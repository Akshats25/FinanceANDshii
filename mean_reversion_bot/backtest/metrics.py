"""
Basic performance / statistical validation metrics. Deliberately small --
enough to sanity-check a strategy, not a full research-metrics platform.
Extend this (bootstrap confidence intervals, per-regime breakdowns, etc.)
only once the basics are stable and trusted.
"""
import numpy as np


def compute_metrics(trade_pnls: list, capital: float) -> dict:
    if not trade_pnls:
        return {"trades": 0}

    pnls = np.array(trade_pnls, dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    equity_curve = capital + np.cumsum(pnls)
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown = float(drawdown.min())

    per_trade_returns = pnls / capital
    sharpe = 0.0
    if per_trade_returns.std() > 0:
        # Rough annualisation assuming ~1 trade opportunity per session;
        # treat this as directional, not precise, until trade frequency
        # is well established from real data.
        sharpe = float(np.sqrt(252) * per_trade_returns.mean() / per_trade_returns.std())

    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")

    return {
        "trades": int(len(pnls)),
        "win_rate": float(len(wins) / len(pnls)),
        "avg_pnl_per_trade": round(float(pnls.mean()), 2),
        "total_pnl": round(float(pnls.sum()), 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "sharpe_approx": round(sharpe, 2),
        "profit_factor": round(profit_factor, 2),
    }
