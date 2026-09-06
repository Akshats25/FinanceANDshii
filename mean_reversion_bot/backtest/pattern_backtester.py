"""
Backtester for the pattern-reversal strategy (direct long/short on the
underlying -- futures or equity intraday, not options premium). Simpler
P&L than the options backtester: entry/exit price difference times
quantity, minus costs. Same discipline as the options backtester:
  - signal computed on bar t's close, filled at bar t+1's open
  - one position at a time, forced square-off at config.SQUARE_OFF_TIME
"""
from dataclasses import dataclass
import pandas as pd

import config
from strategy.pattern_reversal import generate_signals, should_exit
from backtest.metrics import compute_metrics


@dataclass
class PatternTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl: float


def _apply_costs(price: float, quantity: int) -> float:
    turnover = price * quantity
    slippage = turnover * config.PATTERN_ASSUMED_SLIPPAGE_PCT
    stt = turnover * config.PATTERN_STT_PCT
    other = turnover * config.PATTERN_OTHER_CHARGES_PCT
    return config.PATTERN_BROKERAGE_PER_ORDER + slippage + stt + other


def run_backtest(underlying_df: pd.DataFrame) -> dict:
    """underlying_df: one trading day's bars, columns
    [timestamp, open, high, low, close, volume]."""
    signals = generate_signals(underlying_df)
    trades: list[PatternTrade] = []
    open_trade = None
    quantity = config.PATTERN_QUANTITY

    for i in range(len(signals) - 1):
        row = signals.iloc[i]
        next_row = signals.iloc[i + 1]

        if open_trade is None and row["signal"] in ("LONG", "SHORT"):
            open_trade = {
                "entry_time": next_row["timestamp"],
                "direction": row["signal"],
                "entry_price": next_row["open"],
            }
            continue

        if open_trade is not None:
            reason = should_exit(open_trade["direction"], open_trade["entry_price"], row["close"])
            forced_time_exit = row["timestamp"].strftime("%H:%M") >= config.SQUARE_OFF_TIME

            if reason or forced_time_exit:
                exit_price = row["close"]
                entry_cost = _apply_costs(open_trade["entry_price"], quantity)
                exit_cost = _apply_costs(exit_price, quantity)

                if open_trade["direction"] == "LONG":
                    gross_pnl = (exit_price - open_trade["entry_price"]) * quantity
                else:
                    gross_pnl = (open_trade["entry_price"] - exit_price) * quantity

                net_pnl = gross_pnl - entry_cost - exit_cost

                trades.append(PatternTrade(
                    entry_time=open_trade["entry_time"],
                    exit_time=row["timestamp"],
                    direction=open_trade["direction"],
                    entry_price=open_trade["entry_price"],
                    exit_price=exit_price,
                    exit_reason=reason or "square_off_time",
                    pnl=net_pnl,
                ))
                open_trade = None

    pnls = [t.pnl for t in trades]
    metrics = compute_metrics(pnls, config.PATTERN_CAPITAL)
    return {"trades": trades, "metrics": metrics}


def run_train_test_split(daily_dfs: dict) -> dict:
    split_date = pd.Timestamp(config.TRAIN_TEST_SPLIT_DATE)
    embargo = pd.Timedelta(days=config.EMBARGO_DAYS)

    train_days = {d: df for d, df in daily_dfs.items() if pd.Timestamp(d) < split_date}
    test_days = {d: df for d, df in daily_dfs.items() if pd.Timestamp(d) > split_date + embargo}

    def run_all(days: dict) -> dict:
        all_pnls = []
        for _, df in days.items():
            result = run_backtest(df)
            all_pnls.extend([t.pnl for t in result["trades"]])
        return compute_metrics(all_pnls, config.PATTERN_CAPITAL)

    return {"train_metrics": run_all(train_days), "test_metrics": run_all(test_days)}
