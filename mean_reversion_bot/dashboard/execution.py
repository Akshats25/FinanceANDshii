"""
execution.py — Order placement, position tracking, and P&L for the dashboard.

Handles:
  • Angel One order placement via the live broker session
  • In-memory today's position log (resets on server restart)
  • Swing low/high detection for auto stop-loss
  • R:R target calculation
"""

import threading
from datetime import datetime
from typing import Optional
import pandas as pd
import numpy as np

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data import database


# ─────────────────────────────────────────────────────────────────────────────
# Swing low / high  (pivot-style, for auto stop-loss)
# ─────────────────────────────────────────────────────────────────────────────
def find_recent_swing_low(candles: list, lookback: int = 20) -> Optional[float]:
    """
    Given a list of OHLCV dicts (most recent last), find the lowest 'low'
    in the last `lookback` bars — used as the stop-loss for LONG trades.
    """
    if not candles:
        return None
    recent = candles[-lookback:]
    try:
        return min(float(c["low"]) for c in recent if c.get("low"))
    except Exception:
        return None


def find_recent_swing_high(candles: list, lookback: int = 20) -> Optional[float]:
    """Highest 'high' in last `lookback` bars — stop for SHORT trades."""
    if not candles:
        return None
    recent = candles[-lookback:]
    try:
        return max(float(c["high"]) for c in recent if c.get("high"))
    except Exception:
        return None


def calc_target(entry: float, stop: float, direction: str, rr: float) -> float:
    """
    Target = entry ± rr × |entry - stop|
    direction: 'LONG' or 'SHORT'
    """
    risk_pts = abs(entry - stop)
    if direction == "LONG":
        return round(entry + rr * risk_pts, 2)
    else:
        return round(entry - rr * risk_pts, 2)


def calc_qty_from_risk(capital: float, risk_pct: float,
                        entry: float, stop: float) -> int:
    """
    Quantity = (capital × risk_pct) / |entry - stop|
    Minimum 1.
    """
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return 1
    max_risk_rs = capital * risk_pct
    qty = int(max_risk_rs / risk_per_unit)
    return max(qty, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Order placement
# ─────────────────────────────────────────────────────────────────────────────
def place_order(
    session,           # Angel One SmartConnect session
    tradingsymbol: str,
    symboltoken: str,
    exchange: str,
    transaction_type: str,   # "BUY" | "SELL"
    quantity: int,
    order_type: str = "MARKET",
    product_type: str = "INTRADAY",
    price: float = 0.0,
) -> dict:
    """
    Place an order via Angel One. Returns a result dict with
    order_id, status, and the raw API response.
    """
    try:
        params = {
            "variety":         "NORMAL",
            "tradingsymbol":   tradingsymbol,
            "symboltoken":     symboltoken,
            "transactiontype": transaction_type,
            "exchange":        exchange,
            "ordertype":       order_type,
            "producttype":     product_type,
            "duration":        "DAY",
            "price":           str(price) if order_type == "LIMIT" else "0",
            "squareoff":       "0",
            "stoploss":        "0",
            "quantity":        str(quantity),
        }
        resp = session.placeOrderFullResponse(params)
        order_id = resp.get("data", {}).get("orderid", "")
        success   = resp.get("status", False)
        return {
            "order_id": order_id,
            "status":   "PLACED" if success else "FAILED",
            "message":  resp.get("message", ""),
            "raw":      resp,
        }
    except Exception as e:
        return {"order_id": "", "status": "ERROR", "message": str(e), "raw": {}}


def get_order_status(session, order_id: str) -> dict:
    try:
        r = session.individual_order_details(order_id)
        return r.get("data", {}) or {}
    except Exception as e:
        return {"error": str(e)}


def get_live_positions(session) -> list:
    """Fetch open positions from Angel One."""
    try:
        r = session.position()
        data = r.get("data") or []
        return data
    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────────────────────────────────────
# Trade log (database-backed)
# ─────────────────────────────────────────────────────────────────────────────
def log_trade(
    instrument: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    qty: int,
    rr: float,
    order_id: str,
    status: str,
    exchange: str,
    tradingsymbol: str,
    mode: str = "paper",
    strategy: str = "pattern_reversal",
) -> int:
    """Record a trade attempt to the persistent database."""
    return database.log_trade(
        strategy=strategy,
        instrument=instrument,
        direction=direction,
        mode=mode,
        entry=entry,
        qty=qty,
        stop=stop,
        target=target,
        order_id=order_id
    )


def close_trade(trade_id: int, exit_price: float):
    """Mark a trade as closed and calculate PnL in database."""
    database.close_trade(trade_id, exit_price)


def get_all_trades() -> dict:
    """Get all trades from database."""
    trades = database.get_all_trades()
    open_list = trades["open"]
    closed_list = trades["closed"]
    
    # Calculate total PnL
    total_pnl = sum(t.get("pnl") or 0 for t in closed_list)
    wins = sum(1 for t in closed_list if (t.get("pnl") or 0) > 0)
    
    # Adapt to legacy frontend format for time/id
    for t in open_list + closed_list:
        t["time"] = t["open_time"]
        
    return {
        "open": open_list,
        "closed": closed_list,
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(closed_list),
        "wins": wins,
    }


def reset_ledger():
    """No-op. SQLite handles persistence."""
    pass
