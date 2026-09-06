"""
Entry point: paper trading loop for the mean-reversion OPTIONS strategy.

Polls the live underlying price at each bar interval, runs the same
signal logic as the backtest, and SIMULATES fills (no real orders
placed). Logs everything to the trade journal so you can compare it
against backtest predictions day by day -- this is the "Week 3-4(-5):
Paper trading" phase from the project plan.

This is a working skeleton, not a finished production loop. Before
trusting it unattended, you'll want (see AGENT_PROMPTS.md for ready-to-
use task briefs on each of these):
  - a real option premium quote instead of the TODO placeholder below
  - WebSocket streaming instead of polling
  - reconnect/retry handling around the broker session
  - a market-hours guard so it doesn't sit querying a closed market

Watch this run side-by-side with the actual market for the first several
sessions before trusting the numbers it produces.
"""
import time
from datetime import datetime
import pandas as pd

import config
from broker.angelone_adapter import AngelOneAdapter
from strategy.mean_reversion import compute_zscore, select_strike, should_exit
from risk.risk_manager import RiskState
from journal.trade_journal import log_event, JournalEntry


def main():
    assert config.MODE == "paper", "config.MODE must be 'paper' to run this script"

    broker = AngelOneAdapter(
        config.ANGEL_API_KEY, config.ANGEL_CLIENT_CODE,
        config.ANGEL_PASSWORD_OR_PIN, config.ANGEL_TOTP_SECRET,
    )
    broker.connect()

    risk = RiskState()
    bars: list = []
    open_trade = None

    print(f"Paper trading {config.UNDERLYING} -- Ctrl+C to stop.")

    try:
        while True:
            now = datetime.now().strftime("%H:%M")
            if now >= config.SQUARE_OFF_TIME and open_trade is None:
                print("Past square-off time, no new entries today.")
                time.sleep(60)
                continue

            # TODO: replace "SET_ME_TOKEN" with the correct symboltoken for
            # your underlying -- resolve it once via broker.load_scrip_master()
            # and hardcode it here (it doesn't change often).
            price = broker.get_ltp("NSE", f"{config.UNDERLYING}-EQ", "SET_ME_TOKEN")
            bars.append({"timestamp": pd.Timestamp.now(), "close": price})
            df = pd.DataFrame(bars)

            if len(df) >= config.ZSCORE_WINDOW:
                df["zscore"] = compute_zscore(df)
                z = df["zscore"].iloc[-1]

                if open_trade is None and risk.can_open_new_position():
                    direction = None
                    if z <= -config.ZSCORE_ENTRY_THRESHOLD:
                        direction = "CE"
                    elif z >= config.ZSCORE_ENTRY_THRESHOLD:
                        direction = "PE"

                    if direction:
                        strike = select_strike(price, direction)
                        open_trade = {"direction": direction, "strike": strike, "bars_held": 0}
                        log_event(JournalEntry(
                            timestamp=str(pd.Timestamp.now()), event_type="signal",
                            direction=direction, strike=strike, premium=0.0,
                            quantity=risk.position_size_lots(), reason=f"zscore={z:.2f}",
                            mode="paper",
                        ))
                        print(f"[SIGNAL] {direction} @ strike {strike}, z={z:.2f}")

                elif open_trade is not None:
                    open_trade["bars_held"] += 1
                    # TODO: fetch a real option premium here (via
                    # broker.resolve_option_token + get_ltp on that
                    # contract) instead of this 1.0/1.0 placeholder.
                    reason = should_exit(1.0, 1.0, open_trade["bars_held"], z)
                    if reason:
                        log_event(JournalEntry(
                            timestamp=str(pd.Timestamp.now()), event_type="exit",
                            direction=open_trade["direction"], strike=open_trade["strike"],
                            premium=0.0, quantity=risk.position_size_lots(),
                            reason=reason, mode="paper",
                        ))
                        print(f"[EXIT] {reason}")
                        open_trade = None

            time.sleep(5 * 60)  # align to config.BAR_INTERVAL

    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
