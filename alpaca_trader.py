import os
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Ensure env vars are loaded
load_dotenv()

def get_alpaca_credentials() -> tuple[Optional[str], Optional[str], str]:
    """Retrieves Alpaca API credentials from environment variables or active session."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    
    # Strip any potential leading/trailing whitespace
    if api_key:
        api_key = api_key.strip()
    if secret_key:
        secret_key = secret_key.strip()
    if base_url:
        base_url = base_url.strip()
        
    return api_key, secret_key, base_url

def get_alpaca_headers() -> Dict[str, str]:
    """Generates authentication headers for the Alpaca REST API."""
    api_key, secret_key, _ = get_alpaca_credentials()
    return {
        "APCA-API-KEY-ID": api_key or "",
        "APCA-API-SECRET-KEY": secret_key or "",
        "Content-Type": "application/json"
    }

def is_alpaca_configured() -> bool:
    """Checks whether the API keys are configured."""
    api_key, secret_key, _ = get_alpaca_credentials()
    return bool(api_key and secret_key)

def get_account_info() -> Dict[str, Any]:
    """
    Fetches Alpaca account details (cash, buying power, equity, status, etc.).
    Returns an empty dict if API is not configured or fails.
    """
    if not is_alpaca_configured():
        return {}
    
    _, _, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/account"
    try:
        response = requests.get(url, headers=get_alpaca_headers(), timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"[Alpaca Trader] Account fetch failed: Status {response.status_code}")
    except Exception as e:
        print(f"[Alpaca Trader] Connection error during account fetch: {e}")
    return {}

def verify_alpaca_connection() -> tuple[bool, str]:
    """
    Verifies the connection to Alpaca and returns a status flag and details.
    Returns (True, message) if connection is successful, (False, details) otherwise.
    """
    if not is_alpaca_configured():
        return False, "Alpaca API Keys sind nicht vollständig konfiguriert (Key ID und Secret Key werden benötigt)."
        
    api_key, secret_key, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/account"
    try:
        response = requests.get(url, headers=get_alpaca_headers(), timeout=10)
        if response.status_code == 200:
            acc_data = response.json()
            return True, f"Verbunden! Konto-Status: {acc_data.get('status', 'ACTIVE')}"
        elif response.status_code == 401:
            return False, "Fehler 401: Ungültige API-Schlüssel. Bitte prüfen Sie Key ID und Secret Key."
        elif response.status_code == 403:
            return False, "Fehler 403: Zugriff verweigert. Haben Sie Live-Keys mit der Paper-URL verwendet oder umgekehrt?"
        else:
            try:
                err_msg = response.json().get("message", response.text)
            except Exception:
                err_msg = response.text
            return False, f"Fehler {response.status_code}: {err_msg}"
    except requests.exceptions.Timeout:
        return False, "Verbindungsfehler: Zeitüberschreitung (Timeout) beim Verbinden mit Alpaca."
    except requests.exceptions.ConnectionError:
        return False, "Verbindungsfehler: Verbindung zum Alpaca-Server fehlgeschlagen. Bitte URL und Internet prüfen."
    except Exception as e:
        return False, f"Unbekannter Fehler: {str(e)}"


def get_positions() -> List[Dict[str, Any]]:
    """
    Fetches currently open portfolio positions from Alpaca.
    Returns a list of positions or an empty list.
    """
    if not is_alpaca_configured():
        return []
    
    _, _, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/positions"
    try:
        response = requests.get(url, headers=get_alpaca_headers(), timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[Alpaca Trader] Connection error during positions fetch: {e}")
    return []

def get_open_orders() -> List[Dict[str, Any]]:
    """
    Fetches currently active/pending orders from Alpaca.
    Returns a list of orders.
    """
    if not is_alpaca_configured():
        return []
    
    _, _, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/orders"
    params = {"status": "open"}
    try:
        response = requests.get(url, headers=get_alpaca_headers(), params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[Alpaca Trader] Connection error during orders fetch: {e}")
    return []

def place_order(
    symbol: str, 
    qty: float, 
    side: str, 
    order_type: str = "market", 
    limit_price: Optional[float] = None,
    time_in_force: str = "gtc"
) -> Dict[str, Any]:
    """
    Places an order on Alpaca.
    
    :param symbol: Ticker symbol (e.g. 'AAPL')
    :param qty: Quantity to buy/sell (can be float for fractional shares if supported, or int)
    :param side: 'buy' or 'sell'
    :param order_type: 'market', 'limit', 'stop', 'stop_limit'
    :param limit_price: Required if order_type is 'limit' or 'stop_limit'
    :param time_in_force: 'day', 'gtc', 'opg', 'cls', 'ioc', 'fok'
    """
    if not is_alpaca_configured():
        return {"status": "error", "message": "Alpaca API Keys nicht in .env oder Sidebar konfiguriert."}
    
    _, _, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/orders"
    
    # Ensure quantity is formatted appropriately (no unnecessary .0)
    qty_str = str(int(qty)) if qty.is_integer() else str(qty)
    
    data = {
        "symbol": symbol.upper().replace("-", "."), # Alpaca uses dots for class shares, e.g. BRK.B
        "qty": qty_str,
        "side": side.lower(),
        "type": order_type.lower(),
        "time_in_force": time_in_force.lower()
    }
    
    if order_type.lower() in ["limit", "stop_limit"] and limit_price is not None:
        data["limit_price"] = f"{limit_price:.2f}"
        
    try:
        response = requests.post(url, headers=get_alpaca_headers(), json=data, timeout=10)
        if response.status_code in [200, 201]:
            return {"status": "success", "order": response.json()}
        else:
            try:
                err_msg = response.json().get("message", response.text)
            except Exception:
                err_msg = response.text
            return {"status": "error", "message": f"Alpaca API Error ({response.status_code}): {err_msg}"}
    except Exception as e:
        return {"status": "error", "message": f"Verbindungsfehler: {str(e)}"}

def cancel_order(order_id: str) -> bool:
    """Cancels a specific pending order by its order_id."""
    if not is_alpaca_configured():
        return False
    
    _, _, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/orders/{order_id}"
    try:
        response = requests.delete(url, headers=get_alpaca_headers(), timeout=10)
        return response.status_code == 204
    except Exception as e:
        print(f"[Alpaca Trader] Connection error during order cancellation: {e}")
    return False

def cancel_all_orders() -> bool:
    """Cancels all currently open orders."""
    if not is_alpaca_configured():
        return False
    
    _, _, base_url = get_alpaca_credentials()
    url = f"{base_url}/v2/orders"
    try:
        response = requests.delete(url, headers=get_alpaca_headers(), timeout=10)
        return response.status_code == 207  # Multi-status response for batch delete
    except Exception as e:
        print(f"[Alpaca Trader] Connection error during batch cancellation: {e}")
    return False
