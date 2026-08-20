"""
mobile_api.py - REST API for mobile client access to the Falcone Capital terminal.

Thin HTTP layer over the existing modules (alpaca_trader.py, watchlist_manager.py,
screener.py) - no business logic lives here, it only wraps and serializes.

Run with: uvicorn mobile_api:app --host 0.0.0.0 --port 8000
"""
import os
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

import alpaca_trader as at
import watchlist_manager as wm
from screener import calculate_scores, load_cache

load_dotenv()

app = FastAPI(title="Falcone Capital Mobile API", version="1.0.0")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: Optional[str] = Depends(_api_key_header)) -> None:
    expected = os.getenv("MOBILE_API_KEY")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="MOBILE_API_KEY ist nicht in .env konfiguriert - Server nicht einsatzbereit.",
        )
    if api_key != expected:
        raise HTTPException(status_code=401, detail="Ungueltiger oder fehlender X-API-Key Header.")


class OrderRequest(BaseModel):
    symbol: str
    qty: float
    side: str
    order_type: str = "market"
    limit_price: Optional[float] = None
    time_in_force: str = "gtc"


class WatchlistRequest(BaseModel):
    ticker: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "alpaca_configured": at.is_alpaca_configured()}


@app.get("/account", dependencies=[Depends(require_api_key)])
def account() -> dict:
    info = at.get_account_info()
    if not info:
        raise HTTPException(status_code=502, detail="Alpaca-Konto konnte nicht geladen werden.")
    return info


@app.get("/positions", dependencies=[Depends(require_api_key)])
def positions() -> list:
    return at.get_positions()


@app.get("/orders", dependencies=[Depends(require_api_key)])
def orders() -> list:
    return at.get_open_orders()


@app.post("/orders", dependencies=[Depends(require_api_key)])
def create_order(req: OrderRequest) -> dict:
    result = at.place_order(
        symbol=req.symbol,
        qty=req.qty,
        side=req.side,
        order_type=req.order_type,
        limit_price=req.limit_price,
        time_in_force=req.time_in_force,
    )
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message", "Order fehlgeschlagen."))
    return result["order"]


@app.delete("/orders/{order_id}", dependencies=[Depends(require_api_key)])
def cancel_order(order_id: str) -> dict:
    if not at.cancel_order(order_id):
        raise HTTPException(status_code=400, detail="Order konnte nicht storniert werden.")
    return {"status": "cancelled", "order_id": order_id}


@app.get("/watchlist", dependencies=[Depends(require_api_key)])
def watchlist() -> list:
    return wm.load_watchlist()


@app.post("/watchlist", dependencies=[Depends(require_api_key)])
def watchlist_add(req: WatchlistRequest) -> dict:
    added = wm.add_to_watchlist(req.ticker)
    return {"ticker": req.ticker.strip().upper(), "added": added}


@app.delete("/watchlist/{ticker}", dependencies=[Depends(require_api_key)])
def watchlist_remove(ticker: str) -> dict:
    removed = wm.remove_from_watchlist(ticker)
    return {"ticker": ticker.strip().upper(), "removed": removed}


@app.get("/screener", dependencies=[Depends(require_api_key)])
def screener(
    side: str = Query("long", pattern="^(long|short)$"),
    limit: int = Query(20, ge=1, le=200),
) -> list:
    cache = load_cache()
    if not cache:
        return []
    records = [entry["data"] for entry in cache.values() if "data" in entry]
    if not records:
        return []
    df = pd.DataFrame(records)
    df = calculate_scores(df)
    score_col = "LongScore" if side == "long" else "ShortScore"
    if score_col not in df.columns:
        raise HTTPException(status_code=500, detail=f"Score-Spalte {score_col} fehlt im Cache.")
    df = df.sort_values(score_col, ascending=False).head(limit)
    return df.to_dict(orient="records")
