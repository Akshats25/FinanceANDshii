# Agent Task Prompts

Ready-to-paste briefs for handing the remaining work to ChatGPT Codex (or
any other coding agent). Each one is self-contained -- paste it into a
fresh session along with the repo/zip, and it should have enough context
to work without you re-explaining the project. Do them roughly in the
order listed; later ones assume earlier ones exist, and 6 (tests) is
worth doing early so everything after it stays honest.

Before every task, tell the agent to actually run `python run_backtest.py`
and `python run_backtest_pattern.py` against real or synthetic data
afterward, not just eyeball the diff -- the codebase runs in this
sandbox, it should run in Codex too.

---

## 1. Real historical option-chain data (replace the Black-Scholes fallback)

```
Context: This is a Python algo-trading project (Angel One SmartAPI broker,
NIFTY/BANKNIFTY options). The backtester in backtest/backtester.py
currently prices options using a flat-IV Black-Scholes fallback in
pricing/black_scholes.py, because real historical option-chain premiums
weren't available yet. See that file's docstring for why this matters.

Task: Build a data pipeline that fetches and stores real historical
option-chain data (OHLC per strike/expiry/right, ideally with IV if the
source provides it) for NIFTY and BANKNIFTY. Check what depth Angel One's
own historical API actually provides for the NFO segment before assuming
you need a third-party vendor -- if it's too shallow, evaluate a paid
data vendor and document the tradeoffs (coverage, cost, format) rather
than picking one silently.

Constraints:
- Store data in a way run_backtest.py's daily-DataFrame grouping pattern
  can consume with minimal changes -- match the existing
  [timestamp, open, high, low, close, volume] shape, extended with
  strike/expiry/right columns as needed.
- Add a data-quality check for the option data mirroring
  data/data_quality.py's approach (bad OHLC, gaps, duplicates) --
  options data has its own failure modes too (e.g. zero open interest,
  stale quotes near illiquid strikes).
- Keep pricing/black_scholes.py in place as an explicit fallback/sanity
  check, not deleted -- add a flag to switch between real data and the
  fallback so the two can be compared.

Acceptance criteria: run_backtest.py can optionally source premiums from
real historical data instead of Black-Scholes, and produces a written
comparison of the two on the same historical period.
```

---

## 2. WebSocket live data (replace polling in run_paper.py / run_live.py)

```
Context: run_paper.py and run_live.py currently poll broker.get_ltp() in
a `while True: ... time.sleep(5*60)` loop. Angel One's SmartAPI exposes
SmartWebSocketV2 (see broker/angelone_adapter.py's docstring for the
import path) for real-time streaming instead.

Task: Add WebSocket-based live data ingestion to the AngelOneAdapter
(broker/angelone_adapter.py), and refactor run_paper.py and run_live.py
to consume streamed ticks instead of polling. Bars should still be
aggregated to config.BAR_INTERVAL before being handed to the strategy
functions (strategy/mean_reversion.py expects one row per bar, not raw
ticks).

Constraints:
- Keep the BrokerAdapter interface (broker/base_adapter.py) intent
  intact -- if you add new abstract methods for streaming, add them
  there too, not just on the Angel One implementation, so a future
  second broker can implement them.
- Handle reconnects: a dropped WebSocket should not silently stop the
  strategy loop or duplicate bars.
- Don't change the point-in-time discipline already in
  strategy/mean_reversion.py and strategy/pattern_reversal.py (signal on
  bar t's close, fill at bar t+1's open) -- streaming should feed that
  same discipline, not bypass it.

Acceptance criteria: run_paper.py runs unattended through a live session
using streamed data, with a reconnect test (kill the connection
mid-session) that recovers without crashing or double-counting bars.
```

---

## 3. Expiry & instrument resolution automation

```
Context: broker/angelone_adapter.py has resolve_option_token(), which
looks up a contract's symboltoken from Angel One's scrip master JSON by
matching name/exchange/strike/option-type/expiry. The expiry string
format has to match the scrip master's own format exactly, which isn't
verified anywhere yet, and there's no logic for picking "nearest weekly
expiry" automatically -- run_live.py currently has expiry="SET_ME" as a
placeholder.

Task: Add a function that, given an underlying and a target (e.g.
"nearest weekly", "nearest monthly"), inspects the scrip master and
returns the correctly-formatted expiry string and the resolved contract.
Cache the scrip master with a sensible refresh policy (it's a large file,
don't re-download it every call, but don't let it go stale across an
expiry rollover either).

Constraints:
- Handle the weekly rollover correctly: on/after the last trading day of
  an expiry, "nearest weekly" should mean next week's contract, not the
  one that just expired.
- Fail loudly (raise, don't silently default) if no matching contract is
  found -- this is exactly the kind of silent wrong-answer risk flagged
  throughout this project.
- Add a small test fixture (a saved sample of scrip-master JSON) so this
  logic can be unit-tested without hitting the network every time.

Acceptance criteria: run_live.py and run_paper.py no longer contain any
"SET_ME" placeholder for expiry; a unit test proves correct rollover
behavior across an expiry boundary.
```

---

## 4. Order lifecycle robustness

```
Context: broker/angelone_adapter.py's place_order() fires a single
request and returns whatever the API responds with. run_live.py assumes
that response is reliable and doesn't retry, reconcile, or handle partial
fills. risk/risk_manager.py's RiskState.open_positions is just an int
that run_live.py increments/decrements by hand -- it isn't reconciled
against what the broker actually shows.

Task: Add retry-with-backoff around order placement and status polling
(individual_order_details), handle partial fills explicitly (a partial
fill should not be treated as a clean entry/exit), and add a startup
reconciliation step that calls broker.get_positions() and refuses to
proceed if there's a live position the script doesn't know about
(don't auto-adjust silently -- surface it and require a human decision).

Constraints:
- Every retry, partial fill, and reconciliation mismatch must go through
  journal/trade_journal.py's log_event(), not just a print statement --
  this is exactly the append-only audit trail the project's risk
  section depends on.
- Don't weaken risk/risk_manager.py's kill-switch semantics: a
  reconciliation failure should trip the kill switch, not just log a
  warning and continue.

Acceptance criteria: a simulated partial-fill and a simulated
"unexpected open position on startup" scenario both behave safely
(halt and log, not silently proceed) in a test harness.
```

---

## 5. Alerting on kill-switch trips and errors

```
Context: risk/risk_manager.py's RiskState.trip_kill_switch() currently
just sets a flag and a reason string -- nothing notifies you when it
fires. If this is running unattended, a tripped kill switch or an
unhandled exception should reach you immediately, not just sit in
trade_journal.csv until you happen to check it.

Task: Add a notification hook (Telegram bot or email, your choice --
Telegram is usually the fastest to set up for this) that fires whenever
RiskState.trip_kill_switch() is called, and whenever run_paper.py /
run_live.py hit an unhandled exception in the main loop.

Constraints:
- Keep credentials for the notification channel in config.py alongside
  the other "SET_ME" broker credentials, not hardcoded.
- The notification call itself must not be able to crash the trading
  loop (wrap it, don't let a failed Telegram API call take down a live
  session) -- and it must not block for more than a couple of seconds.

Acceptance criteria: forcing a kill-switch trip and forcing an unhandled
exception in a test run both result in a real notification within
seconds, and neither one crashes the main loop.
```

---

## 6. Automated test suite

```
Context: Everything so far has been validated by hand with synthetic
random-walk data and manual inspection (see the point-in-time and pivot-
lag reasoning in strategy/mean_reversion.py and
strategy/pattern_reversal.py's docstrings). There's no repeatable test
suite yet.

Task: Write a pytest suite covering, at minimum:
- strategy/mean_reversion.py: z-score math on known input, and a
  specific regression test proving a signal generated from bar t is
  never filled using bar t's own price (feed it a crafted DataFrame
  where getting this wrong would produce a detectably different result).
- strategy/pattern_reversal.py: the pivot-lag behavior specifically --
  construct a DataFrame with a known local low, and assert the pivot
  value is NaN until exactly pivot_len bars after it, matching
  translation note 1 in that file's docstring. Also test
  PERSIST_PIVOT_LEVELS True vs False produce different results on the
  same input.
- data/data_quality.py: each check (bad OHLC, duplicates, out-of-order,
  intraday gaps) against a deliberately corrupted fixture, and a
  confirmation that normal overnight session boundaries do NOT trigger
  the gap check.
- backtest/metrics.py: known trade-PnL lists with hand-computed expected
  Sharpe/drawdown/win-rate, not just "does it run without error."

Constraints:
- Tests must not require network access or real broker credentials --
  everything broker-related should be tested against a mocked
  BrokerAdapter, not AngelOneAdapter directly.
- Put fixtures in a tests/fixtures/ directory, not inline as giant
  literals, so they're reusable across tests.

Acceptance criteria: `pytest` passes from a clean checkout with no
network access and no config.py credentials filled in.
```

---

## 7. Daily paper-trading report

```
Context: run_paper.py logs every signal/entry/exit to
journal/trade_journal.py's CSV. The README's go/no-go gate depends on
comparing "paper P&L direction" against "what the backtest would have
predicted for the same day" -- right now that comparison is manual.

Task: Build a script that, given a completed paper-trading session's
journal entries and the corresponding day's underlying OHLC data, runs
that day through backtest/backtester.py (or pattern_backtester.py) and
produces a short report: actual paper trades vs. what the backtest would
have generated, flagging any day where they diverge (different number of
signals, different direction, or PnL sign mismatch).

Constraints:
- Read directly from trade_journal.csv's existing schema
  (journal/trade_journal.py's JournalEntry) -- don't change that schema,
  extend the report to work with it as-is.
- Output should be readable in a terminal (a human checking this every
  evening during the paper-trading phase) -- a markdown or plain-text
  summary is fine, no need for a dashboard yet.

Acceptance criteria: running the report against a day with deliberately
mismatched paper/backtest behavior (e.g. by hand-editing a journal entry)
clearly flags the mismatch.
```

---

## 8. Deployment (VPS, static IP, process supervision)

```
Context: The SEBI 2026 framework requires a static IP registered with
the broker (see README's "Static IP" setup step) -- most people satisfy
this with a small VPS rather than a home static IP. run_paper.py /
run_live.py are currently meant to be run in a foreground terminal.

Task: Set this up to run unattended on a VPS: a systemd service (or
equivalent process supervisor) that starts run_live.py (or run_paper.py)
on a schedule aligned to market hours, restarts it on crash with a
backoff, and ships logs somewhere durable (not just stdout that
disappears on restart).

Constraints:
- The service must NOT auto-restart past a kill-switch trip -- a crash
  should restart, a deliberate risk halt should not. Distinguish the two
  in the exit code or a sentinel file, don't just restart on any process
  exit.
- Document the actual VPS provider/IP/firewall steps taken, in enough
  detail that this is reproducible if the VPS needs to be rebuilt.

Acceptance criteria: killing the process (simulating a crash) restarts
it within a defined backoff window; triggering a real kill-switch trip
does not.
```

---

## 9. Second broker adapter (multi-broker, when you're ready)

```
Context: broker/base_adapter.py defines BrokerAdapter specifically so a
second broker can be added without touching strategy, risk, or backtest
code. This is a "later" task per the original project plan -- only do
this once the Angel One pilot has actually run live for a while.

Task: Implement a second BrokerAdapter subclass (Zerodha Kite Connect is
a common second choice) covering the same interface: connect,
get_historical_candles, get_ltp, place_order, get_order_status,
get_positions, disconnect.

Constraints:
- Do not modify broker/base_adapter.py's interface to accommodate broker-
  specific quirks -- if something doesn't map cleanly, handle the
  translation inside the new adapter, keeping the interface broker-
  agnostic. If the interface genuinely can't express something needed,
  that's worth flagging back rather than silently working around it.
- run_paper.py / run_live.py should be able to switch broker by changing
  one line (which adapter class gets instantiated), nothing else.

Acceptance criteria: run_backtest.py's historical-data step works
unchanged against either broker's adapter for the same instrument and
date range, modulo actual data differences between the two brokers.
```

---

## 10. Post-pilot: data/quant research layer

```
Context: The original architecture review (that started this project)
flagged a full quant-research layer -- dataset versioning, experiment
tracking, a model registry, purged/embargoed cross-validation, drift
detection, and eventually an ML layer -- as valuable but explicitly out
of scope for the v0 pilot. Only start this once the pilot has run live
long enough to have real, non-synthetic results worth tracking.

Task: Do NOT build all of this speculatively. Start with the smallest
piece that has immediate value: a simple experiment log (one row per
backtest run, capturing dataset version/date-range, strategy + config
snapshot, code commit hash, and the resulting metrics from
backtest/metrics.py) so that six months from now a specific backtest run
can be reproduced exactly. Propose the next piece only after that one is
in daily use.

Constraints:
- Reuse the existing config.py values and backtest/metrics.py output
  directly -- don't invent a parallel config or metrics format.
- This must not become a prerequisite for anything in tasks 1-9 above --
  it's additive, for when there's enough real trading history to make
  research infrastructure worth the overhead.

Acceptance criteria: every run of run_backtest.py or
run_backtest_pattern.py appends one reproducible, timestamped record to
an experiment log, with enough information to re-run that exact
backtest later.
```
