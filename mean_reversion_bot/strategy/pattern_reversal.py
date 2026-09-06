"""
Pattern-reversal strategy: EMA trend filter + RSI extreme + pivot-based
support/resistance zone + candlestick reversal pattern. Ported from a
Pine Script v6 strategy ("Combined Buy & Sell Strategy (1-Min)"). Unlike
the mean-reversion module, this one trades the underlying directly --
LONG when a bullish reversal fires near support, SHORT when a bearish
reversal fires near resistance -- with a fixed 0.5% target/stop either
side, matching the source script.

TRANSLATION NOTES (read before trusting this):

1. Pivot confirmation lag. Pine's ta.pivotlow(low, left, right) only
   returns a non-na value `right` bars AFTER the actual local low/high --
   it can't know a bar is a pivot before the bars to its right exist.
   Using a "centered" pivot immediately, without that lag, would leak
   future information into the signal -- exactly the look-ahead-bias
   failure mode flagged for this whole project. This module reproduces
   the lag faithfully: a pivot centered at bar i only becomes visible at
   bar i + pivot_len.

2. Zone persistence. The source Pine code assigns
   `supportLevel = ta.pivotlow(...)` fresh every bar. Pine's pivot
   functions return `na` on every bar except the exact confirmation bar --
   they do not automatically persist a value forward. Taken literally,
   `inSupportZone` / `inResistanceZone` are therefore only ever true on
   the single bar a pivot confirms, not for an ongoing zone. That may or
   may not be what was intended when the script was written. This module
   defaults to the literal behavior (config.PERSIST_PIVOT_LEVELS = False).
   Set it True to instead treat the level as an active zone until the
   next pivot appears. Run both and compare trade counts -- they will
   differ a lot.

3. Execution lag. Same discipline as the mean-reversion module: a signal
   computed from bar t's close is only filled at bar t+1's open, never
   at bar t's own close/price.
"""
import pandas as pd
from typing import Optional

import config


def compute_ema(close: pd.Series, length: int) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()


def compute_rsi(close: pd.Series, length: int) -> pd.Series:
    """Wilder-style RSI, matching Pine's ta.rsi smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)  # neutral where undefined (e.g. no losses seen yet)


def compute_pivots(df: pd.DataFrame, pivot_len: int) -> pd.DataFrame:
    """
    pivot_low / pivot_high, non-NaN only on the bar the pivot becomes
    KNOWN -- i.e. already shifted by pivot_len bars. See translation
    note 1 above.
    """
    window = 2 * pivot_len + 1
    centered_min = df["low"].rolling(window, center=True).min()
    centered_max = df["high"].rolling(window, center=True).max()

    is_pivot_low = df["low"] == centered_min
    is_pivot_high = df["high"] == centered_max

    pivot_low_at_center = df["low"].where(is_pivot_low)
    pivot_high_at_center = df["high"].where(is_pivot_high)

    pivot_low = pivot_low_at_center.shift(pivot_len)
    pivot_high = pivot_high_at_center.shift(pivot_len)

    if config.PERSIST_PIVOT_LEVELS:
        pivot_low = pivot_low.ffill()
        pivot_high = pivot_high.ffill()

    return pd.DataFrame({"pivot_low": pivot_low, "pivot_high": pivot_high})


def compute_candle_patterns(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    body = (df["open"] - df["close"]).abs()
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]

    out["is_hammer"] = (lower_wick > body * 2) & (upper_wick < body)
    out["is_shooting_star"] = (upper_wick > body * 2) & (lower_wick < body)

    prev_open, prev_close = df["open"].shift(1), df["close"].shift(1)
    out["bullish_engulfing"] = (
        (prev_open > prev_close) & (df["close"] > df["open"])
        & (df["open"] < prev_close) & (df["close"] > prev_open)
    )
    out["bearish_engulfing"] = (
        (prev_open < prev_close) & (df["close"] < df["open"])
        & (df["open"] > prev_close) & (df["close"] < prev_open)
    )
    return out


def generate_signals(
    df: pd.DataFrame,
    ema_length: int = None,
    rsi_length: int = None,
    pivot_len: int = None,
    rsi_oversold: int = None,
    rsi_overbought: int = None,
    support_tol_pct: float = None,
    resistance_tol_pct: float = None,
) -> pd.DataFrame:
    """
    Call this ONE TRADING DAY AT A TIME -- same reasoning as the
    mean-reversion module: EMA/RSI/pivot state should not bleed across
    session boundaries.
    """
    ema_length = ema_length or config.PATTERN_EMA_LENGTH
    rsi_length = rsi_length or config.PATTERN_RSI_LENGTH
    pivot_len = pivot_len or config.PATTERN_PIVOT_LEN
    rsi_oversold = rsi_oversold or config.PATTERN_RSI_OVERSOLD
    rsi_overbought = rsi_overbought or config.PATTERN_RSI_OVERBOUGHT
    support_tol_pct = support_tol_pct if support_tol_pct is not None else config.PATTERN_SUPPORT_TOLERANCE_PCT
    resistance_tol_pct = resistance_tol_pct if resistance_tol_pct is not None else config.PATTERN_RESISTANCE_TOLERANCE_PCT

    out = df.copy().reset_index(drop=True)
    out["ema"] = compute_ema(out["close"], ema_length)
    out["rsi"] = compute_rsi(out["close"], rsi_length)

    pivots = compute_pivots(out, pivot_len)
    out["support_level"] = pivots["pivot_low"]
    out["resistance_level"] = pivots["pivot_high"]

    patterns = compute_candle_patterns(out)
    out = pd.concat([out, patterns], axis=1)

    in_support_zone = out["support_level"].notna() & (
        (out["close"] - out["support_level"]).abs() / out["support_level"] * 100 <= support_tol_pct
    )
    in_resistance_zone = out["resistance_level"].notna() & (
        (out["close"] - out["resistance_level"]).abs() / out["resistance_level"] * 100 <= resistance_tol_pct
    )

    buy_signal = (
        in_support_zone
        & (out["rsi"] < rsi_oversold)
        & (out["is_hammer"] | out["bullish_engulfing"])
        & (out["close"] > out["ema"])
    )
    sell_signal = (
        in_resistance_zone
        & (out["rsi"] > rsi_overbought)
        & (out["is_shooting_star"] | out["bearish_engulfing"])
        & (out["close"] < out["ema"])
    )

    out["signal"] = None
    out.loc[buy_signal, "signal"] = "LONG"
    out.loc[sell_signal, "signal"] = "SHORT"
    return out


def should_exit(direction: str, entry_price: float, current_price: float) -> Optional[str]:
    """Fixed 0.5% target/stop either side, same as the source Pine script."""
    if direction == "LONG":
        if current_price >= entry_price * (1 + config.PATTERN_TARGET_PCT):
            return "target"
        if current_price <= entry_price * (1 - config.PATTERN_STOP_PCT):
            return "stop_loss"
    else:  # SHORT
        if current_price <= entry_price * (1 - config.PATTERN_TARGET_PCT):
            return "target"
        if current_price >= entry_price * (1 + config.PATTERN_STOP_PCT):
            return "stop_loss"
    return None
