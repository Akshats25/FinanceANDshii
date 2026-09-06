"""
Flask dashboard — real-data edition.

Sources:
  • Angel One SmartAPI  — NIFTY/BANKNIFTY LTP, option chain, historical candles
  • Binance REST        — BTC/USDT OHLCV (no auth)
  • CoinGecko REST      — BTC price + 24-h stats (no auth)

Credentials: fill ANGEL_API_KEY / ANGEL_CLIENT_CODE / ANGEL_PASSWORD_OR_PIN /
ANGEL_TOTP_SECRET in mean_reversion_bot/config.py. The broker session is
attempted at startup; if it fails the dashboard still runs with graceful
"N/A" values everywhere Angel One data would appear.
"""

import os
import sys
import json
import math
import csv
import random
import io
import threading
import time
from datetime import datetime, timedelta
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from flask import Flask, render_template, request, jsonify

import config
from strategy.mean_reversion import generate_signals, compute_zscore, select_strike, should_exit as mr_should_exit
from strategy.pattern_reversal import generate_signals as pat_generate_signals
from backtest.backtester import run_backtest as run_mr_backtest, run_train_test_split
from backtest.pattern_backtester import run_backtest as run_pat_backtest
from backtest.metrics import compute_metrics
from pricing.black_scholes import bs_price
from risk.risk_manager import RiskState
from journal.trade_journal import log_event, JournalEntry, JOURNAL_PATH
from data.data_quality import check_ohlc

# Dashboard-local module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_data
import execution

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "qe-trading-secret-2026"

# ─────────────────────────────────────────────────────────────────────────────
# Angel One broker session — attempted once at startup, non-fatal if missing
# ─────────────────────────────────────────────────────────────────────────────
_broker = None
_broker_error = None
_broker_lock = threading.Lock()


def _try_connect_broker():
    global _broker, _broker_error
    if config.ANGEL_API_KEY == "SET_ME":
        _broker_error = "credentials_not_set"
        return

    try:
        import pyotp
        from SmartApi import SmartConnect
        session = SmartConnect(api_key=config.ANGEL_API_KEY)
        totp = pyotp.TOTP(config.ANGEL_TOTP_SECRET).now()
        data = session.generateSession(
            config.ANGEL_CLIENT_CODE,
            config.ANGEL_PASSWORD_OR_PIN,
            totp,
        )
        if not data.get("status", False):
            _broker_error = f"login_failed: {data.get('message', 'unknown')}"
            return

        with _broker_lock:
            _broker = session
        live_data.set_angel_session(session)
        print("[broker] Angel One connected")

    except ImportError:
        _broker_error = "smartapi-python not installed"
    except Exception as e:
        _broker_error = str(e)
        print(f"[broker] Connection failed: {e}")


# Connect in a background thread so Flask starts immediately
threading.Thread(target=_try_connect_broker, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Paper trading state
# ─────────────────────────────────────────────────────────────────────────────
paper_state = {
    "running": False,
    "risk": RiskState(),
    "bars": [],
    "open_trade": None,
    "log": [],
    "use_real_prices": False,
    "last_real_price": None,
}

# ─────────────────────────────────────────────────────────────────────────────
# Price history buffers (for sparklines / live charts)
# ─────────────────────────────────────────────────────────────────────────────
_price_history = {
    "nifty":  [],   # deque-like list, max 200 points
    "bnifty": [],
    "btc":    [],
}
_HIST_MAX = 200


def _push_price(key: str, price: float):
    buf = _price_history[key]
    buf.append({"ts": datetime.now().strftime("%H:%M:%S"), "price": price})
    if len(buf) > _HIST_MAX:
        buf.pop(0)


# ─────────────────────────────────────────────────────────────────────────────
# Background price poller (every 10 s during market hours)
# ─────────────────────────────────────────────────────────────────────────────
def _price_poll_loop():
    while True:
        try:
            btc = live_data.get_btc_price()
            if btc.get("price_usd"):
                _push_price("btc", btc["price_usd"])

            nifty = live_data.get_nifty_ltp()
            if nifty.get("ltp"):
                _push_price("nifty", nifty["ltp"])
                paper_state["last_real_price"] = nifty["ltp"]

            bnifty = live_data.get_banknifty_ltp()
            if bnifty.get("ltp"):
                _push_price("bnifty", bnifty["ltp"])

        except Exception:
            pass
        time.sleep(10)


threading.Thread(target=_price_poll_loop, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _generate_synthetic_ohlcv(n_bars=200, base_price=22000.0, bar_minutes=5,
                               start="2026-01-02 09:15:00"):
    rng = np.random.default_rng(42)
    ts = pd.date_range(start, periods=n_bars, freq=f"{bar_minutes}min")
    returns = rng.normal(0, 0.0025, n_bars)
    close = base_price * np.exp(np.cumsum(returns))
    high = close * (1 + abs(rng.normal(0, 0.001, n_bars)))
    low  = close * (1 - abs(rng.normal(0, 0.001, n_bars)))
    open_ = np.roll(close, 1);  open_[0] = base_price
    volume = rng.integers(10000, 50000, n_bars)
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                          "low": low, "close": close, "volume": volume})


def _split_into_daily(df):
    df = df.copy()
    df["date"] = df["timestamp"].dt.date
    return {str(d): g.drop(columns="date").reset_index(drop=True)
            for d, g in df.groupby("date")}


def _load_journal():
    if not os.path.isfile(JOURNAL_PATH):
        return []
    try:
        with open(JOURNAL_PATH, newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Routes — pages
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ─────────────────────────────────────────────────────────────────────────────
# Routes — live market data
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/market/ticker")
def market_ticker():
    """All live prices for the top bar — called every 10 s by the front end."""
    btc    = live_data.get_btc_price()
    nifty  = live_data.get_nifty_ltp()
    bnifty = live_data.get_banknifty_ltp()
    return jsonify({
        "btc_usd":     btc.get("price_usd"),
        "btc_inr":     btc.get("price_inr"),
        "btc_chg24":   btc.get("change_24h_pct"),
        "btc_vol24":   btc.get("volume_24h_usd"),
        "nifty_ltp":   nifty.get("ltp"),
        "bnifty_ltp":  bnifty.get("ltp"),
        "broker_ok":   _broker is not None,
        "broker_error": _broker_error,
    })


@app.route("/api/market/btc_candles")
def btc_candles():
    interval = request.args.get("interval", "5m")
    limit    = int(request.args.get("limit", 100))
    data = live_data.get_btc_candles(interval, limit)
    return jsonify(data)


@app.route("/api/market/btc_zscore")
def btc_zscore():
    interval = request.args.get("interval", "5m")
    window   = int(request.args.get("window", 20))
    data = live_data.get_btc_zscore(interval, window)
    return jsonify(data)


@app.route("/api/market/price_history")
def price_history():
    """Buffered price history for sparklines."""
    return jsonify({
        "nifty":  _price_history["nifty"][-100:],
        "bnifty": _price_history["bnifty"][-100:],
        "btc":    _price_history["btc"][-100:],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Routes — option chain
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/options/chain")
def option_chain():
    underlying = request.args.get("underlying", config.UNDERLYING)
    expiry     = request.args.get("expiry", None)

    # Use real NIFTY LTP as spot, fallback to 22000
    spot_data = live_data.get_nifty_ltp()
    spot = spot_data.get("ltp") or 22000.0

    chain = live_data.get_option_chain(underlying, spot, expiry, strikes_around=10)
    nearest = live_data.get_nearest_expiry(underlying, "weekly")
    return jsonify({
        "chain": chain,
        "spot": spot,
        "nearest_expiry": nearest,
        "underlying": underlying,
    })


@app.route("/api/options/expiries")
def option_expiries():
    underlying = request.args.get("underlying", config.UNDERLYING)
    # Get all unique expiries from scrip master
    df = live_data._load_scrip_master()
    if df is None:
        return jsonify({"expiries": [], "error": "scrip_master_unavailable"})
    try:
        opts = df[(df["name"] == underlying) & (df["exch_seg"] == "NFO")]
        expiries = sorted(opts["expiry"].dropna().unique().tolist())
        return jsonify({"expiries": expiries})
    except Exception as e:
        return jsonify({"expiries": [], "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Routes — backtest
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/backtest/run", methods=["POST"])
def run_backtest_api():
    data = request.get_json(force=True) or {}
    strategy   = data.get("strategy", "mean_reversion")
    n_bars     = int(data.get("n_bars", 390))
    base_price = float(data.get("base_price", 22000.0))

    instrument = data.get("instrument", "NIFTY")

    df = _generate_synthetic_ohlcv(n_bars=n_bars, base_price=base_price)
    daily_dfs = _split_into_daily(df)
    lot_size  = {"NIFTY": 65, "BANKNIFTY": 30}.get(config.UNDERLYING, 65)
    inst_type = "OPTIONS" if instrument == "NIFTY" else "SPOT"

    all_trades = []
    daily_metrics = []

    for date_str, day_df in sorted(daily_dfs.items()):
        if strategy == "mean_reversion":
            result = run_mr_backtest(day_df, lot_size, instrument_type=inst_type)
        else:
            result = run_pat_backtest(day_df)
        all_trades.extend(result["trades"])
        daily_metrics.append({
            "date": date_str,
            "trades": result["metrics"].get("trades", 0),
            "pnl":    result["metrics"].get("total_pnl", 0),
            "win_rate": result["metrics"].get("win_rate", 0),
        })

    pnls = [t.pnl for t in all_trades]
    metrics = compute_metrics(pnls, config.CAPITAL)

    equity = [config.CAPITAL]
    running = config.CAPITAL
    for p in pnls:
        running += p
        equity.append(round(running, 2))

    trade_list = []
    for t in all_trades[-50:]:
        td = asdict(t) if hasattr(t, "__dataclass_fields__") else t.__dict__
        td["entry_time"] = str(td.get("entry_time", ""))
        td["exit_time"]  = str(td.get("exit_time", ""))
        trade_list.append(td)

    return jsonify({
        "metrics": metrics,
        "equity_curve": equity,
        "daily_metrics": daily_metrics,
        "trades": trade_list,
        "strategy": strategy,
        "days_backtested": len(daily_dfs),
        "data_source": "synthetic",
    })


@app.route("/api/backtest/upload", methods=["POST"])
def backtest_upload():
    """
    Accept a CSV upload (Angel One getCandleData export) and run the
    backtest on real historical data.
    Expected columns: timestamp, open, high, low, close, volume
    """
    if "file" not in request.files:
        return jsonify({"error": "no_file"}), 400

    f = request.files["file"]
    strategy = request.form.get("strategy", "mean_reversion")
    instrument = request.form.get("instrument", "NIFTY")

    try:
        df = pd.read_csv(f, parse_dates=["timestamp"])
    except Exception as e:
        return jsonify({"error": f"csv_parse_failed: {e}"}), 400

    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return jsonify({"error": f"missing_columns: need {required - set(df.columns)}"}), 400

    problems = check_ohlc(df)
    if problems:
        return jsonify({"error": "data_quality", "problems": problems}), 400

    daily_dfs = _split_into_daily(df)
    lot_size  = {"NIFTY": 65, "BANKNIFTY": 30}.get(config.UNDERLYING, 65)
    inst_type = "OPTIONS" if instrument == "NIFTY" else "SPOT"

    all_trades = []
    daily_metrics = []

    for date_str, day_df in sorted(daily_dfs.items()):
        if strategy == "mean_reversion":
            result = run_mr_backtest(day_df, lot_size, instrument_type=inst_type)
        else:
            result = run_pat_backtest(day_df)
        all_trades.extend(result["trades"])
        daily_metrics.append({
            "date": date_str,
            "trades": result["metrics"].get("trades", 0),
            "pnl":    result["metrics"].get("total_pnl", 0),
            "win_rate": result["metrics"].get("win_rate", 0),
        })

    pnls = [t.pnl for t in all_trades]
    metrics = compute_metrics(pnls, config.CAPITAL)

    equity = [config.CAPITAL]
    running = config.CAPITAL
    for p in pnls:
        running += p
        equity.append(round(running, 2))

    trade_list = []
    for t in all_trades[-100:]:
        td = asdict(t) if hasattr(t, "__dataclass_fields__") else t.__dict__
        td["entry_time"] = str(td.get("entry_time", ""))
        td["exit_time"]  = str(td.get("exit_time", ""))
        trade_list.append(td)

    return jsonify({
        "metrics": metrics,
        "equity_curve": equity,
        "daily_metrics": daily_metrics,
        "trades": trade_list,
        "strategy": strategy,
        "days_backtested": len(daily_dfs),
        "data_source": "uploaded_csv",
        "rows": len(df),
    })


@app.route("/api/backtest/fetch_and_run", methods=["POST"])
def backtest_fetch_and_run():
    """
    Fetch historical data from Angel One then run backtest — no CSV needed.
    Body: { symbol_token, exchange, interval, from_date, to_date, strategy }
    """
    data = request.get_json(force=True) or {}
    instrument   = data.get("instrument", "NIFTY")
    
    if instrument == "NIFTY" and _broker is None:
        return jsonify({"error": "broker_not_connected",
                        "hint": "Fill Angel One credentials in config.py"}), 503

    symbol_token = data.get("symbol_token", NIFTY_TOKEN)
    exchange     = data.get("exchange", "NSE")
    interval     = data.get("interval", "FIVE_MINUTE")
    from_date    = data.get("from_date", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M"))
    to_date      = data.get("to_date",   datetime.now().strftime("%Y-%m-%d %H:%M"))
    strategy     = data.get("strategy", "mean_reversion")

    if instrument == "BTC":
        binance_intervals = {
            "ONE_MINUTE": "1m", "FIVE_MINUTE": "5m", 
            "FIFTEEN_MINUTE": "15m", "ONE_HOUR": "1h"
        }
        b_interval = binance_intervals.get(interval, "5m")
        candles = live_data.get_btc_candles(b_interval, limit=1000)
        if not candles:
            return jsonify({"error": "Failed to fetch BTC data from Binance"}), 400
        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    else:
        df = live_data.get_historical_candles(_broker, symbol_token, exchange, interval, from_date, to_date)
        
    if df.empty:
        return jsonify({"error": "no_data_returned"}), 400

    daily_dfs = _split_into_daily(df)
    lot_size  = {"NIFTY": 65, "BANKNIFTY": 30}.get(config.UNDERLYING, 65)
    inst_type = "OPTIONS" if instrument == "NIFTY" else "SPOT"
    
    all_trades = []
    daily_metrics = []

    for date_str, day_df in sorted(daily_dfs.items()):
        if strategy == "mean_reversion":
            result = run_mr_backtest(day_df, lot_size, instrument_type=inst_type)
        else:
            result = run_pat_backtest(day_df)
        all_trades.extend(result["trades"])
        daily_metrics.append({
            "date": date_str,
            "trades": result["metrics"].get("trades", 0),
            "pnl":    result["metrics"].get("total_pnl", 0),
        })

    pnls = [t.pnl for t in all_trades]
    metrics = compute_metrics(pnls, config.CAPITAL)
    equity = [config.CAPITAL]
    running = config.CAPITAL
    for p in pnls:
        running += p
        equity.append(round(running, 2))

    trade_list = []
    for t in all_trades[-100:]:
        td = asdict(t) if hasattr(t, "__dataclass_fields__") else t.__dict__
        td["entry_time"] = str(td.get("entry_time", ""))
        td["exit_time"]  = str(td.get("exit_time", ""))
        trade_list.append(td)

    return jsonify({
        "metrics": metrics, "equity_curve": equity,
        "daily_metrics": daily_metrics, "trades": trade_list,
        "strategy": strategy, "days_backtested": len(daily_dfs),
        "data_source": "angel_one_live", "rows": len(df),
    })


NIFTY_TOKEN  = live_data.NIFTY_TOKEN
BNIFTY_TOKEN = live_data.BNIFTY_TOKEN


# ─────────────────────────────────────────────────────────────────────────────
# Routes — paper trading
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/paper/status")
def paper_status():
    risk = paper_state["risk"]
    return jsonify({
        "running":        paper_state["running"],
        "daily_pnl":      round(risk.daily_pnl, 2),
        "open_positions": risk.open_positions,
        "kill_switch":    risk.kill_switch_tripped,
        "kill_switch_reason": risk.kill_switch_reason,
        "bars_collected": len(paper_state["bars"]),
        "open_trade":     paper_state["open_trade"],
        "log":            paper_state["log"][-30:],
        "using_real":     paper_state["use_real_prices"],
    })


@app.route("/api/paper/start", methods=["POST"])
def paper_start():
    data = request.get_json(force=True) or {}
    paper_state["running"] = True
    paper_state["use_real_prices"] = data.get("use_real", _broker is not None)
    src = "real NIFTY LTP" if paper_state["use_real_prices"] else "simulated prices"
    paper_state["log"].append(f"[{_now()}] 🟡 Paper trading started ({src})")
    return jsonify({"status": "started", "source": src})


@app.route("/api/paper/stop", methods=["POST"])
def paper_stop():
    paper_state["running"] = False
    paper_state["log"].append(f"[{_now()}] ⏹ Paper trading stopped")
    return jsonify({"status": "stopped"})


@app.route("/api/paper/tick", methods=["POST"])
def paper_tick():
    """
    Advance by one bar. Uses real NIFTY LTP if broker connected,
    otherwise simulates a random tick.
    """
    if not paper_state["running"]:
        return jsonify({"error": "not_running"}), 400

    risk = paper_state["risk"]
    bars = paper_state["bars"]

    # Get price
    if paper_state["use_real_prices"] and _broker is not None:
        ltp_data = live_data.get_nifty_ltp()
        price = ltp_data.get("ltp")
        if price is None:
            price = (bars[-1]["close"] if bars else 22000.0) * (1 + np.random.normal(0, 0.001))
    else:
        last = bars[-1]["close"] if bars else 22000.0
        price = last * (1 + np.random.normal(0, 0.002))

    now_ts = pd.Timestamp.now()
    bars.append({
        "timestamp": now_ts,
        "close": price,
        "open": bars[-1]["close"] if bars else price,
        "high": price * 1.001,
        "low":  price * 0.999,
        "volume": random.randint(10000, 50000),
    })

    msg = f"[{_now()}] Tick ₹{price:,.2f}"

    if len(bars) >= config.ZSCORE_WINDOW:
        df_bars = pd.DataFrame(bars)
        df_bars["zscore"] = compute_zscore(df_bars)
        z = float(df_bars["zscore"].iloc[-1])
        msg += f" | Z: {z:.3f}"

        if paper_state["open_trade"] is None and risk.can_open_new_position():
            direction = None
            if z <= -config.ZSCORE_ENTRY_THRESHOLD:
                direction = "CE"
            elif z >= config.ZSCORE_ENTRY_THRESHOLD:
                direction = "PE"

            if direction:
                strike = select_strike(price, direction)
                
                # Mock options premium at 100 for Mean Reversion paper trade
                qty = risk.position_size_lots()
                trade_id = execution.log_trade(
                    instrument=f"NIFTY {strike} {direction}",
                    direction=direction,
                    entry=100.0,
                    stop=0,
                    target=0,
                    qty=qty,
                    rr=0,
                    order_id=f"MR_{int(time.time())}",
                    status="OPEN",
                    exchange="NFO",
                    tradingsymbol="NIFTY",
                    mode="paper",
                    strategy="mean_reversion"
                )
                
                paper_state["open_trade"] = {
                    "trade_id": trade_id,
                    "direction": direction,
                    "strike": strike,
                    "entry_price": price,
                    "bars_held": 0,
                    "entry_time": str(now_ts),
                }
                risk.open_positions += 1
                paper_state["log"].append(
                    f"[{_now()}] 🟢 ENTRY {direction} | Strike {strike} | ₹{price:,.2f} | Z={z:.2f}")

        elif paper_state["open_trade"] is not None:
            trade = paper_state["open_trade"]
            trade["bars_held"] += 1
            # Mock premium: 1% of underlying move ×5 leverage
            entry_premium = 100.0
            current_premium = entry_premium * (1 + (price - trade["entry_price"]) / trade["entry_price"] * 5)
            reason = mr_should_exit(entry_premium, current_premium, trade["bars_held"], z)

            now_str = datetime.now().strftime("%H:%M")
            if now_str >= config.SQUARE_OFF_TIME:
                reason = "square_off_time"

            if reason:
                lot_size = {"NIFTY": 65, "BANKNIFTY": 30}.get(config.UNDERLYING, 65)
                gross_pnl = (current_premium - entry_premium) * config.MAX_LOTS_PER_TRADE * lot_size
                net_pnl = gross_pnl - 80  # rough costs
                risk.record_trade_pnl(net_pnl)
                risk.open_positions = max(0, risk.open_positions - 1)
                
                execution.close_trade(trade["trade_id"], current_premium)
                
                sign = "🟢" if net_pnl > 0 else "🔴"
                paper_state["log"].append(
                    f"[{_now()}] {sign} EXIT {trade['direction']} | {reason} | ₹{net_pnl:+,.2f}")
                paper_state["open_trade"] = None

    paper_state["log"].append(msg)

    risk_d = {
        "running": paper_state["running"],
        "daily_pnl": round(risk.daily_pnl, 2),
        "open_positions": risk.open_positions,
        "kill_switch": risk.kill_switch_tripped,
        "kill_switch_reason": risk.kill_switch_reason,
        "bars_collected": len(bars),
        "open_trade": paper_state["open_trade"],
        "log": paper_state["log"][-30:],
        "using_real": paper_state["use_real_prices"],
    }
    return jsonify(risk_d)


@app.route("/api/paper/reset", methods=["POST"])
def paper_reset():
    paper_state.update({
        "running": False,
        "risk": RiskState(),
        "bars": [],
        "open_trade": None,
        "log": ["Session reset."],
        "use_real_prices": False,
        "last_real_price": None,
    })
    return jsonify({"status": "reset"})


# ─────────────────────────────────────────────────────────────────────────────
# Routes — risk
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/risk")
def get_risk():
    risk = paper_state["risk"]
    capital = config.CAPITAL
    loss_limit = capital * config.DAILY_LOSS_LIMIT_PCT
    return jsonify({
        "capital": capital,
        "daily_pnl": round(risk.daily_pnl, 2),
        "daily_loss_limit": round(loss_limit, 2),
        "pnl_pct": round(risk.daily_pnl / capital * 100, 2),
        "limit_pct": round(config.DAILY_LOSS_LIMIT_PCT * 100, 2),
        "open_positions": risk.open_positions,
        "max_positions": config.MAX_CONCURRENT_POSITIONS,
        "kill_switch": risk.kill_switch_tripped,
        "kill_switch_reason": risk.kill_switch_reason,
        "can_trade": risk.can_open_new_position(),
    })


@app.route("/api/risk/reset_kill_switch", methods=["POST"])
def reset_kill_switch():
    paper_state["risk"].kill_switch_tripped = False
    paper_state["risk"].kill_switch_reason  = ""
    paper_state["log"].append(f"[{_now()}] ⚠️ Kill switch manually reset")
    return jsonify({"status": "reset"})


# ─────────────────────────────────────────────────────────────────────────────
# Routes — signals (demo on synthetic; real BTC from Binance)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/signals/nifty_demo")
def nifty_demo_signals():
    n = int(request.args.get("n", 100))
    df = _generate_synthetic_ohlcv(n_bars=n)
    df["zscore"] = compute_zscore(df)
    signals = generate_signals(df)
    return jsonify([{
        "timestamp": str(r["timestamp"]),
        "close":   round(r["close"], 2),
        "zscore":  round(r["zscore"], 4) if not pd.isna(r["zscore"]) else None,
        "signal":  r["signal"],
    } for _, r in signals.iterrows()])


@app.route("/api/signals/btc_live")
def btc_live_signals():
    """BTC z-score on real Binance candles."""
    interval = request.args.get("interval", "5m")
    window   = int(request.args.get("window", 20))
    data = live_data.get_btc_zscore(interval, window)
    return jsonify(data)


@app.route("/api/signals/pattern_demo")
def pattern_demo_signals():
    n = int(request.args.get("n", 200))
    df = _generate_synthetic_ohlcv(n_bars=n, bar_minutes=1)
    signals = pat_generate_signals(df)
    return jsonify([{
        "timestamp": str(r["timestamp"]),
        "close":  round(r["close"], 2),
        "ema":    round(r["ema"], 2) if not pd.isna(r.get("ema", float("nan"))) else None,
        "rsi":    round(r["rsi"], 2) if not pd.isna(r.get("rsi", float("nan"))) else None,
        "signal": r["signal"],
    } for _, r in signals.iterrows()])


# ─────────────────────────────────────────────────────────────────────────────
# Routes — option pricer
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/pricer", methods=["POST"])
def option_pricer():
    d = request.get_json(force=True) or {}
    try:
        spot   = float(d.get("spot", 22000))
        strike = float(d.get("strike", 22000))
        tte    = float(d.get("tte_days", 3)) / 365.0
        iv     = float(d.get("iv", config.ASSUMED_IV))
        rate   = float(d.get("rate", config.RISK_FREE_RATE))

        ce = bs_price(spot, strike, tte, iv, rate, "CE")
        pe = bs_price(spot, strike, tte, iv, rate, "PE")
        h  = spot * 0.001
        delta_ce = (bs_price(spot+h, strike, tte, iv, rate, "CE") -
                    bs_price(spot-h, strike, tte, iv, rate, "CE")) / (2*h)
        delta_pe = (bs_price(spot+h, strike, tte, iv, rate, "PE") -
                    bs_price(spot-h, strike, tte, iv, rate, "PE")) / (2*h)
        gamma    = (bs_price(spot+h, strike, tte, iv, rate, "CE") -
                    2*bs_price(spot, strike, tte, iv, rate, "CE") +
                    bs_price(spot-h, strike, tte, iv, rate, "CE")) / h**2

        return jsonify({
            "ce_price": round(ce, 2), "pe_price": round(pe, 2),
            "delta_ce": round(delta_ce, 4), "delta_pe": round(delta_pe, 4),
            "gamma":    round(gamma, 6),
            "intrinsic_ce": round(max(spot-strike, 0), 2),
            "intrinsic_pe": round(max(strike-spot, 0), 2),
            "time_value_ce": round(ce - max(spot-strike, 0), 2),
            "time_value_pe": round(pe - max(strike-spot, 0), 2),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─────────────────────────────────────────────────────────────────────────────
# Routes — journal
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/journal")
def get_journal():
    from data import database
    entries = database.get_journal_entries()
    return jsonify({"entries": entries[:200], "total": len(entries)})


# ─────────────────────────────────────────────────────────────────────────────
# Routes — execution (Real / Paper Order Placement)
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/execution/trade_info", methods=["POST"])
def execution_trade_info():
    """
    Given an instrument and direction, calculate suggested SL (swing low/high),
    Target (R:R), Qty, and Risk.
    """
    data = request.get_json(force=True) or {}
    instrument = data.get("instrument", "NIFTY")
    direction  = data.get("direction", "LONG")
    entry      = float(data.get("entry", 0))
    rr         = float(data.get("rr", 2.0))
    
    # Get recent candles to find swing high/low
    if instrument == "BTC":
        candles = live_data.get_btc_candles("1m", limit=30)
    else:
        if _broker:
            df = live_data.get_historical_candles(_broker, NIFTY_TOKEN, "NSE", "ONE_MINUTE")
            candles = df.to_dict("records") if not df.empty else []
        else:
            # Fallback to synthetic if no broker
            candles = _generate_synthetic_ohlcv(30, bar_minutes=1).to_dict("records")

    if direction == "LONG":
        stop = execution.find_recent_swing_low(candles, lookback=20) or (entry * 0.999)
    else:
        stop = execution.find_recent_swing_high(candles, lookback=20) or (entry * 1.001)

    target = execution.calc_target(entry, stop, direction, rr)
    
    # Qty based on risk
    risk_pct = config.DAILY_LOSS_LIMIT_PCT / 3  # risk 1/3 of daily limit per trade
    qty = execution.calc_qty_from_risk(config.CAPITAL, risk_pct, entry, stop)
    
    return jsonify({
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "qty": qty,
        "risk_rs": round(abs(entry - stop) * qty, 2),
        "reward_rs": round(abs(target - entry) * qty, 2),
    })

@app.route("/api/execution/place_order", methods=["POST"])
def execution_place_order():
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "paper") # "paper" or "real"
    
    instrument = data.get("instrument", "NIFTY")
    direction  = data.get("direction", "LONG")
    entry      = float(data.get("entry", 0))
    stop       = float(data.get("stop", 0))
    target     = float(data.get("target", 0))
    qty        = int(data.get("qty", 1))
    rr         = float(data.get("rr", 2.0))
    
    order_id = f"PAPER_{int(time.time())}"
    status = "PLACED (PAPER)"
    
    if mode == "real":
        if not _broker:
            return jsonify({"error": "Broker not connected"}), 400
        if instrument == "NIFTY":
            tx_type = "BUY" if direction == "LONG" else "SELL"
            # In a real F&O scenario, we'd trade a specific option or future contract. 
            # For demonstration with LTP, we'll assume a futures contract token if available, or just mock it.
            res = execution.place_order(
                _broker, 
                tradingsymbol="NIFTY", 
                symboltoken=NIFTY_TOKEN, 
                exchange="NSE", 
                transaction_type=tx_type, 
                quantity=qty,
                order_type="MARKET"
            )
            order_id = res.get("order_id", "ERR")
            status = res.get("status", "FAILED")
            if status == "ERROR":
                return jsonify({"error": res.get("message")}), 400
        else:
            return jsonify({"error": "Real trading not supported for BTC yet."}), 400

    execution.log_trade(
        instrument=instrument,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        qty=qty,
        rr=rr,
        order_id=order_id,
        status=status,
        exchange="NSE" if instrument == "NIFTY" else "CRYPTO",
        tradingsymbol=instrument
    )
    
    return jsonify({"status": "success", "order_id": order_id})

@app.route("/api/execution/positions")
def execution_positions():
    trades = execution.get_all_trades()
    
    # Update real-time PnL for open trades
    for t in trades["open"]:
        if t["instrument"] == "NIFTY":
            ltp = live_data.get_nifty_ltp().get("ltp") or t["entry"]
        else:
            ltp = live_data.get_btc_price().get("price_usd") or t["entry"]
            
        if t["direction"] == "LONG":
            t["pnl"] = round((ltp - t["entry"]) * t["qty"], 2)
        else:
            t["pnl"] = round((t["entry"] - ltp) * t["qty"], 2)
            
        t["current_price"] = round(ltp, 2)
        
    return jsonify(trades)

@app.route("/api/execution/close_trade", methods=["POST"])
def execution_close_trade():
    data = request.get_json(force=True) or {}
    trade_id = data.get("id")
    
    # Find current price
    trades = execution.get_all_trades()
    trade = next((t for t in trades["open"] if t["id"] == trade_id), None)
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
        
    if trade["instrument"] == "NIFTY":
        ltp = live_data.get_nifty_ltp().get("ltp") or trade["entry"]
    else:
        ltp = live_data.get_btc_price().get("price_usd") or trade["entry"]
        
    execution.close_trade(trade_id, ltp)
    return jsonify({"status": "success"})


# ─────────────────────────────────────────────────────────────────────────────
# Routes — broker status & config
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/broker/status")
def broker_status():
    return jsonify({
        "connected": _broker is not None,
        "error": _broker_error,
        "credentials_set": config.ANGEL_API_KEY != "SET_ME",
    })


@app.route("/api/config")
def get_config():
    return jsonify({
        "mode": config.MODE,
        "underlying": config.UNDERLYING,
        "capital": config.CAPITAL,
        "max_lots": config.MAX_LOTS_PER_TRADE,
        "max_positions": config.MAX_CONCURRENT_POSITIONS,
        "daily_loss_limit_pct": config.DAILY_LOSS_LIMIT_PCT * 100,
        "zscore_window": config.ZSCORE_WINDOW,
        "zscore_entry": config.ZSCORE_ENTRY_THRESHOLD,
        "zscore_exit":  config.ZSCORE_EXIT_THRESHOLD,
        "strike_step": config.STRIKE_STEP,
        "square_off_time": config.SQUARE_OFF_TIME,
        "assumed_iv": config.ASSUMED_IV * 100,
        "risk_free_rate": config.RISK_FREE_RATE * 100,
        "train_test_split_date": config.TRAIN_TEST_SPLIT_DATE,
        "active_strategy": config.ACTIVE_STRATEGY,
        "pattern_ema": config.PATTERN_EMA_LENGTH,
        "pattern_rsi": config.PATTERN_RSI_LENGTH,
        "pattern_pivot_len": config.PATTERN_PIVOT_LEN,
        "pattern_rsi_oversold": config.PATTERN_RSI_OVERSOLD,
        "pattern_rsi_overbought": config.PATTERN_RSI_OVERBOUGHT,
        "brokerage_per_order": config.BROKERAGE_PER_ORDER,
        "stt_options_pct": config.STT_OPTIONS_PCT * 100,
        "slippage_pct": config.ASSUMED_SLIPPAGE_PCT * 100,
        "lot_size": {"NIFTY": 65, "BANKNIFTY": 30}.get(config.UNDERLYING, 65),
        "nifty_token": NIFTY_TOKEN,
        "bnifty_token": BNIFTY_TOKEN,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────
def _now():
    return datetime.now().strftime("%H:%M:%S")


if __name__ == "__main__":
    print("=" * 60)
    print("  QuantEdge Trading Dashboard — Real Data Edition")
    print("  http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, port=5000, threaded=True)
