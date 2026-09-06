# Mean-Reversion / Pattern-Reversal Options & Futures Pilot

A deliberately narrow v0: one broker (Angel One), one capital pool at a
time, two strategy modules, real risk controls from day one. Built to go
from zero code to a small live pilot in 3-6 weeks, not to be the full
quant research platform from the original architecture doc -- that comes
later, if this survives contact with the market.

## Why it's built this way (read this before changing scope)

- **Capital reality check.** NSE's lot-size revision effective the
  January 2026 contract series cut the Nifty 50 lot to 65 units and Bank
  Nifty to 30. At recent index levels, one Nifty futures lot still needs
  roughly Rs 1.7-1.8 lakh in margin -- more than a Rs 1 lakh pilot budget,
  before a single trade. That's why the mean-reversion module trades
  **long options only** (premium paid = max risk, no margin/MTM needed),
  not futures and not short options.
- **Regulatory status.** SEBI's retail algo-trading framework is fully in
  force nationally since April 1, 2026. For an individual trading their
  own capital with their own transparent ("white box") logic, well under
  the 10-orders-per-second threshold, separate SEBI/exchange registration
  generally isn't required -- but a **static IP (or VPS) registered with
  your broker's API console is mandatory**, and STT on options
  (premium + exercise) is now 0.15%, futures STT is 0.05%. Both are
  already reflected in `config.py`'s cost model -- keep them current if
  rates change again.
- **Scope.** The original architecture document's full Trading OS +
  quant-research platform (dataset versioning, experiment tracking, model
  registry, drift detection, ML layer, etc.) is not buildable from zero
  code in a few weeks solo. Everything not needed to safely run one
  strategy on one instrument is deliberately deferred -- see
  `AGENT_PROMPTS.md` for the backlog of what to build next, and only
  after the pilot proves itself.

## Project structure

```
config.py                    All tunable parameters. Nothing should be
                              hardcoded elsewhere -- if you find a magic
                              number in another file, move it here.
broker/
  base_adapter.py             Abstract interface. Strategy/risk code
                               never imports a broker SDK directly.
  angelone_adapter.py          Angel One SmartAPI implementation.
data/
  data_quality.py              OHLC sanity checks -- run on every batch
                               before trusting it.
pricing/
  black_scholes.py             Fallback option pricer for backtesting
                               before you have real historical premiums.
strategy/
  mean_reversion.py            Strategy 1: z-score mean reversion on the
                               underlying, executed via long options.
  pattern_reversal.py          Strategy 2: EMA + RSI + pivot S/R +
                               candlestick pattern, ported from Pine
                               Script. Trades the underlying directly
                               (long AND short) -- different margin
                               profile, see the module docstring.
risk/
  risk_manager.py               Position sizing, daily loss limit, kill
                               switch. Never cut this for speed.
journal/
  trade_journal.py              Append-only signal/order/fill log.
backtest/
  metrics.py                    Sharpe/drawdown/win-rate/profit-factor.
  backtester.py                 Backtest engine for the options strategy.
  pattern_backtester.py         Backtest engine for the pattern strategy
                               (direct price P&L, no options pricer).
run_backtest.py                Backtest the mean-reversion (options) strategy.
run_backtest_pattern.py        Backtest the pattern-reversal strategy.
run_paper.py                   Paper-trade the mean-reversion strategy.
run_live.py                    LIVE-trade the mean-reversion strategy
                               (hard-gated, see below).
AGENT_PROMPTS.md                Ready-to-paste task briefs for continuing
                               this build in ChatGPT Codex or another
                               coding agent, one task at a time.
```

Both strategy/backtester pairs enforce the same two disciplines
throughout: a signal computed from bar *t*'s close is only ever filled at
bar *t+1*'s open (never the same bar), and every trade is intraday, force
-closed at `config.SQUARE_OFF_TIME`.

## One-time setup

1. **Angel One SmartAPI account.** Create an app at
   https://smartapi.angelone.in, note the API key, and enable TOTP-based
   login -- save the base32 secret shown during QR setup (not the 6-digit
   code, which expires in seconds) into `config.ANGEL_TOTP_SECRET`.
2. **Static IP.** Get a static IPv4 (from your ISP, or a small VPS) and
   register it in the SmartAPI developer console. Mandatory under the
   2026 framework -- API calls from unregistered/dynamic IPs get blocked.
   Start this in parallel with everything else, it can take longer than
   the code does.
3. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```
4. **Resolve your instrument tokens once.** Call
   `AngelOneAdapter.load_scrip_master()` and find the symboltoken for
   NIFTY/BANKNIFTY spot (or the relevant index) -- hardcode it where
   `run_paper.py`/`run_live.py` currently say `"SET_ME_TOKEN"`. Tokens
   don't change often, no need to re-resolve every run.
5. **Get historical data for backtesting.** Angel One's `getCandleData`
   covers the underlying well; historical *options chain* depth is often
   much shallower. Check what you actually have access to before
   committing to a backtest lookback window -- see `AGENT_PROMPTS.md`
   task 1 if you need to go further than the broker API provides.

## Running it

```bash
# Backtest the mean-reversion options strategy
python run_backtest.py path/to/underlying_5min.csv

# Backtest the pattern-reversal strategy (needs 1-min bars -- that's
# what the source Pine script was tuned for)
python run_backtest_pattern.py path/to/underlying_1min.csv

# Paper trade (set config.MODE = "paper" first)
python run_paper.py

# Go live (set config.MODE = "live" AND config.LIVE_TRADING_CONFIRMED = True,
# then confirm again interactively -- see go/no-go gate below)
python run_live.py
```

## Go/no-go gate before real money

Move `config.MODE` to `"live"` only when **all** of these are true:

- Paper trading has run for a meaningful number of sessions with zero
  unhandled system errors.
- The kill switch has been deliberately tested (force a daily-loss-limit
  breach in a test run) and confirmed to actually halt new entries.
- Paper P&L direction roughly tracks what the backtest predicted for the
  same days -- it doesn't need to be profitable, but a large, unexplained
  divergence usually means a bug in data, costs, or fills, not that the
  market changed.
- Your broker has confirmed the static IP / API compliance setup is
  complete.

Start live at 1 lot with the loss limits already in `config.py`, and
resist the urge to raise size or add the second strategy live in the
same week you go live with the first.

## What this v0 deliberately does NOT do yet

Real historical option-chain premiums (uses a Black-Scholes fallback
instead), WebSocket streaming (polls instead), multi-broker abstraction
beyond the one clean interface, automated alerting, a test suite, dataset
versioning, experiment tracking, or anything from the ML/MLOps layer of
the original architecture doc. All of that is real, and all of it is
deferred on purpose -- `AGENT_PROMPTS.md` has a ready-to-use task brief
for each one, roughly in the order worth tackling them.
