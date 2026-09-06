"""
Backtester for the mean-reversion OPTIONS strategy.

Key discipline enforced here (keep this when you extend it):
  - Signals are computed on bar t's close, filled at bar t+1's open.
    Never fill on the same bar you generated the signal from.
  - Every trade is intraday: forced exit at config.SQUARE_OFF_TIME.
  - Costs are charged on both entry and exit: brokerage, STT, and an
    assumed slippage percentage.
  - Uses the Black-Scholes fallback pricer for premiums unless you've
    wired in real historical option-chain data (see
    pricing/black_scholes.py docstring). Treat backtest numbers built on
    the BS fallback as a sanity check on the SIGNAL LOGIC, not a promise
    of real tradeable P&L -- real spreads, skew, and liquidity differ.
"""
from dataclasses import dataclass
import pandas as pd

import config
from strategy.mean_reversion import generate_signals, select_strike, should_exit
from pricing.black_scholes import bs_price
from backtest.metrics import compute_metrics


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str
    strike: float
    entry_premium: float
    exit_premium: float
    exit_reason: str
    pnl: float


def _apply_costs(premium: float, lots: int, lot_size: int) -> float:
    """Call once per fill (entry AND exit) -- this is not a round-trip total."""
    turnover = premium * lots * lot_size
    slippage = turnover * config.ASSUMED_SLIPPAGE_PCT
    stt = turnover * config.STT_OPTIONS_PCT
    other = turnover * config.OTHER_CHARGES_PCT
    return config.BROKERAGE_PER_ORDER + slippage + stt + other


def run_backtest(underlying_df: pd.DataFrame, lot_size: int, time_to_expiry_days: float = 3.0, instrument_type: str = "OPTIONS") -> dict:
    """
    underlying_df: columns [timestamp, open, high, low, close, volume],
    one trading day's bars. Group your full history by date upstream and
    call this once per day, then combine results -- see run_backtest.py.
    """
    signals = generate_signals(underlying_df)
    trades: list[Trade] = []
    open_trade = None

    for i in range(len(signals) - 1):
        row = signals.iloc[i]
        next_row = signals.iloc[i + 1]  # entry happens at the NEXT bar's open

        if open_trade is None and row["signal"] in ("CE", "PE"):
            if instrument_type == "OPTIONS":
                strike = select_strike(row["close"], row["signal"])
                tte_years = time_to_expiry_days / 365.0
                entry_premium = bs_price(
                    next_row["open"], strike, tte_years, config.ASSUMED_IV, config.RISK_FREE_RATE, row["signal"]
                )
            else:
                strike = 0
                entry_premium = next_row["open"]

            open_trade = {
                "entry_time": next_row["timestamp"],
                "direction": row["signal"],
                "strike": strike,
                "entry_premium": entry_premium,
                "bars_held": 0,
            }
            continue

        if open_trade is not None:
            open_trade["bars_held"] += 1
            
            if instrument_type == "OPTIONS":
                bars_to_expiry_now = time_to_expiry_days - (open_trade["bars_held"] / 75.0)  # ~75 5-min bars/session, rough
                tte_years_now = max(bars_to_expiry_now, 0.001) / 365.0
                current_premium = bs_price(
                    row["close"], open_trade["strike"], tte_years_now, config.ASSUMED_IV,
                    config.RISK_FREE_RATE, open_trade["direction"]
                )
            else:
                current_premium = row["close"]
                
            exit_reason = should_exit(
                open_trade["entry_premium"], current_premium, open_trade["bars_held"], row["zscore"]
            )
            forced_time_exit = row["timestamp"].strftime("%H:%M") >= config.SQUARE_OFF_TIME

            if exit_reason or forced_time_exit:
                if instrument_type == "OPTIONS":
                    lots = config.MAX_LOTS_PER_TRADE
                    entry_cost = _apply_costs(open_trade["entry_premium"], lots, lot_size)
                    exit_cost = _apply_costs(current_premium, lots, lot_size)
                    gross_pnl = (current_premium - open_trade["entry_premium"]) * lots * lot_size
                else:
                    lots = 1
                    lot_size = 1
                    entry_cost = 0
                    exit_cost = 0
                    if open_trade["direction"] == "CE":
                        gross_pnl = current_premium - open_trade["entry_premium"]
                    else:
                        gross_pnl = open_trade["entry_premium"] - current_premium
                        
                net_pnl = gross_pnl - entry_cost - exit_cost

                trades.append(Trade(
                    entry_time=open_trade["entry_time"],
                    exit_time=row["timestamp"],
                    direction=open_trade["direction"],
                    strike=open_trade["strike"],
                    entry_premium=open_trade["entry_premium"],
                    exit_premium=current_premium,
                    exit_reason=exit_reason or "square_off_time",
                    pnl=net_pnl,
                ))
                open_trade = None

    pnls = [t.pnl for t in trades]
    metrics = compute_metrics(pnls, config.CAPITAL)
    return {"trades": trades, "metrics": metrics}


def run_train_test_split(daily_dfs: dict, lot_size: int, instrument_type: str = "OPTIONS") -> dict:
    """
    daily_dfs: {date_str: DataFrame} of underlying bars, one entry per
    trading day. Splits by date around config.TRAIN_TEST_SPLIT_DATE with
    an embargo gap, so indicator lookback windows can't leak across the
    boundary.
    """
    split_date = pd.Timestamp(config.TRAIN_TEST_SPLIT_DATE)
    embargo = pd.Timedelta(days=config.EMBARGO_DAYS)

    train_days = {d: df for d, df in daily_dfs.items() if pd.Timestamp(d) < split_date}
    test_days = {d: df for d, df in daily_dfs.items() if pd.Timestamp(d) > split_date + embargo}

    def run_all(days: dict) -> dict:
        all_pnls = []
        for _, df in days.items():
            result = run_backtest(df, lot_size, instrument_type=instrument_type)
            all_pnls.extend([t.pnl for t in result["trades"]])
        return compute_metrics(all_pnls, config.CAPITAL)

    return {"train_metrics": run_all(train_days), "test_metrics": run_all(test_days)}
