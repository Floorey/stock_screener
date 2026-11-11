"""Explicit manual paper order workflow; legacy automation has no write authority."""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import streamlit as st
import alpaca_trader as at
import paper_orders as po


def stage_option(state, symbol, side="buy", *, add_leg=False, limit=""):
    """Pass a selected contract to the ticket; never creates or submits an order."""
    normalized = po.normalize_order({"symbol": symbol, "qty": 1, "side": side,
                                     "position_intent": side + "_to_open", "type": "limit",
                                     "limit_price": "1", "time_in_force": "day"})
    if not po._option(normalized["symbol"]):
        raise po.OrderError("Bitte einen Optionskontrakt auswählen.")
    state["paper_ticket_selection"] = {"symbol": normalized["symbol"], "side": side,
                                       "add_leg": add_leg, "limit": str(limit)}


def _apply_selection(state):
    selection = state.pop("paper_ticket_selection", None)
    if not selection:
        return
    state.pop("paper_preview", None)
    symbol, side = selection["symbol"], selection["side"]
    if selection["add_leg"]:
        empty = [i for i in range(4) if not str(state.get(f"leg_symbol_{i}", "")).strip()]
        if not empty:
            raise po.OrderError("Vier Legs vorhanden. Bitte Ticket leeren, bevor weitere Legs übernommen werden.")
        count = empty[0]
        state["manual_instrument"] = "Native Optionskombination (2–4 Legs)"
        state["manual_leg_count"] = max(state.get("manual_leg_count", 2), count + 1)
        state[f"leg_symbol_{count}"] = symbol
        state[f"leg_side_{count}"] = side
        state[f"leg_intent_{count}"] = side + "_to_open"
        state["paper_staged_leg_count"] = count + 1
        state["manual_limit"] = ""
    else:
        for key in list(state):
            if key.startswith("leg_"):
                del state[key]
        state["manual_instrument"] = "Einzeloption"
        state["manual_symbol"] = symbol
        state["manual_side"] = side
        state["manual_position_intent"] = side + "_to_open"
        state["manual_limit"] = selection["limit"]
        state["paper_staged_leg_count"] = 0
    state["manual_order_type"] = "limit"
    state["manual_tif"] = "day"


def _contract_search(account_id):
    with st.expander("Optionen suchen und direkt ins Ticket übernehmen", expanded=True):
        today = datetime.now(ZoneInfo("America/New_York")).date()
        with st.form("paper_contract_search"):
            underlying = st.text_input("Basiswert", "SPY", key="paper_search_underlying").strip().upper()
            first = st.date_input("Verfall ab", today + timedelta(days=1), key="paper_search_first")
            last = st.date_input("Verfall bis", today + timedelta(days=45), key="paper_search_last")
            search = st.form_submit_button("Handelbare Optionen bei Alpaca suchen")
        if search:
            st.session_state.pop("paper_contract_catalog", None)
            try:
                with st.spinner("Lade handelbare Optionskontrakte..."):
                    contracts = at.list_option_contracts(underlying, first.isoformat(), last.isoformat())
            except at.AlpacaReadError as exc:
                st.error(f"Optionssuche: {exc}")
                return
            spot, spot_time = None, None
            try:
                underlying_quote = at.get_latest_quote(underlying)
                bid, ask = Decimal(str(underlying_quote["bp"])), Decimal(str(underlying_quote["ap"]))
                if bid.is_finite() and ask.is_finite() and 0 < bid <= ask:
                    spot, spot_time = (bid + ask) / 2, underlying_quote.get("t")
            except (at.AlpacaReadError, KeyError, ValueError, ArithmeticError):
                pass
            st.session_state["paper_contract_catalog"] = {"account_id": account_id, "contracts": contracts,
                                                           "spot": spot, "spot_time": spot_time}
        catalog = st.session_state.get("paper_contract_catalog", {})
        contracts = catalog.get("contracts", []) if catalog.get("account_id") == account_id else []
        if not contracts:
            if search:
                st.info("Keine handelbaren Standardkontrakte im gewählten Fenster gefunden.")
            return
        expiry = st.selectbox("Verfall auswählen", sorted({c["expiration_date"] for c in contracts}), key="paper_contract_expiry")
        kind = st.selectbox("Call / Put", ["call", "put"], key="paper_contract_type")
        chain = sorted((c for c in contracts if c["expiration_date"] == expiry and c["type"] == kind),
                       key=lambda c: Decimal(str(c["strike_price"])))
        if not chain:
            st.info("Für diesen Verfall und Typ wurden keine Kontrakte gefunden.")
            return
        lookup = {c["symbol"]: c for c in chain}
        spot = catalog.get("spot")
        closest = min(range(len(chain)), key=lambda i: abs(Decimal(str(chain[i]["strike_price"])) - spot)) if spot else 0
        if spot:
            st.caption(f"Zuletzt vorliegender Basiswertkurs: {spot} USD · {catalog.get('spot_time')}. Auswahl startet beim nächstgelegenen Strike.")
        symbol = st.selectbox("Strike auswählen", list(lookup), index=closest, key="paper_selected_contract",
                              format_func=lambda s: f"{lookup[s]['underlying_symbol']} · {expiry} · {kind.upper()} · Strike {lookup[s]['strike_price']}")
        side = st.selectbox("Gewünschte Aktion", ["buy", "sell"], key="paper_contract_side",
                            format_func=lambda value: "Kaufen" if value == "buy" else "Verkaufen")
        st.caption(f"{len(contracts)} handelbare Kontrakte geladen · Alpaca-Kontrakt: {symbol}")
        price = ""
        try:
            quote = at.get_latest_quote(symbol, option=True)
            st.write({"Bid": quote.get("bp"), "Ask": quote.get("ap"), "Feed": quote.get("feed"), "Kurszeit": quote.get("t")})
            if quote.get("feed") == "indicative":
                st.caption("Indicative: veränderte Quotes, keine offiziellen OPRA-Quotes. Die Frischeprüfung erfolgt bei der Vorschau.")
            value = Decimal(str(quote.get("ap" if side == "buy" else "bp", 0)))
            if value.is_finite() and value > 0:
                price = format(value, "f")
        except (at.AlpacaReadError, ValueError, ArithmeticError) as exc:
            st.warning(f"Kontrakt auswählbar; Quote derzeit nicht verfügbar: {exc}")
        a, b = st.columns(2)
        if a.button("In Einzelorder übernehmen", key="paper_take_single"):
            stage_option(st.session_state, symbol, side, limit=price)
        if b.button("Als Kombinations-Leg hinzufügen", key="paper_take_leg"):
            stage_option(st.session_state, symbol, side, add_leg=True)


def offer_screener_ticket(frame, key):
    if frame.empty or "contractSymbol" not in frame:
        return
    symbols = frame["contractSymbol"].dropna().astype(str).tolist()
    if not symbols:
        return
    symbol = st.selectbox("Kontrakt ins Paper-Ticket übernehmen", symbols, key=key+"_contract")
    buy, sell = st.columns(2)
    if buy.button("Kaufticket vorbereiten", key=key+"_buy"):
        stage_option(st.session_state, symbol, "buy")
        st.success("Kaufticket im Reiter Alpaca Trading vorausgefüllt; noch keine Order gesendet.")
    if sell.button("Verkaufsticket vorbereiten", key=key+"_sell"):
        stage_option(st.session_state, symbol, "sell")
        st.success("Verkaufsticket im Reiter Alpaca Trading vorausgefüllt; noch keine Order gesendet.")


def _confirmation(intent):
    st.subheader("Verbindliche Paper-Vorschau")
    st.caption(f"Konto: {intent['account_id']} · PAPER · Vorschau: {intent['intent_id']}")
    st.json(intent["payload"])
    st.json(intent["preview"])
    st.caption("Deckung wird konservativ über alle Short-Strikes und Debits geschätzt, nicht als Broker-Marginoptimierung. Optionen mit Ablauf heute, Kalender/Rolls und ungedeckte Call-Ratios sind gesperrt.")
    if intent["preview"].get("indicative_quotes"):
        st.warning("Indicative-Optionsquotes sind verändert und keine offiziellen OPRA-Quotes. Feed und Zeitstempel vor Bestätigung prüfen.")
    st.caption("Market-Kurse sind Schätzungen; das Broker-Fill bestimmt Ausführungspreis und Menge. Limit-Orders können offen bleiben.")
    confirmed = st.checkbox("Ich habe Konto, Symbole, Legs, Mengen und Limit dieser Paper-Vorschau geprüft.", key="confirm_" + intent["intent_id"])
    if st.button("Diese Paper-Order verbindlich senden", disabled=not confirmed or not po.trading_enabled(), key="send_" + intent["intent_id"]):
        result = po.confirm_cancel(intent["intent_id"], confirmed=True) if intent["payload"].get("action") == "cancel" else po.confirm_order(intent["intent_id"], confirmed=True)
        st.session_state["paper_preview"] = result["intent_id"]
        st.json({"state": result["state"], "broker_order": result["broker_order"]})
        if result["state"] in ("unknown", "submitting"):
            st.warning("Übermittlung ungeklärt. Keine neue Order erzeugen; Brokerstatus über Client-ID abgleichen.")
        else:
            st.info("Brokerantwort gespeichert. Nur der Brokerstatus 'filled' bedeutet vollständig ausgeführt.")


def render_paper_order_tab():
    st.markdown("## 💼 Alpaca Paper Portfolio & Trading Desk")
    st.info("Manuelle Paper-Orders benötigen Vorschau und Bestätigung. Direkte Schnellorders, Bots, Skripte und automatische Hedges sind gesperrt.")
    if not po.trading_enabled():
        st.warning("Handelsfreigabe gesperrt: technische Abnahme und serverseitige Freigabe stehen aus. Research und Vorschau bleiben verfügbar.")
    else:
        st.success("Manueller Paper-Handel freigegeben. Jede Order erfordert deine Bestätigung in dieser Oberfläche.")
    if not at.is_alpaca_configured():
        st.warning("Alpaca Paper ist serverseitig nicht konfiguriert. Keine Schlüssel im Browser eingeben.")
        return
    try:
        account = at.get_account_info()
        st.caption(f"PAPER · Konto {account['id']} · Status {account.get('status', 'unbekannt')}")
        positions = at.get_positions()
        orders = at.get_open_orders()
        a, b, c = st.columns(3)
        a.metric("Equity (USD)", account.get("equity", "unbekannt"))
        b.metric("Cash (USD)", account.get("cash", "unbekannt"))
        c.metric("Optionslevel", account.get("options_trading_level", "unbekannt"))
        st.subheader("Offene Positionen")
        st.dataframe(positions, use_container_width=True) if positions else st.info("Broker bestätigt: keine offenen Positionen.")
        st.subheader("Offene Brokerorders")
        st.dataframe(orders, use_container_width=True) if orders else st.info("Broker bestätigt: keine offenen Orders.")
        if orders:
            with st.expander("Offene Brokerorder stornieren (mit Vorschau)"):
                broker_order_id = st.selectbox("Broker-Order-ID", [o["id"] for o in orders], key="external_cancel_order")
                if st.button("Stornovorschau für diese Brokerorder erstellen"):
                    st.session_state["paper_preview"] = po.preview_cancel_broker_order(broker_order_id)["intent_id"]
        if positions:
            with st.expander("Bestehende Position reduzieren / schließen (mit Vorschau)"):
                position_symbol = st.selectbox("Bestehende Position", [p["symbol"] for p in positions], key="close_position_symbol")
                close_qty = st.text_input("Zu schließende Menge (positiv)", "1", key="close_quantity")
                close_limit = st.text_input("Limit für Positionsschluss (USD)", key="close_limit_price")
                st.caption("Positionsschluss ist auf den bestätigten Bestand begrenzt und wird vor Übermittlung erneut geprüft.")
                if st.button("Reduzierenden Positionsschluss prüfen"):
                    st.session_state["paper_preview"] = po.preview_close_position(position_symbol, close_qty, limit_price=close_limit)["intent_id"]
        st.subheader("Manuelles Orderticket")
        _contract_search(account["id"])
        if st.button("Ticket leeren", key="paper_clear_ticket"):
            for key in list(st.session_state):
                if key.startswith(("manual_", "leg_")) or key in ("paper_preview", "paper_ticket_selection", "paper_staged_leg_count"):
                    del st.session_state[key]
        _apply_selection(st.session_state)
        kind = st.selectbox("Instrument", ["Aktie / ETF", "Einzeloption", "Native Optionskombination (2–4 Legs)"], key="manual_instrument")
        leg_count = st.selectbox("Anzahl Optionslegs", [2, 3, 4], key="manual_leg_count") if kind.startswith("Native") else 0
        with st.form("manual_paper_ticket"):
            qty = st.text_input("Menge (bei Kombinationen: Anzahl Strategien)", "1")
            multi = kind.startswith("Native")
            if not multi:
                symbol = st.text_input("Symbol / OCC-Kontrakt", "SPY" if kind == "Aktie / ETF" else "", key="manual_symbol")
                side = st.selectbox("Seite", ["buy", "sell"], key="manual_side")
                position_intent = st.selectbox("Position Intent", ["buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"], key="manual_position_intent") if kind == "Einzeloption" else None
            else:
                st.caption("Zwei bis vier unterschiedliche Standardkontrakte, gleicher Basiswert und Verfall. Keine Kalender/Rolls, keine ungedeckten Call-Ratios.")
                legs = []
                for idx in range(leg_count):
                    st.markdown(f"**Leg {idx + 1}**")
                    columns = st.columns([3, 1, 1, 2])
                    leg_symbol = columns[0].text_input("OCC-Kontrakt", key=f"leg_symbol_{idx}")
                    ratio = columns[1].number_input("Ratio", min_value=1, value=1, step=1, key=f"leg_ratio_{idx}")
                    leg_side = columns[2].selectbox("Seite", ["buy", "sell"], index=idx % 2, key=f"leg_side_{idx}")
                    leg_intent = columns[3].selectbox("Position Intent", ["buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close"], index=0 if idx % 2 == 0 else 2, key=f"leg_intent_{idx}")
                    legs.append({"symbol": leg_symbol, "ratio_qty": ratio, "side": leg_side, "position_intent": leg_intent})
            order_type = st.selectbox("Ordertyp", ["limit", "market"] if kind == "Aktie / ETF" else ["limit"], key="manual_order_type")
            limit = st.text_input("Limit (USD; Kombination: positiv = Netto-Debit, negativ = Netto-Credit)", "", key="manual_limit")
            tif = st.selectbox("Gültigkeit", ["day", "gtc"] if kind == "Aktie / ETF" else ["day"], key="manual_tif")
            preview = st.form_submit_button("Vorschau prüfen und speichern")
        if preview:
            payload = {"qty": qty, "type": order_type, "time_in_force": tif}
            if order_type == "limit":
                payload["limit_price"] = limit
            if multi:
                payload.update(order_class="mleg", legs=legs)
            else:
                payload.update(symbol=symbol, side=side)
                if position_intent:
                    payload["position_intent"] = position_intent
            st.session_state["paper_preview"] = po.preview_order(payload)["intent_id"]
        if st.session_state.get("paper_preview"):
            _confirmation(po.get_intent(st.session_state["paper_preview"]))
        st.subheader("Dauerhaftes Orderprotokoll")
        intents = [x for x in po.list_intents() if x["account_id"] == account["id"]]
        st.dataframe([{k: x[k] for k in ("intent_id", "client_order_id", "state", "created_at")} for x in intents], use_container_width=True)
        if intents:
            selected = st.selectbox("Protokollierte Order", [x["intent_id"] for x in intents])
            c1, c2 = st.columns(2)
            if c1.button("Brokerstatus abgleichen (nur lesen)"):
                st.json(po.reconcile_order(selected))
            if c2.button("Stornovorschau erstellen"):
                st.session_state["paper_preview"] = po.preview_cancel(selected)["intent_id"]
                st.rerun()
    except (po.OrderError, at.AlpacaReadError, ValueError, KeyError) as exc:
        st.error(f"Paper-Desk: {exc}")
