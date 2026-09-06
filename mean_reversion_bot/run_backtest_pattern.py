"""
Entry point: run the pattern-reversal backtest on historical underlying data.

Usage:
    python run_backtest_pattern.py path/to/underlying_1min.csv

CSV must have columns: timestamp, open, high, low, close, volume
The source Pine script was written for a 1-minute chart -- keep that
timeframe unless you deliberately re-tune ema/rsi/pivot lengths for a
different one.
"""
import sys
import pandas as pd

from data.data_quality import check_ohlc
from backtest.pattern_backtester import run_train_test_split


def main(csv_path: str):
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])

    problems = check_ohlc(df)
    if problems:
        print("Data quality problems found -- fix before trusting results:")
        for p in problems:
            print(f"  - {p}")
        return

    df["date"] = df["timestamp"].dt.date
    daily_dfs = {str(d): g.drop(columns="date").reset_index(drop=True) for d, g in df.groupby("date")}

    if len(daily_dfs) < 30:
        print(f"Warning: only {len(daily_dfs)} trading days of data -- "
              f"thin sample, treat metrics as low-confidence.\n")

    results = run_train_test_split(daily_dfs)

    print("=== TRAIN (in-sample) ===")
    for k, v in results["train_metrics"].items():
        print(f"  {k}: {v}")

    print("\n=== TEST (out-of-sample) ===")
    for k, v in results["test_metrics"].items():
        print(f"  {k}: {v}")

    print("\nNote: config.PERSIST_PIVOT_LEVELS changes trade frequency a "
          "lot for this strategy -- run it both True and False and compare "
          "before picking one (see strategy/pattern_reversal.py docstring).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_backtest_pattern.py path/to/underlying_1min.csv")
        sys.exit(1)
    main(sys.argv[1])
