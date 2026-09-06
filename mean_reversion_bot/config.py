"""
Central configuration for the mean-reversion options pilot.
Edit these values before running backtest / paper / live.
Nothing here should be duplicated elsewhere -- if you find yourself
hardcoding a number in another file, it belongs here instead.
"""

from typing import Literal

# ---------------------------------------------------------------------------
# MODE
# ---------------------------------------------------------------------------
# "backtest" | "paper" | "live"
# Do not hand-edit this to "live" without going through the go/no-go
# checklist in README.md. Live mode also requires LIVE_TRADING_CONFIRMED
# below to be manually flipped -- that's a deliberate second gate.
MODE: Literal["backtest", "paper", "live"] = "backtest"
LIVE_TRADING_CONFIRMED = False

# ---------------------------------------------------------------------------
# INSTRUMENT
# ---------------------------------------------------------------------------
UNDERLYING = "NIFTY"              # "NIFTY" or "BANKNIFTY"
EXCHANGE = "NFO"
STRIKE_STEP = 50                  # NIFTY=50, BANKNIFTY=100 as of recent cycles --
                                   # VERIFY against the live option chain before
                                   # trusting this; exchanges revise these
                                   # periodically (lot sizes were last revised
                                   # Jan 2026 -- strike steps can move too).
OPTION_PRODUCT_TYPE = "INTRADAY"  # v0 always squares off same day, no overnight risk

# ---------------------------------------------------------------------------
# CAPITAL & RISK  (sized for a ~1 lakh pilot -- see README "Capital reality check")
# ---------------------------------------------------------------------------
CAPITAL = 100_000
MAX_LOTS_PER_TRADE = 1
MAX_CONCURRENT_POSITIONS = 1
DAILY_LOSS_LIMIT_PCT = 0.03          # halt new entries for the day past this loss
PER_TRADE_STOP_LOSS_PCT = 0.35       # exit if premium falls 35% from entry
PER_TRADE_TARGET_PCT = 0.50          # exit if premium rises 50% from entry
MAX_HOLD_BARS = 24                   # e.g. 24 x 5-min bars = 2 hours
SQUARE_OFF_TIME = "15:15"            # force-exit time (IST), avoid closing auction

# ---------------------------------------------------------------------------
# STRATEGY: Z-SCORE MEAN REVERSION
# ---------------------------------------------------------------------------
BAR_INTERVAL = "FIVE_MINUTE"         # matches Angel One's getCandleData interval values
ZSCORE_WINDOW = 20
ZSCORE_ENTRY_THRESHOLD = 2.0
ZSCORE_EXIT_THRESHOLD = 0.3          # consider "reverted" once |z| falls below this

# ---------------------------------------------------------------------------
# BACKTEST COST MODEL (Angel One F&O + current SEBI rates -- verify before trusting)
# ---------------------------------------------------------------------------
BROKERAGE_PER_ORDER = 20.0           # flat ~Rs 20/executed order, Angel One F&O
STT_OPTIONS_PCT = 0.0015             # 0.15% on options premium (post Apr-2026 rate)
OTHER_CHARGES_PCT = 0.0005           # rough catch-all: GST + exchange txn + stamp duty
ASSUMED_SLIPPAGE_PCT = 0.01          # 1% of premium per fill -- recalibrate from paper trading

# ---------------------------------------------------------------------------
# BACKTEST VALIDATION
# ---------------------------------------------------------------------------
TRAIN_TEST_SPLIT_DATE = "2026-06-01"  # set to a real date inside your own data range
EMBARGO_DAYS = 5                       # gap between train and test to reduce leakage

# ---------------------------------------------------------------------------
# OPTION PRICING FALLBACK
# Used only until you have real historical option-chain premiums wired in --
# see pricing/black_scholes.py docstring for why this matters.
# ---------------------------------------------------------------------------
ASSUMED_IV = 0.14
RISK_FREE_RATE = 0.065

# ---------------------------------------------------------------------------
# STRATEGY 2: PATTERN REVERSAL (EMA trend filter + RSI extreme + pivot
# support/resistance + candlestick reversal pattern)
# Ported from a Pine Script v6 strategy. Trades the underlying directly,
# LONG and SHORT -- that needs futures-level (or equity intraday) margin,
# not the options-premium-only budget the mean-reversion module is sized
# for. Decide capital/instrument for this one separately; don't assume
# it shares the ~1 lakh options pilot's budget.
# ---------------------------------------------------------------------------
ACTIVE_STRATEGY = "mean_reversion"     # "mean_reversion" | "pattern_reversal"

PATTERN_EMA_LENGTH = 21
PATTERN_RSI_LENGTH = 14
PATTERN_PIVOT_LEN = 5
PATTERN_RSI_OVERSOLD = 30
PATTERN_RSI_OVERBOUGHT = 70
PATTERN_SUPPORT_TOLERANCE_PCT = 0.5
PATTERN_RESISTANCE_TOLERANCE_PCT = 0.5
PATTERN_TARGET_PCT = 0.005              # 0.5%, matches the source Pine script
PATTERN_STOP_PCT = 0.005                # 0.5%, matches the source Pine script
PERSIST_PIVOT_LEVELS = False            # see strategy/pattern_reversal.py docstring
                                         # note 2 -- literal Pine behavior vs.
                                         # an ongoing zone are very different strategies

PATTERN_CAPITAL = 100_000               # <-- set this yourself, separately from
                                         #     the options pilot's CAPITAL above
PATTERN_QUANTITY = 1                    # shares/contracts per trade -- depends on
                                         # PATTERN_CAPITAL and whatever instrument
                                         # you end up running this on
PATTERN_STT_PCT = 0.0005                # 0.05% futures STT (post Apr-2026 rate) --
                                         # change if you run this on cash equities
                                         # instead (different STT schedule)
PATTERN_BROKERAGE_PER_ORDER = 20.0
PATTERN_OTHER_CHARGES_PCT = 0.0005
PATTERN_ASSUMED_SLIPPAGE_PCT = 0.005

# ---------------------------------------------------------------------------
# BROKER: Angel One SmartAPI
# ---------------------------------------------------------------------------
ANGEL_API_KEY = "p3FVaFTD"
ANGEL_CLIENT_CODE = "AAAL256349"
ANGEL_PASSWORD_OR_PIN = "2911"
ANGEL_TOTP_SECRET = "UUCRDR36CTTWC7LCVBYE75GHAM"          # base32 secret behind your SmartAPI QR code
