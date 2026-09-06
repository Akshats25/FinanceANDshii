"""
Minimal risk manager: fixed position sizing, a daily loss limit, and a
kill switch. This is the one piece of the whole system that should never
get cut for speed -- it is what turns a bug into an inconvenience
instead of a blown account.
"""
from dataclasses import dataclass
import config


@dataclass
class RiskState:
    daily_pnl: float = 0.0
    open_positions: int = 0
    kill_switch_tripped: bool = False
    kill_switch_reason: str = ""

    def record_trade_pnl(self, pnl: float) -> None:
        self.daily_pnl += pnl
        if self.daily_pnl <= -config.CAPITAL * config.DAILY_LOSS_LIMIT_PCT:
            self.trip_kill_switch("daily_loss_limit_breached")

    def trip_kill_switch(self, reason: str) -> None:
        self.kill_switch_tripped = True
        self.kill_switch_reason = reason

    def reset_for_new_day(self) -> None:
        self.daily_pnl = 0.0
        # Kill switch does NOT auto-reset. A human should look at why it
        # tripped before trading resumes -- that's the point of it.

    def can_open_new_position(self) -> bool:
        if self.kill_switch_tripped:
            return False
        if self.open_positions >= config.MAX_CONCURRENT_POSITIONS:
            return False
        return True

    def position_size_lots(self) -> int:
        return config.MAX_LOTS_PER_TRADE
