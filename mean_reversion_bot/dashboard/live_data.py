"""
live_data.py — Real-data fetchers for the dashboard.

Sources used (all free / no paid key required):
  • Angel One SmartAPI  — NIFTY/BANKNIFTY LTP + option chain scrip master
  • Binance REST API    — BTC/USDT OHLCV candles (no auth)
  • CoinGecko REST API  — BTC price + 24 h stats (no auth)

All network calls are wrapped in try/except so a single failing
source never crashes the dashboard — it returns a structured error
payload instead and the front-end shows a graceful "N/A".
"""

import math
import threading
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# In-process cache
# ─────────────────────────────────────────────────────────────────────────────
_cache: dict = {}
_cache_lock = threading.Lock()

CACHE_TTL = {
    "btc_price":   10,   # seconds
    "nifty_ltp":   10,
    "scrip_master": 3600,
}


def _set_cache(key: str, value):
    with _cache_lock:
        _cache[key] = {"value": value, "ts": time.time()}


def _get_cache(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL.get(key, 60):
            return entry["value"]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# BTC — CoinGecko (no key needed)
# ─────────────────────────────────────────────────────────────────────────────
COINGECKO_SIMPLE = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_MARKET = "https://api.coingecko.com/api/v3/coins/bitcoin"


def get_btc_price() -> dict:
    """Return BTC price + 24h change from CoinGecko. Cached 10 s."""
    cached = _get_cache("btc_price")
    if cached:
        return cached

    try:
        r = requests.get(
            COINGECKO_SIMPLE,
            params={"ids": "bitcoin", "vs_currencies": "usd,inr",
                    "include_24hr_change": "true", "include_24hr_vol": "true"},
            timeout=8,
        )
        r.raise_for_status()
        d = r.json()["bitcoin"]
        result = {
            "price_usd": d.get("usd", 0),
            "price_inr": d.get("inr", 0),
            "change_24h_pct": round(d.get("usd_24h_change", 0), 3),
            "volume_24h_usd": d.get("usd_24h_vol", 0),
            "source": "coingecko",
            "error": None,
        }
    except Exception as e:
        result = {"price_usd": None, "price_inr": None,
                  "change_24h_pct": None, "volume_24h_usd": None,
                  "source": "coingecko", "error": str(e)}

    _set_cache("btc_price", result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# BTC OHLCV candles — Binance (no auth)
# ─────────────────────────────────────────────────────────────────────────────
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


def get_btc_candles(interval: str = "5m", limit: int = 100) -> list:
    """
    Returns list of OHLCV dicts for BTC/USDT from Binance.
    interval: '1m','5m','15m','1h','4h','1d'
    """
    cache_key = f"btc_candles_{interval}_{limit}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    try:
        r = requests.get(
            BINANCE_KLINES,
            params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        raw = r.json()
        candles = [
            {
                "timestamp": datetime.utcfromtimestamp(c[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            }
            for c in raw
        ]
        _set_cache(cache_key, candles)
        return candles
    except Exception as e:
        return [{"error": str(e)}]


def get_btc_zscore(interval: str = "5m", window: int = 20) -> list:
    """BTC candles with z-score applied (for signal demo on BTC)."""
    candles = get_btc_candles(interval, limit=max(window + 20, 60))
    if not candles or "error" in candles[0]:
        return candles

    df = pd.DataFrame(candles)
    df["close"] = df["close"].astype(float)
    df["rolling_mean"] = df["close"].rolling(window).mean()
    df["rolling_std"]  = df["close"].rolling(window).std()
    df["zscore"] = (df["close"] - df["rolling_mean"]) / df["rolling_std"]

    return df[["timestamp", "open", "high", "low", "close", "volume", "zscore"]].to_dict("records")


# ─────────────────────────────────────────────────────────────────────────────
# Angel One — NIFTY / BANKNIFTY LTP
# ─────────────────────────────────────────────────────────────────────────────
# Known stable token IDs for NSE indices (rarely change):
NIFTY_TOKEN  = "99926000"
BNIFTY_TOKEN = "99926009"

_angel_session = None   # set by app.py after broker.connect()


def set_angel_session(session):
    """Called from app.py once broker.connect() succeeds."""
    global _angel_session
    _angel_session = session


def _ltp(exchange: str, symbol: str, token: str) -> Optional[float]:
    if _angel_session is None:
        return None
    try:
        r = _angel_session.ltpData(exchange, symbol, token)
        return float(r["data"]["ltp"])
    except Exception:
        return None


def get_nifty_ltp() -> dict:
    cached = _get_cache("nifty_ltp")
    if cached:
        return cached

    ltp = _ltp("NSE", "Nifty 50", NIFTY_TOKEN)
    result = {"ltp": ltp, "error": None if ltp else "broker_not_connected"}
    _set_cache("nifty_ltp", result)
    return result


def get_banknifty_ltp() -> dict:
    cached = _get_cache("banknifty_ltp")
    if cached:
        return cached

    ltp = _ltp("NSE", "Nifty Bank", BNIFTY_TOKEN)
    result = {"ltp": ltp, "error": None if ltp else "broker_not_connected"}
    _set_cache("banknifty_ltp", result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Angel One — Scrip master + option chain
# ─────────────────────────────────────────────────────────────────────────────
SCRIP_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"

_scrip_df: Optional[pd.DataFrame] = None
_scrip_loaded_at: float = 0


def _load_scrip_master() -> Optional[pd.DataFrame]:
    global _scrip_df, _scrip_loaded_at
    now = time.time()
    if _scrip_df is not None and (now - _scrip_loaded_at) < 3600:
        return _scrip_df
    try:
        r = requests.get(SCRIP_URL, timeout=30)
        r.raise_for_status()
        _scrip_df = pd.DataFrame(r.json())
        _scrip_loaded_at = now
        return _scrip_df
    except Exception:
        return _scrip_df  # return stale if available


def get_nearest_expiry(underlying: str = "NIFTY", expiry_type: str = "weekly") -> Optional[str]:
    """
    Returns the nearest weekly (or monthly) expiry string as it appears
    in the Angel One scrip master (e.g. '25SEP2026').

    Logic: look at all available NFO option expiries for the underlying,
    filter to future dates, and pick the nearest one.
    For monthly: restrict to the last Thursday of the month.
    """
    df = _load_scrip_master()
    if df is None:
        return None

    try:
        opts = df[
            (df["name"] == underlying) &
            (df["exch_seg"] == "NFO") &
            (df["instrumenttype"].isin(["OPTIDX", "OPTSTK"]))
        ].copy()

        if opts.empty:
            return None

        # Parse expiry strings — Angel One format is DDMMMYYYY e.g. 25SEP2026
        opts["expiry_dt"] = pd.to_datetime(opts["expiry"], format="%d%b%Y", errors="coerce")
        opts = opts.dropna(subset=["expiry_dt"])

        today = pd.Timestamp.now().normalize()
        future = opts[opts["expiry_dt"] >= today]["expiry_dt"].drop_duplicates().sort_values()

        if future.empty:
            return None

        if expiry_type == "weekly":
            nearest = future.iloc[0]
        else:
            # Monthly: pick the last Thursday of the nearest future month
            monthly = future[future.dt.day >= 20]  # rough filter
            nearest = monthly.iloc[0] if not monthly.empty else future.iloc[0]

        # Convert back to Angel One format
        return nearest.strftime("%d%b%Y").upper()

    except Exception:
        return None


def get_option_chain(underlying: str = "NIFTY", spot: float = 22000.0,
                     expiry: Optional[str] = None, strikes_around: int = 10) -> list:
    """
    Returns a list of option chain rows (strike, CE token, PE token, expiry)
    from the scrip master, centred ±strikes_around around ATM.
    """
    df = _load_scrip_master()
    if df is None:
        return [{"error": "scrip_master_unavailable"}]

    if expiry is None:
        expiry = get_nearest_expiry(underlying)
    if expiry is None:
        return [{"error": "no_expiry_found"}]

    try:
        opts = df[
            (df["name"] == underlying) &
            (df["exch_seg"] == "NFO") &
            (df["expiry"] == expiry)
        ].copy()

        if opts.empty:
            return [{"error": f"no_options_for_expiry_{expiry}"}]

        opts["strike_f"] = opts["strike"].astype(float) / 100  # Angel stores * 100
        step = 50 if underlying == "NIFTY" else 100
        atm = round(spot / step) * step
        lo = atm - strikes_around * step
        hi = atm + strikes_around * step

        opts = opts[(opts["strike_f"] >= lo) & (opts["strike_f"] <= hi)]

        # Pivot: one row per strike with CE and PE columns
        chain = []
        for strike_val, grp in opts.groupby("strike_f"):
            ce_row = grp[grp["symbol"].str.endswith("CE")]
            pe_row = grp[grp["symbol"].str.endswith("PE")]
            chain.append({
                "strike": strike_val,
                "expiry": expiry,
                "ce_symbol": ce_row["symbol"].iloc[0] if not ce_row.empty else None,
                "ce_token":  ce_row["token"].iloc[0]  if not ce_row.empty else None,
                "pe_symbol": pe_row["symbol"].iloc[0] if not pe_row.empty else None,
                "pe_token":  pe_row["token"].iloc[0]  if not pe_row.empty else None,
                "atm": (strike_val == atm),
            })

        return sorted(chain, key=lambda x: x["strike"])

    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────────────────────────────────────
# Angel One — Historical candles for backtest
# ─────────────────────────────────────────────────────────────────────────────
def get_historical_candles(
    session,
    symbol_token: str,
    exchange: str = "NSE",
    interval: str = "FIVE_MINUTE",
    from_date: str = None,
    to_date: str = None,
) -> pd.DataFrame:
    """
    Fetch historical OHLCV from Angel One and return as a DataFrame.
    from_date / to_date format: "YYYY-MM-DD HH:MM"
    """
    if to_date is None:
        to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    if from_date is None:
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")

    try:
        result = session.getCandleData({
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        })
        if not result.get("status", False):
            return pd.DataFrame()

        df = pd.DataFrame(
            result["data"],
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    except Exception:
        return pd.DataFrame()
