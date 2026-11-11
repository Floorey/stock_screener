"""Manual paper intents: immutable preview, durable claim, and read-only reconciliation.

A crashed/ambiguous submission is never retried automatically, including after a 404.
"""
from contextlib import contextmanager
import json
import math
import os
import re
import sqlite3
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
import alpaca_trader as at


class OrderError(ValueError):
    pass


def trading_enabled():
    return os.getenv("ALPACA_TRADING_ENABLED", "false").lower() == "true"


def _decimal(value, name, *, positive=True):
    if isinstance(value, bool):
        raise OrderError(f"{name}: ungültiger Zahlenwert.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OrderError(f"{name}: ungültiger Zahlenwert.") from None
    if not result.is_finite() or (positive and result <= 0):
        raise OrderError(f"{name}: endliche positive Zahl erforderlich.")
    return result


def _number(value, name, *, whole=False, positive=True):
    number = _decimal(value, name, positive=positive)
    if whole and number != number.to_integral_value():
        raise OrderError(f"{name}: ganze Zahl erforderlich.")
    if number.as_tuple().exponent < -9:
        raise OrderError(f"{name}: höchstens neun Nachkommastellen.")
    return format(number.normalize(), "f")


def _symbol(value):
    value = str(value).upper().strip()
    if not re.fullmatch(r"[A-Z][A-Z.]{0,9}|[A-Z]{1,6}\d{6}[CP]\d{8}", value):
        raise OrderError("Ungültiges Aktien-/Optionssymbol.")
    return value


def _option(symbol):
    return bool(re.fullmatch(r"[A-Z]{1,6}\d{6}[CP]\d{8}", symbol))


def normalize_order(order):
    if not isinstance(order, dict):
        raise OrderError("Order muss ein Objekt sein.")
    fields = {"symbol", "qty", "side", "type", "limit_price", "time_in_force", "order_class", "position_intent", "legs"}
    if set(order) - fields:
        raise OrderError("Nicht unterstützte Orderfelder.")
    multi = order.get("order_class", "simple") == "mleg"
    if order.get("order_class", "simple") not in ("simple", "mleg"):
        raise OrderError("Nur einfache oder native MLeg-Orders zugelassen.")
    payload = {"qty": _number(order.get("qty"), "Menge", whole=multi),
               "type": order.get("type", "limit"), "time_in_force": order.get("time_in_force", "day")}
    if payload["type"] not in ("market", "limit") or payload["time_in_force"] not in ("day", "gtc"):
        raise OrderError("Nur Market/Limit und Day/GTC unterstützt.")
    if payload["type"] == "limit":
        payload["limit_price"] = _number(order.get("limit_price"), "Limit", positive=not multi)
        if Decimal(payload["limit_price"]) == 0:
            raise OrderError("Null-Limit wird nicht unterstützt.")
    elif order.get("limit_price") is not None:
        raise OrderError("Market-Orders dürfen kein Limit enthalten.")
    if multi:
        if order.get("symbol") or order.get("side") or order.get("position_intent"):
            raise OrderError("MLeg-Richtung und Symbole gehören in die Legs.")
        legs = order.get("legs")
        if not isinstance(legs, list) or not 2 <= len(legs) <= 4:
            raise OrderError("Native Optionsorders benötigen zwei bis vier Legs.")
        payload["order_class"] = "mleg"
        payload["legs"] = []
        for leg in legs:
            if not isinstance(leg, dict) or set(leg) != {"symbol", "ratio_qty", "side", "position_intent"}:
                raise OrderError("Jedes Leg benötigt Symbol, Ratio, Seite und Position Intent.")
            symbol = _symbol(leg["symbol"])
            if not _option(symbol):
                raise OrderError("MLeg unterstützt ausschließlich Optionskontrakte.")
            payload["legs"].append({"symbol": symbol, "ratio_qty": _number(leg["ratio_qty"], "Ratio", whole=True),
                                    "side": leg["side"], "position_intent": leg["position_intent"]})
        if len({x["symbol"] for x in payload["legs"]}) != len(payload["legs"]):
            raise OrderError("Doppelte Optionslegs sind nicht zugelassen.")
        if math.gcd(*(int(x["ratio_qty"]) for x in payload["legs"])) != 1:
            raise OrderError("Leg-Ratios müssen vollständig gekürzt sein.")
    else:
        if order.get("legs"):
            raise OrderError("Legs erfordern order_class=mleg.")
        payload.update(symbol=_symbol(order.get("symbol", "")), side=order.get("side"))
        if order.get("position_intent"):
            payload["position_intent"] = order["position_intent"]
    for leg in payload.get("legs", [payload]):
        if leg.get("side") not in ("buy", "sell"):
            raise OrderError("Seite muss buy oder sell sein.")
        if _option(leg["symbol"]):
            intent = leg.get("position_intent")
            if intent not in ("buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close") or not intent.startswith(leg["side"]):
                raise OrderError("Optionsseite und Position Intent müssen übereinstimmen.")
            _number(payload["qty"], "Kontrakte", whole=True)
            if payload["type"] != "limit" or payload["time_in_force"] != "day":
                raise OrderError("Optionen verwenden hier Limit/Day ohne Extended Hours.")
    return payload


def _account():
    account = at.get_account_info()
    if account.get("status") != "ACTIVE" or any(account.get(k) for k in ("trading_blocked", "account_blocked", "trade_suspended_by_user")):
        raise OrderError("Konto ist nicht aktiv oder für Handel gesperrt.")
    expected = os.getenv("ALPACA_ACCOUNT_ID", "")
    if expected and account.get("id") != expected:
        raise OrderError("Paper-Konto stimmt nicht mit der serverseitigen Kontozuordnung überein.")
    return account


def _quote(symbol):
    quote = at.get_latest_quote(symbol, option=_option(symbol))
    try:
        stamp = datetime.fromisoformat(quote["t"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        bid, ask = _decimal(quote["bp"], "Bid"), _decimal(quote["ap"], "Ask")
        if not -5 <= age <= 120 or bid > ask or _decimal(quote["bs"], "Bid-Menge") <= 0 or _decimal(quote["as"], "Ask-Menge") <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise OrderError(f"{symbol}: Kurse fehlen, sind veraltet oder ungültig.") from None
    return {"symbol": symbol, "bid": str(bid), "ask": str(ask), "timestamp": quote["t"], "feed": quote["feed"]}


def _preflight(payload):
    account = _account()
    positions = at.get_positions()
    orders = at.get_open_orders()
    if len(orders) >= 500:
        raise OrderError("Offene Orders unvollständig; Handel gesperrt.")
    legs = payload.get("legs", [payload])
    qty = Decimal(payload["qty"])
    quotes, contracts = [], []
    holdings = {p["symbol"]: _decimal(p["qty"], "Positionsmenge", positive=False) for p in positions}
    for leg in legs:
        symbol = leg["symbol"]
        quotes.append(_quote(symbol))
        if _option(symbol):
            c = at.get_option_contract(symbol)
            if c.get("status") != "active" or c.get("tradable") is not True or str(c.get("size")) != "100":
                raise OrderError("Nur aktive, handelbare Standardkontrakte mit Größe 100 zugelassen.")
            try:
                if date.fromisoformat(c["expiration_date"]) <= datetime.now(timezone.utc).date():
                    raise ValueError
            except (KeyError, ValueError):
                raise OrderError("Optionsablauf fehlt oder liegt heute/in der Vergangenheit.") from None
            if c.get("symbol") != symbol or not c.get("underlying_symbol") or c.get("type") not in ("call", "put"):
                raise OrderError("Unvollständige Optionsmetadaten.")
            contracts.append(c)
            count = qty * Decimal(leg.get("ratio_qty", "1"))
            held = holdings.get(symbol, Decimal(0))
            if leg["position_intent"] == "sell_to_close" and held < count:
                raise OrderError("Nicht genügend Long-Kontrakte zum Schließen.")
            if leg["position_intent"] == "buy_to_close" and -held < count:
                raise OrderError("Nicht genügend Short-Kontrakte zum Schließen.")
        else:
            asset = at.get_asset(symbol)
            if asset.get("tradable") is not True:
                raise OrderError("Handelbarkeit nicht bestätigt.")
            if qty != qty.to_integral_value() and (asset.get("fractionable") is not True or payload["type"] != "market" or payload["time_in_force"] != "day"):
                raise OrderError("Bruchstücke benötigen Fractionable sowie Market/Day.")
            if leg["side"] == "sell" and qty > holdings.get(symbol, Decimal(0)):
                if account.get("shorting_enabled") is not True:
                    raise OrderError("Short-Freigabe für das Paper-Konto nicht bestätigt.")
                if asset.get("shortable") is not True or asset.get("easy_to_borrow") is not True or qty != qty.to_integral_value():
                    raise OrderError("Leihbarkeit/Shortbarkeit für diese Order nicht bestätigt.")
    symbols = {x["symbol"] for x in legs}
    underlyings = {c["underlying_symbol"] for c in contracts}
    def conflicts(order):
        symbol = order.get("symbol", "")
        return symbol in symbols or symbol in underlyings or any(symbol.startswith(u) and _option(symbol) for u in underlyings) or any(conflicts(x) for x in order.get("legs") or [])
    if any(conflicts(o) for o in orders):
        raise OrderError("Offene Orders betreffen diese Position/Deckung. Erst prüfen oder stornieren.")
    required = Decimal(0)
    if contracts:
        level = int(account.get("options_trading_level") or 0)
        if "options_approved_level" in account:
            level = min(level, int(account["options_approved_level"] or 0))
        if payload.get("order_class") == "mleg":
            if level < 3 or len(underlyings) != 1:
                raise OrderError("Native MLeg benötigt Optionslevel 3 und einen gemeinsamen Basiswert.")
            if len({c["expiration_date"] for c in contracts}) != 1:
                raise OrderError("MLeg benötigt hier dieselbe Laufzeit; Kalender/Rolls sind nicht freigegeben.")
            intents = {leg["position_intent"].split("_to_")[1] for leg in legs}
            if len(intents) != 1:
                raise OrderError("Öffnen und Schließen dürfen hier nicht in einer Order gemischt werden.")
            call_balance = sum((1 if leg["side"] == "buy" else -1) * int(leg["ratio_qty"])
                               for leg, c in zip(legs, contracts) if c["type"] == "call")
            if intents == {"open"} and call_balance < 0:
                raise OrderError("Ungedeckte Short-Call-Ratios sind auch in MLeg gesperrt.")
            # shortcut: collateral is conservatively bounded by all short strikes plus debit, not a margin optimizer.
            required = max(Decimal(payload["limit_price"]), 0) * qty * 100
            for leg, c in zip(legs, contracts):
                if leg["position_intent"] == "sell_to_open":
                    required += _decimal(c["strike_price"], "Strike") * qty * Decimal(leg["ratio_qty"]) * 100
            if required > _decimal(account.get("options_buying_power", "0"), "Optionskaufkraft", positive=False):
                raise OrderError("Konservativ ermittelte Deckung übersteigt Optionskaufkraft.")
        else:
            leg, c = legs[0], contracts[0]
            if leg["position_intent"] == "buy_to_open":
                if level < 2:
                    raise OrderError("Long-Optionen benötigen Optionslevel 2.")
                required = Decimal(payload["limit_price"]) * qty * 100
            elif leg["position_intent"] == "sell_to_open":
                if level < 1:
                    raise OrderError("Short-Optionen benötigen Optionslevel 1 und bestätigte Deckung.")
                if c["type"] == "call":
                    if holdings.get(c["underlying_symbol"], Decimal(0)) < qty * 100:
                        raise OrderError("Ungedeckte Short-Calls sind gesperrt.")
                    if any(_option(p["symbol"]) and p["symbol"].startswith(c["underlying_symbol"]) and Decimal(p["qty"]) < 0 for p in positions):
                        raise OrderError("Bestehende Short-Optionen: freie Aktien-Deckung nicht eindeutig.")
                else:
                    required = _decimal(c["strike_price"], "Strike") * qty * 100
                    if required > _decimal(account.get("cash", "0"), "Cash", positive=False):
                        raise OrderError("Cash-Secured Put ist nicht vollständig gedeckt.")
            if level < 1 or required > _decimal(account.get("options_buying_power", "0"), "Optionskaufkraft", positive=False):
                raise OrderError("Optionsfreigabe oder Optionskaufkraft fehlt.")
    else:
        price = Decimal(payload["limit_price"]) if payload["type"] == "limit" else Decimal(quotes[0]["ask"])
        reducing_long = payload["side"] == "sell" and holdings.get(payload["symbol"], Decimal(0)) >= qty
        reducing_short = payload["side"] == "buy" and -holdings.get(payload["symbol"], Decimal(0)) >= qty
        required = Decimal(0) if reducing_long or reducing_short else qty * price
        if required > _decimal(account.get("buying_power", "0"), "Kaufkraft", positive=False):
            raise OrderError("Orderbetrag übersteigt aktuelle Kaufkraft.")
    net_quote = sum((Decimal(q["ask"]) if leg["side"] == "buy" else -Decimal(q["bid"]))
                    * Decimal(leg.get("ratio_qty", "1")) for leg, q in zip(legs, quotes))
    return {"account_id": account["id"], "environment": "PAPER", "quotes": quotes,
            "estimated_unit_debit": str(net_quote), "indicative_quotes": any(q["feed"] == "indicative" for q in quotes),
            "conservative_required_usd": str(required), "checked_at": datetime.now(timezone.utc).isoformat()}


def _connect():
    path = Path(os.getenv("ALPACA_ORDER_DB", str(Path(__file__).parent / "data" / "paper-orders.sqlite")))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS order_intents (
        intent_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, client_order_id TEXT UNIQUE NOT NULL,
        payload TEXT NOT NULL, preview TEXT NOT NULL, expires_at REAL NOT NULL,
        state TEXT NOT NULL, broker_order TEXT, created_at REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS order_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL,
        state TEXT NOT NULL, detail TEXT NOT NULL, recorded_at REAL NOT NULL)""")
    db.commit()
    return db


@contextmanager
def _db():
    db = _connect()
    try:
        with db:
            yield db
    finally:
        db.close()


def _event(db, intent_id, state, detail):
    db.execute("INSERT INTO order_events(intent_id,state,detail,recorded_at) VALUES (?,?,?,?)",
               (intent_id, state, json.dumps(detail, sort_keys=True), time.time()))


def _decoded(row):
    result = dict(row)
    for field in ("payload", "preview", "broker_order"):
        result[field] = json.loads(result[field]) if result[field] else None
    return result


def get_intent(intent_id):
    with _db() as db:
        row = db.execute("SELECT * FROM order_intents WHERE intent_id=?", (intent_id,)).fetchone()
    if row is None:
        raise OrderError("Ordervorschau nicht gefunden.")
    return _decoded(row)


def list_intents(limit=30):
    with _db() as db:
        return [_decoded(r) for r in db.execute("SELECT * FROM order_intents ORDER BY created_at DESC LIMIT ?", (min(int(limit), 100),))]


def _record(intent_id, state, broker_order=None, detail=None):
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE order_intents SET state=?,broker_order=? WHERE intent_id=?",
                   (state, json.dumps(broker_order) if broker_order else None, intent_id))
        _event(db, intent_id, state, detail or {})
    return get_intent(intent_id)


def _validate_reduction(payload):
    if payload.get("legs"):
        raise OrderError("Reduzierender Positionsschluss wird nur je Einzelposition unterstützt.")
    position = at.get_position_for_symbol(payload["symbol"])
    if not position:
        raise OrderError("Position zum Schließen existiert nicht mehr.")
    held = _decimal(position["qty"], "Bestand", positive=False)
    qty = Decimal(payload["qty"])
    required_side = "sell" if held > 0 else "buy"
    if held == 0 or payload["side"] != required_side or qty > abs(held):
        raise OrderError("Positionsschluss würde die Position überdrehen oder vergrößern.")


def preview_close_position(symbol, qty, *, order_type="limit", limit_price=None, time_in_force="day"):
    symbol = _symbol(symbol)
    position = at.get_position_for_symbol(symbol)
    if not position:
        raise OrderError("Broker bestätigt keine Position für dieses Symbol.")
    held = _decimal(position["qty"], "Bestand", positive=False)
    side = "sell" if held > 0 else "buy"
    payload = {"symbol": symbol, "qty": qty, "side": side, "type": order_type, "time_in_force": time_in_force}
    if order_type == "limit":
        payload["limit_price"] = limit_price
    if _option(symbol):
        payload["position_intent"] = "sell_to_close" if held > 0 else "buy_to_close"
    return preview_order(payload, reducing_only=True)


def preview_order(order, *, reducing_only=False):
    payload = normalize_order(order)
    checked = _preflight(payload)
    if reducing_only:
        _validate_reduction(payload)
        checked["reducing_only"] = True
    identity = uuid.uuid4().hex
    client_id = "bg-" + identity
    payload["client_order_id"] = client_id
    now = time.time()
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM order_intents WHERE account_id=? AND state IN ('preview','submitting','unknown')",
                              (checked["account_id"],)).fetchall()
        for row in existing:
            if row["state"] in ("submitting", "unknown"):
                raise OrderError("Ungeklärte Brokerübermittlung vorhanden. Erst per Client-ID abgleichen; keine neue Order.")
            previous = json.loads(row["payload"])
            previous.pop("client_order_id", None)
            if row["expires_at"] >= now and previous == normalize_order(order) and bool(json.loads(row["preview"]).get("reducing_only")) == bool(reducing_only):
                return _decoded(row)
        db.execute("INSERT INTO order_intents VALUES (?,?,?,?,?,?,?,?,?)",
                   (identity, checked["account_id"], client_id, json.dumps(payload, sort_keys=True),
                    json.dumps(checked, sort_keys=True), now + 300, "preview", None, now))
        _event(db, identity, "preview", {"payload": payload, "checks": checked})
    return get_intent(identity)


def reconcile_order(intent_id):
    intent = get_intent(intent_id)
    account = _account()
    if account["id"] != intent["account_id"]:
        raise OrderError("Kontowechsel: Abgleich für diese Order nicht zulässig.")
    if intent["state"] == "preview":
        return intent
    if intent["payload"].get("action") == "cancel":
        order = at.get_order(intent["payload"]["order_id"])
        status = order.get("status")
        state = "canceled" if status == "canceled" else "not_canceled" if status in ("filled", "expired", "rejected") else intent["state"]
        return _record(intent_id, state, order or None, {"source": "cancel_reconciliation"})
    order = at.get_order_by_client_id(intent["client_order_id"])
    if order is None:
        # shortcut: unresolved writes remain locked forever; operator must resolve against broker records.
        return intent
    if not order.get("id") or not order.get("status"):
        raise OrderError("Broker-Abgleich enthält keine gültige Orderidentität/Status.")
    return _record(intent_id, "submitted", order, {"source": "broker_reconciliation"})


def confirm_order(intent_id, *, confirmed=False):
    if confirmed is not True:
        raise OrderError("Die angezeigte Paper-Order muss ausdrücklich bestätigt werden.")
    if not trading_enabled():
        raise OrderError("Paper-Handel ist serverseitig gesperrt; Abnahme/Freigabe ausstehend.")
    intent = get_intent(intent_id)
    account = _account()
    if not os.getenv("ALPACA_ACCOUNT_ID") or account["id"] != intent["account_id"]:
        raise OrderError("Eine übereinstimmende serverseitige Paper-Kontozuordnung ist erforderlich.")
    if intent["state"] != "preview":
        return reconcile_order(intent_id) if intent["state"] in ("submitting", "unknown") else intent
    if time.time() > intent["expires_at"]:
        raise OrderError("Vorschau abgelaufen. Bitte erneut prüfen und bestätigen.")
    payload = {k: v for k, v in intent["payload"].items() if k != "client_order_id"}
    checked = _preflight(payload)
    if intent["preview"].get("reducing_only"):
        _validate_reduction(payload)
    if checked["account_id"] != intent["account_id"]:
        raise OrderError("Paper-Konto hat sich seit Vorschau geändert.")
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        unresolved = db.execute("SELECT intent_id FROM order_intents WHERE account_id=? AND intent_id<>? AND state IN ('submitting','unknown') LIMIT 1",
                                (intent["account_id"], intent_id)).fetchone()
        if unresolved:
            raise OrderError("Andere Brokerübermittlung ungeklärt; zuerst abgleichen.")
        if time.time() > intent["expires_at"]:
            raise OrderError("Vorschau während Prüfung abgelaufen.")
        claimed = db.execute("UPDATE order_intents SET state='submitting' WHERE intent_id=? AND state='preview'", (intent_id,)).rowcount
        if claimed:
            _event(db, intent_id, "submitting", {"checks": checked})
    if not claimed:
        return get_intent(intent_id)
    # Claim is durable before network I/O. A timeout, crash, or duplicate click must not repost.
    try:
        response = at._paper_write("post", "/v2/orders", intent["payload"])
    except (requests.RequestException, at.AlpacaReadError):
        return _record(intent_id, "unknown", detail={"reason": "transport_ambiguous", "resubmit": False})
    try:
        order = response.json()
    except ValueError:
        order = {}
    if response.status_code in (200, 201) and isinstance(order, dict) and order.get("id") and order.get("status"):
        return _record(intent_id, "submitted", order, {"http_status": response.status_code})
    if 400 <= response.status_code < 500 and response.status_code not in (408, 409, 429):
        return _record(intent_id, "rejected", detail={"http_status": response.status_code})
    return _record(intent_id, "unknown", detail={"http_status": response.status_code, "resubmit": False})


def preview_cancel(intent_id):
    original = reconcile_order(intent_id)
    order = original.get("broker_order") or {}
    if not order.get("id"):
        raise OrderError("Brokerorder für diese Vorschau nicht bestätigt.")
    return preview_cancel_broker_order(order["id"])


def preview_cancel_broker_order(order_id):
    account = _account()
    order = at.get_order(order_id)
    if order.get("status") in ("filled", "canceled", "expired", "rejected", "done_for_day", "replaced"):
        raise OrderError("Nur bestätigte offene Brokerorders können storniert werden.")
    identity = uuid.uuid4().hex
    now = time.time()
    payload = {"action": "cancel", "order_id": order_id}
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT * FROM order_intents WHERE account_id=?", (account["id"],)):
            if json.loads(row["payload"]) == payload and (row["state"] != "preview" or row["expires_at"] >= now):
                return _decoded(row)
        db.execute("INSERT INTO order_intents VALUES (?,?,?,?,?,?,?,?,?)", (
            identity, account["id"], "cancel-" + identity, json.dumps(payload),
            json.dumps({"account_id": account["id"], "environment": "PAPER", "broker_order": order}),
            now + 300, "preview", None, now))
        _event(db, identity, "preview", payload)
    return get_intent(identity)


def confirm_cancel(intent_id, *, confirmed=False):
    intent = get_intent(intent_id)
    if confirmed is not True or not trading_enabled() or not os.getenv("ALPACA_ACCOUNT_ID"):
        raise OrderError("Stornierung benötigt Freigabe und ausdrückliche Bestätigung.")
    if _account()["id"] != intent["account_id"] or intent["payload"].get("action") != "cancel":
        raise OrderError("Ungültige Stornovorschau oder Kontowechsel.")
    if intent["state"] != "preview":
        return reconcile_order(intent_id)
    if time.time() > intent["expires_at"]:
        raise OrderError("Stornovorschau abgelaufen.")
    order = at.get_order(intent["payload"]["order_id"])
    if order.get("status") in ("filled", "canceled", "expired", "rejected", "replaced"):
        return _record(intent_id, "canceled" if order["status"] == "canceled" else "not_canceled", order)
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        claimed = db.execute("UPDATE order_intents SET state='submitting' WHERE intent_id=? AND state='preview'", (intent_id,)).rowcount
        if claimed:
            _event(db, intent_id, "submitting", {"action": "cancel"})
    if not claimed:
        return get_intent(intent_id)
    try:
        response = at._paper_write("delete", "/v2/orders/" + intent["payload"]["order_id"])
    except (requests.RequestException, at.AlpacaReadError):
        return _record(intent_id, "unknown", detail={"reason": "cancel_transport_ambiguous"})
    return _record(intent_id, "cancel_pending" if response.status_code == 204 else "unknown",
                   detail={"http_status": response.status_code})
