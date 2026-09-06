"""
Entry point: run the mean-reversion OPTIONS backtest on historical
underlying data.

Usage:
    python run_backtest.py path/to/underlying_5min.csv

CSV must have columns: timestamp, open, high, low, close, volume
Get this from Angel One's getCandleData (see broker/angelone_adapter.py)
or your own historical data export.
"""
import sys
import pandas as pd

import config
from data.data_quality import check_ohlc
from backtest.backtester import run_train_test_split

# VERIFY against the current NSE lot size before trusting P&L numbers --
# exchanges revise lot sizes periodically (most recently Jan 2026: NIFTY
# 75->65, BANKNIFTY 35->30).
LOT_SIZE = {"NIFTY": 65, "BANKNIFTY": 30}[config.UNDERLYING]


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
        print(f"Warning: only {len(daily_dfs)} trading days of data. "
              f"That's a thin sample for a mean-reversion strategy -- "
              f"treat any metrics as low-confidence until you have more history.\n")

    results = run_train_test_split(daily_dfs, LOT_SIZE)

    print("=== TRAIN (in-sample) ===")
    for k, v in results["train_metrics"].items():
        print(f"  {k}: {v}")

    print("\n=== TEST (out-of-sample) ===")
    for k, v in results["test_metrics"].items():
        print(f"  {k}: {v}")

    print("\nReminder: these numbers come from the Black-Scholes fallback "
          "pricer with a flat IV assumption, not real historical option "
          "premiums. Treat this as a check on your SIGNAL LOGIC, not a "
          "return forecast -- see README for what to upgrade before going live.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python run_backtest.py path/to/underlying_5min.csv")
        sys.exit(1)
    main(sys.argv[1])
