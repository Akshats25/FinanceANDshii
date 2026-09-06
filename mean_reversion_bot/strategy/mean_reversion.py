"""
Z-score mean-reversion signal on the underlying index, executed via long
options (buy CE when oversold, buy PE when overbought). Defined-risk by
construction: max loss on any single trade is the premium paid, which is
why this is the only strategy shape that fits a ~1 lakh pilot on
NIFTY/BANKNIFTY (see README "Capital reality check" -- futures and short
options both need far more margin than that).
"""
import pandas as pd
from typing import Optional

import config


def compute_zscore(df: pd.DataFrame, window: int = config.ZSCORE_WINDOW) -> pd.Series:
    rolling_mean = df["close"].rolling(window).mean()
    rolling_std = df["close"].rolling(window).std()
    return (df["close"] - rolling_mean) / rolling_std


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    df must have columns: timestamp, open, high, low, close, volume,
    sorted ascending by timestamp. Call this ONE TRADING DAY AT A TIME --
    do not let the rolling window bleed across session boundaries, that
    silently corrupts the first N bars of every day.

    Point-in-time discipline: the signal for bar t is decided using bar
    t's close, but must only ever be ACTED ON starting at bar t+1's open.
    The backtester enforces this lag. Never fill a signal using the same
    bar's close/price it was generated from -- that is a classic
    look-ahead bug and it will make a strategy look better than it is.
    """
    out = df.copy().reset_index(drop=True)
    out["zscore"] = compute_zscore(out)
    out["signal"] = None
    oversold = out["zscore"] <= -config.ZSCORE_ENTRY_THRESHOLD
    overbought = out["zscore"] >= config.ZSCORE_ENTRY_THRESHOLD
    out.loc[oversold, "signal"] = "CE"
    out.loc[overbought, "signal"] = "PE"
    return out


def select_strike(underlying_price: float, direction: str, step: int = None) -> float:
    """
    ATM strike, rounded to the nearest exchange strike interval.
    In live/paper mode, prefer resolving against the ACTUAL available
    strikes from the broker's option chain / scrip master instead of
    this arithmetic rounding -- strike intervals and availability can
    differ from what you'd assume, and this function has no way to know
    if a given strike actually has an active, liquid contract.
    """
    step = step or config.STRIKE_STEP
    return round(underlying_price / step) * step


def should_exit(
    entry_premium: float,
    current_premium: float,
    bars_held: int,
    current_zscore: float,
) -> Optional[str]:
    if entry_premium <= 0:
        return "invalid_entry"

    change_pct = (current_premium - entry_premium) / entry_premium

    if change_pct <= -config.PER_TRADE_STOP_LOSS_PCT:
        return "stop_loss"
    if change_pct >= config.PER_TRADE_TARGET_PCT:
        return "target"
    if abs(current_zscore) <= config.ZSCORE_EXIT_THRESHOLD:
        return "mean_reverted"
    if bars_held >= config.MAX_HOLD_BARS:
        return "max_hold"
    return None
