"""Paper-only broker reads. Writes are exclusively previewed through paper_orders."""
import os
import re
from typing import Any
from urllib.parse import quote

import requests

PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"
BLOCKED_MESSAGE = "Direkte/automatische Ausführung gesperrt. Bitte den manuellen Paper-Desk mit Vorschau und Bestätigung verwenden."


class AlpacaReadError(RuntimeError):
    def __init__(self, message, status_code=None, retry_after=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.retryable = retryable


def load_paper_credentials(env_path=None):
    """Refresh only Alpaca credentials from the explicit project .env on reruns."""
    from pathlib import Path
    from dotenv import dotenv_values
    path = Path(env_path) if env_path is not None else Path(__file__).with_name(".env")
    values = dotenv_values(path)
    for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
        if name in values:
            os.environ[name] = values[name] or ""


def get_alpaca_credentials():
    base = os.getenv("ALPACA_BASE_URL", PAPER_URL).strip()
    if base != PAPER_URL:
        raise AlpacaReadError("Nur der exakte Alpaca-Paper-Endpunkt ist zugelassen.")
    return (os.getenv("ALPACA_API_KEY", "").strip(),
            os.getenv("ALPACA_SECRET_KEY", "").strip(), base)


def get_alpaca_headers():
    key, secret, _ = get_alpaca_credentials()
    if not key or not secret:
        raise AlpacaReadError("Alpaca-Paper-Schlüssel sind serverseitig nicht vollständig konfiguriert.")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Content-Type": "application/json"}


def is_alpaca_configured():
    try:
        key, secret, _ = get_alpaca_credentials()
        return bool(key and secret)
    except AlpacaReadError:
        return False


def analytics_alpaca_get(path, params=None, *, data_api=True):
    if not isinstance(path, str) or not path.startswith(("/v2/", "/v1beta1/")) or any(c in path for c in ("://", "?", "#", "..")):
        raise AlpacaReadError("Unzulässiger Alpaca-Lesepfad.")
    host = DATA_URL if data_api else get_alpaca_credentials()[2]
    try:
        response = requests.get(host + path, headers=get_alpaca_headers(), params=params,
                                timeout=15, allow_redirects=False)
    except requests.RequestException:
        raise AlpacaReadError("Alpaca-Leseanfrage fehlgeschlagen oder Zeitüberschreitung.", retryable=True) from None
    if response.status_code != 200:
        raise AlpacaReadError(f"Alpaca-Leseanfrage: HTTP {response.status_code}.",
                              response.status_code, response.headers.get("Retry-After"))
    try:
        result = response.json()
    except ValueError:
        raise AlpacaReadError("Alpaca hat ungültiges JSON geliefert.") from None
    if not isinstance(result, (dict, list)):
        raise AlpacaReadError("Unerwartetes Alpaca-Antwortformat.")
    return result


def broker_get(path, params=None):
    return analytics_alpaca_get(path, params, data_api=False)


def get_account_info():
    result = broker_get("/v2/account")
    if not isinstance(result, dict) or not result.get("id"):
        raise AlpacaReadError("Alpaca-Kontoidentität fehlt.")
    return result


def verify_alpaca_connection():
    try:
        account = get_account_info()
        return True, f"PAPER verbunden; Konto {str(account['id'])[-8:]}; Status {account.get('status', 'unbekannt')}."
    except AlpacaReadError as exc:
        return False, str(exc)


def _list(path, params=None):
    result = broker_get(path, params)
    if not isinstance(result, list):
        raise AlpacaReadError("Alpaca hat keine gültige Liste geliefert.")
    return result


def get_positions():
    return _list("/v2/positions")


def get_open_orders():
    return _list("/v2/orders", {"status": "open", "limit": 500, "nested": "true"})


def get_asset(symbol):
    return broker_get("/v2/assets/" + quote(symbol, safe=""))


def get_option_contract(symbol):
    return broker_get("/v2/options/contracts/" + quote(symbol, safe=""))


def list_option_contracts(underlying, start, end):
    """Complete broker catalog for an explicit expiry window; no market-data subscription needed."""
    from datetime import date
    if not isinstance(underlying, str) or not re.fullmatch(r"[A-Z][A-Z.]{0,9}", underlying):
        raise AlpacaReadError("Ungültiger Basiswert.")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first > last or (last-first).days > 90:
            raise ValueError
    except (ValueError, TypeError):
        raise AlpacaReadError("Verfallsfenster muss gültig und höchstens 90 Tage lang sein.") from None
    params = {"underlying_symbols": underlying, "expiration_date_gte": start,
              "expiration_date_lte": end, "status": "active", "limit": 1000}
    contracts, seen, cursors = [], set(), set()
    for _ in range(100):
        result = broker_get("/v2/options/contracts", params)
        if not isinstance(result, dict) or not isinstance(result.get("option_contracts"), list):
            raise AlpacaReadError("Ungültiger Optionskatalog vom Broker.")
        for contract in result["option_contracts"]:
            if not isinstance(contract, dict):
                raise AlpacaReadError("Ungültiger Optionskontrakt vom Broker.")
            symbol = contract.get("symbol")
            if (contract.get("underlying_symbol") != underlying or contract.get("status") != "active"
                    or contract.get("tradable") is not True or str(contract.get("size")) != "100"):
                continue
            if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z]{1,6}\d{6}[CP]\d{8}", symbol):
                raise AlpacaReadError("Optionskatalog enthält ein ungültiges Kontraktsymbol.")
            try:
                from decimal import Decimal
                expiry = date.fromisoformat(contract["expiration_date"])
                strike = Decimal(str(contract["strike_price"]))
                if not first <= expiry <= last or contract.get("type") not in ("call", "put") or not strike.is_finite() or strike <= 0:
                    raise ValueError
            except (KeyError, ValueError, ArithmeticError):
                raise AlpacaReadError("Optionskatalog enthält ungültige Verfalls-/Strike-Daten.") from None
            if symbol not in seen:
                contracts.append(contract)
                seen.add(symbol)
        cursor = result.get("next_page_token")
        if not cursor:
            return contracts
        if not isinstance(cursor, str) or cursor in cursors:
            raise AlpacaReadError("Optionskatalog wiederholt seine Seitennummer.")
        cursors.add(cursor)
        params = {**params, "page_token": cursor}
    raise AlpacaReadError("Optionskatalog zu groß. Bitte engeres Verfallsfenster wählen.")


def get_order(order_id):
    if not isinstance(order_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", order_id):
        raise AlpacaReadError("Ungültige Broker-Order-ID.")
    result = broker_get("/v2/orders/" + order_id)
    if not isinstance(result, dict) or result.get("id") != order_id or not result.get("status"):
        raise AlpacaReadError("Broker-Orderidentität oder Status stimmt nicht überein.")
    return result


def get_order_by_client_id(client_order_id):
    try:
        return broker_get("/v2/orders:by_client_order_id", {"client_order_id": client_order_id})
    except AlpacaReadError as exc:
        if exc.status_code == 404:
            return None
        raise


def get_latest_quote(symbol, *, option=False):
    feed = os.getenv("ALPACA_OPTION_FEED", "indicative") if option else os.getenv("ALPACA_STOCK_FEED", "sip")
    allowed = ("opra", "indicative") if option else ("iex", "sip", "delayed_sip")
    if feed not in allowed:
        raise AlpacaReadError("Unbekannter Marktdatenfeed.")
    if option:
        result = analytics_alpaca_get("/v1beta1/options/quotes/latest", {"symbols": symbol, "feed": feed})
        quote_data = result.get("quotes", {}).get(symbol)
    else:
        result = analytics_alpaca_get("/v2/stocks/quotes/latest", {"symbols": symbol, "feed": feed})
        quote_data = result.get("quotes", {}).get(symbol)
    if not isinstance(quote_data, dict):
        raise AlpacaReadError("Aktuelle Geld-/Briefkurse fehlen.")
    return {**quote_data, "feed": feed}


def get_position_for_symbol(symbol):
    try:
        return broker_get("/v2/positions/" + quote(symbol.upper(), safe=""))
    except AlpacaReadError as exc:
        if exc.status_code == 404:
            return None
        raise


def get_position_qty(symbol):
    result = get_position_for_symbol(symbol)
    return float(result["qty"]) if result else 0.0


def get_account_activities(activity_types=None):
    params = {"activity_types": ",".join(activity_types)} if activity_types else None
    return _list("/v2/account/activities", params)


def place_order(*args, **kwargs):
    return {"status": "error", "message": BLOCKED_MESSAGE}


def place_statarb_pair_order(*args, **kwargs):
    return place_order()


def close_position_partial(*args, **kwargs):
    return place_order()


def cancel_order(*args, **kwargs):
    return False


def cancel_all_orders(*args, **kwargs):
    return False


def close_position(*args, **kwargs):
    return False


def wait_for_order_fill(*args, **kwargs):
    raise AlpacaReadError(BLOCKED_MESSAGE)


def _paper_write(method, path, payload=None):
    """Transport for durably claimed manual intents in paper_orders only."""
    if method not in ("post", "delete") or not re.fullmatch(r"/v2/orders(?:/[A-Za-z0-9-]+)?", path):
        raise AlpacaReadError("Ungültiger manueller Paper-Schreibpfad.")
    headers = get_alpaca_headers()
    if os.getenv("ALPACA_TRADING_ENABLED", "false").lower() != "true":
        raise AlpacaReadError("Paper-Handel serverseitig gesperrt.")
    return getattr(requests, method)(PAPER_URL + path, headers=headers, json=payload,
                                     timeout=15, allow_redirects=False)
