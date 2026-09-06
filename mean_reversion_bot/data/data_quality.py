"""
Minimal data quality checks. Run this on every batch of historical or
live candles before feeding it to the strategy -- a backtest on bad
data produces a confident, wrong answer, which is worse than an obvious
one.
"""
import pandas as pd


def check_ohlc(df: pd.DataFrame) -> list:
    """Returns a list of human-readable problem descriptions, empty if clean."""
    problems = []

    if df[["open", "high", "low", "close"]].le(0).any().any():
        problems.append("zero_or_negative_price")

    bad_high = df["high"] < df[["open", "close", "low"]].max(axis=1)
    if bad_high.any():
        problems.append(f"high_below_open_close_or_low: {int(bad_high.sum())} rows")

    bad_low = df["low"] > df[["open", "close", "high"]].min(axis=1)
    if bad_low.any():
        problems.append(f"low_above_open_close_or_high: {int(bad_low.sum())} rows")

    if df["timestamp"].duplicated().any():
        problems.append(f"duplicate_timestamps: {int(df['timestamp'].duplicated().sum())}")

    if not df["timestamp"].is_monotonic_increasing:
        problems.append("timestamps_out_of_order")

    # Gap check is session-aware: a jump from one trading day's last bar to
    # the next day's first bar is normal, not a data problem. Only flag
    # gaps that occur WITHIN the same session.
    same_day = df["timestamp"].dt.date == df["timestamp"].dt.date.shift(1)
    intraday_gaps = df["timestamp"].diff()[same_day]
    if len(intraday_gaps) > 0:
        mode = intraday_gaps.mode()
        if not mode.empty:
            expected = mode.iloc[0]
            large_gaps = intraday_gaps[intraday_gaps > expected * 3]
            if len(large_gaps) > 0:
                problems.append(f"unexpected_intraday_gaps: {len(large_gaps)}")

    return problems
