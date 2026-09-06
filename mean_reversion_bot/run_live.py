"""
Entry point: LIVE trading for the mean-reversion OPTIONS strategy. Reads
real market data and places REAL orders with REAL money through Angel One.

Hard gates before this does anything (on purpose -- don't bypass them):
  1. config.MODE must be "live"
  2. config.LIVE_TRADING_CONFIRMED must be True
  3. You type "YES" at the interactive prompt below
  4. You've actually been through the go/no-go checklist in README.md --
     nothing in this script checks that part for you, it's on you.

This is intentionally structured as a near-copy of run_paper.py -- that's
deliberate, so paper and live behave identically except for the
place_order() calls. Any strategy change should be tested in paper mode
first, not edited directly here.
"""
import sys
import time
from datetime import datetime
import pandas as pd

import config
from broker.angelone_adapter import AngelOneAdapter
from strategy.mean_reversion import compute_zscore, select_strike, should_exit
from risk.risk_manager import RiskState
from journal.trade_journal import log_event, JournalEntry


def _hard_safety_gate():
    if config.MODE != "live":
        sys.exit("config.MODE must be 'live' to run this script.")
    if not config.LIVE_TRADING_CONFIRMED:
        sys.exit(
            "config.LIVE_TRADING_CONFIRMED is False. That's intentional -- "
            "flip it to True only after you've been through the go/no-go "
            "checklist in README.md. This script places real orders with "
            "real money."
        )
    confirm = input(
        f"About to trade {config.UNDERLYING} LIVE with real money, "
        f"max {config.MAX_LOTS_PER_TRADE} lot(s), capital base Rs {config.CAPITAL:,}. "
        f"Type YES to continue: "
    )
    if confirm.strip() != "YES":
        sys.exit("Not confirmed, exiting.")


def main():
    _hard_safety_gate()

    broker = AngelOneAdapter(
        config.ANGEL_API_KEY, config.ANGEL_CLIENT_CODE,
        config.ANGEL_PASSWORD_OR_PIN, config.ANGEL_TOTP_SECRET,
    )
    broker.connect()

    risk = RiskState()
    bars: list = []
    open_trade = None

    print(f"LIVE trading {config.UNDERLYING} -- Ctrl+C to stop "
          f"(any open position is NOT auto-closed on stop -- check broker.get_positions()).")

    try:
        while True:
            if risk.kill_switch_tripped:
                print(f"Kill switch tripped ({risk.kill_switch_reason}). Halting new entries. "
                      f"Manage any open position manually and investigate before restarting.")
                time.sleep(60)
                continue

            now = datetime.now().strftime("%H:%M")
            if now >= config.SQUARE_OFF_TIME and open_trade is None:
                time.sleep(60)
                continue

            # TODO: same token wiring as run_paper.py.
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
                        # TODO: set a real expiry string, resolved from the
                        # scrip master (nearest weekly expiry for the chosen
                        # underlying), before this will actually work.
                        contract = broker.resolve_option_token(
                            config.UNDERLYING, expiry="SET_ME", strike=strike, option_type=direction
                        )
                        result = broker.place_order(
                            tradingsymbol=contract["tradingsymbol"],
                            symbol_token=contract["symboltoken"],
                            exchange=config.EXCHANGE,
                            transaction_type="BUY",
                            quantity=risk.position_size_lots(),
                            product_type=config.OPTION_PRODUCT_TYPE,
                        )
                        log_event(JournalEntry(
                            timestamp=str(pd.Timestamp.now()), event_type="entry",
                            direction=direction, strike=strike, premium=0.0,
                            quantity=risk.position_size_lots(),
                            reason=f"order_id={result.order_id} status={result.status}",
                            mode="live",
                        ))
                        open_trade = {"direction": direction, "strike": strike, "contract": contract, "bars_held": 0}
                        risk.open_positions += 1

                elif open_trade is not None:
                    open_trade["bars_held"] += 1
                    # TODO: real premium, same as run_paper.py.
                    reason = should_exit(1.0, 1.0, open_trade["bars_held"], z)
                    if reason:
                        result = broker.place_order(
                            tradingsymbol=open_trade["contract"]["tradingsymbol"],
                            symbol_token=open_trade["contract"]["symboltoken"],
                            exchange=config.EXCHANGE,
                            transaction_type="SELL",
                            quantity=risk.position_size_lots(),
                            product_type=config.OPTION_PRODUCT_TYPE,
                        )
                        log_event(JournalEntry(
                            timestamp=str(pd.Timestamp.now()), event_type="exit",
                            direction=open_trade["direction"], strike=open_trade["strike"],
                            premium=0.0, quantity=risk.position_size_lots(),
                            reason=f"{reason} order_id={result.order_id}", mode="live",
                        ))
                        risk.open_positions -= 1
                        open_trade = None

            time.sleep(5 * 60)

    except KeyboardInterrupt:
        print("Stopped. Check open positions manually via broker.get_positions().")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
