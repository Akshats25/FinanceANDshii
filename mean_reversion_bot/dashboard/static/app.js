/* ============================================================
   QuantEdge Dashboard — Real Data Edition
   ============================================================ */

Chart.defaults.color         = '#8a9bbf';
Chart.defaults.borderColor   = '#242e48';
Chart.defaults.font.family   = "'Inter', sans-serif";

// ---- Chart instances ----
let equityChart = null, dailyPnlChart = null;
let zscoreChart = null, priceSignalChart = null;
let patternPriceChart = null, rsiChart = null;
let ivSurfaceChart = null;
let btcPriceChart = null, btcZscoreChart = null;
let niftySparkline = null;

// ---- Cached live prices ----
let liveNiftyLtp = null, liveBtcUsd = null;

// ---- Utilities ----
const fmt = (n, d = 2) => (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d);
const fmtINR = n => {
  if (n == null || isNaN(n)) return '₹—';
  const sign = n > 0 ? '+' : '';
  return `${sign}₹${Math.abs(n).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
};
const fmtINRPlain = n => {
  if (n == null || isNaN(n)) return '₹—';
  return `₹${Number(n).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
};
const fmtUSD = n => {
  if (n == null || isNaN(n)) return '$—';
  return `$${Number(n).toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0})}`;
};
const colorClass = n => n > 0 ? 'td-positive' : n < 0 ? 'td-negative' : '';

// ================================================================
// CLOCK
// ================================================================
function updateClock() {
  const now = new Date();
  document.getElementById('sidebar-time').textContent =
    now.toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
}
setInterval(updateClock, 1000);
updateClock();

// ================================================================
// NAVIGATION
// ================================================================
const breadcrumbMap = {
  dashboard: 'Dashboard', btc: '₿ BTC Live', backtest: 'Backtest Lab',
  paper: 'Paper Trading', signals: 'Signal Monitor', options: 'Option Chain',
  pricer: 'Option Pricer', journal: 'Trade Journal', config: 'Configuration',
};

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  document.getElementById('breadcrumb').textContent = breadcrumbMap[name] || name;

  if (name === 'dashboard') loadDashboard();
  if (name === 'config')    loadConfig();
  if (name === 'journal')   loadJournal();
  if (name === 'signals')   { execUpdateChart(); execLoadPositions(); }
  if (name === 'btc')       { loadBtcChart(); loadBtcKpis(); }
  if (name === 'options')   loadOptionChain();
  if (name === 'backtest')  checkBrokerForBacktest();
}

// ================================================================
// LIVE TICKER — polls /api/market/ticker every 10 s
// ================================================================
async function fetchTicker() {
  try {
    const d = await fetch('/api/market/ticker').then(r => r.json());

    // Update live cache
    liveNiftyLtp = d.nifty_ltp;
    liveBtcUsd   = d.btc_usd;

    // NIFTY chip
    if (d.nifty_ltp) {
      document.getElementById('nifty-val').textContent = fmtINRPlain(d.nifty_ltp).replace('₹', '');
      document.getElementById('chip-nifty').title = `Live from Angel One`;
    } else {
      document.getElementById('nifty-val').textContent = 'N/A';
    }

    // BANKNIFTY chip
    if (d.bnifty_ltp) {
      document.getElementById('bnifty-val').textContent = Number(d.bnifty_ltp).toLocaleString('en-IN', {maximumFractionDigits: 2});
    } else {
      document.getElementById('bnifty-val').textContent = 'N/A';
    }

    // BTC chip
    if (d.btc_usd) {
      document.getElementById('btc-val').textContent = fmtUSD(d.btc_usd);
      const chgEl = document.getElementById('btc-chg');
      const chg = d.btc_chg24;
      chgEl.textContent = chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '';
      chgEl.className = 'chip-chg ' + (chg >= 0 ? 'up' : 'down');
    }

    // Broker status
    const brokerLine = document.getElementById('broker-status-line');
    if (d.broker_ok) {
      brokerLine.textContent = '● Connected';
      brokerLine.className   = 'broker-status-line ok';
      document.getElementById('broker-banner')?.style.setProperty('display', 'none');
    } else {
      brokerLine.textContent = d.broker_error === 'credentials_not_set'
        ? '○ No credentials'
        : '● Error: ' + (d.broker_error || 'unknown');
      brokerLine.className   = 'broker-status-line fail';
      const banner = document.getElementById('broker-banner');
      if (banner) banner.style.display = 'flex';
    }

    // Kill switch chip
    updateKsChip(false);

    // KPI on dashboard: BTC
    if (d.btc_usd) {
      document.getElementById('kpi-btc').textContent = fmtUSD(d.btc_usd);
    }

    // NIFTY sparkline LTP label
    const ltpBadge = document.getElementById('nifty-sparkline-ltp');
    if (ltpBadge) ltpBadge.textContent = d.nifty_ltp ? fmtINRPlain(d.nifty_ltp) : 'N/A';

    // BTC vol
    const volBadge = document.getElementById('btc-vol-24');
    if (volBadge && d.btc_vol24) {
      volBadge.textContent = '$' + (d.btc_vol24 / 1e9).toFixed(1) + 'B';
    }

  } catch (e) {
    console.warn('Ticker fetch failed:', e);
  }
}

function updateKsChip(tripped) {
  const chip = document.getElementById('ks-chip');
  const dot  = chip?.querySelector('.ks-dot');
  if (!chip) return;
  if (tripped) {
    chip.classList.add('tripped');
    dot.className = 'ks-dot tripped';
    chip.querySelector('span:last-child').textContent = 'TRIPPED';
  } else {
    chip.classList.remove('tripped');
    dot.className = 'ks-dot safe';
    chip.querySelector('span:last-child').textContent = 'Safe';
  }
}

// Fetch price history for sparklines
async function fetchPriceHistory() {
  try {
    const d = await fetch('/api/market/price_history').then(r => r.json());

    // NIFTY sparkline
    const niftyData = (d.nifty || []);
    if (niftyData.length > 1) {
      if (niftySparkline) niftySparkline.destroy();
      niftySparkline = new Chart(document.getElementById('nifty-sparkline'), {
        type: 'line',
        data: {
          labels: niftyData.map(p => p.ts),
          datasets: [{
            data: niftyData.map(p => p.price),
            borderColor: '#4f8ef7',
            backgroundColor: 'rgba(79,142,247,0.08)',
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 0,
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            x: { display: false },
            y: { grid: { color: '#242e48' }, ticks: { callback: v => '₹' + Math.round(v/100)*100 } },
          },
        },
      });
    }
  } catch (e) {}
}

// Start polling
setInterval(fetchTicker, 10000);
fetchTicker();
setInterval(fetchPriceHistory, 15000);
fetchPriceHistory();

// ================================================================
// DASHBOARD
// ================================================================
async function loadDashboard() {
  try {
    const d = await fetch('/api/risk').then(r => r.json());

    document.getElementById('kpi-capital').textContent   = fmtINRPlain(d.capital);
    const pnlEl = document.getElementById('kpi-pnl');
    pnlEl.textContent = fmtINR(d.daily_pnl);
    pnlEl.style.color = d.daily_pnl >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('kpi-positions').textContent = `${d.open_positions} / ${d.max_positions}`;
    const ksEl = document.getElementById('kpi-ks');
    ksEl.textContent = d.kill_switch ? '⚠ TRIPPED' : 'Safe';
    ksEl.style.color = d.kill_switch ? 'var(--red)' : 'var(--green)';

    const pct = Math.min(Math.abs(d.pnl_pct / d.limit_pct) * 100, 100);
    const fill = document.getElementById('risk-bar-fill');
    fill.style.width = pct + '%';
    pct > 70 ? fill.classList.add('danger') : fill.classList.remove('danger');
    document.getElementById('risk-bar-pct').textContent  = `${pct.toFixed(0)}% of daily limit used`;
    document.getElementById('risk-loss-val').textContent = fmtINR(d.daily_pnl);
    document.getElementById('risk-limit-val').textContent = fmtINRPlain(d.daily_loss_limit);
    document.getElementById('risk-can-trade').textContent = d.can_trade ? 'Yes' : 'No';
    document.getElementById('risk-can-trade').className   = 'pill ' + (d.can_trade ? 'green' : 'red');
    document.getElementById('risk-max-conc').textContent  = d.max_positions;
    document.getElementById('risk-ks-pill').textContent   = d.kill_switch ? '⚠ TRIPPED' : 'Safe';
    document.getElementById('risk-ks-pill').className     = 'pill ' + (d.kill_switch ? 'red' : 'green');

    updateKsChip(d.kill_switch);
  } catch (e) {}
}

async function runQuickBacktest() {
  const el = document.getElementById('quick-backtest-result');
  el.innerHTML = '<div class="loading-state"><div class="spinner"></div> Running...</div>';
  const res = await fetch('/api/backtest/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ strategy: 'mean_reversion', n_bars: 390, base_price: liveNiftyLtp || 22000 }),
  });
  const d = await res.json();
  const m = d.metrics || {};
  const pnlColor = (m.total_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
  el.innerHTML = `
    <div class="quick-result-grid">
      <div class="quick-metric"><div class="quick-metric-label">Trades</div><div class="quick-metric-value">${m.trades || 0}</div></div>
      <div class="quick-metric"><div class="quick-metric-label">Total P&L</div><div class="quick-metric-value" style="color:${pnlColor}">${fmtINR(m.total_pnl)}</div></div>
      <div class="quick-metric"><div class="quick-metric-label">Win Rate</div><div class="quick-metric-value">${m.win_rate != null ? (m.win_rate*100).toFixed(1)+'%' : '—'}</div></div>
      <div class="quick-metric"><div class="quick-metric-label">Sharpe</div><div class="quick-metric-value">${fmt(m.sharpe_approx)}</div></div>
      <div class="quick-metric"><div class="quick-metric-label">Max DD</div><div class="quick-metric-value" style="color:var(--red)">${fmt(m.max_drawdown_pct)}%</div></div>
      <div class="quick-metric"><div class="quick-metric-label">Profit Factor</div><div class="quick-metric-value">${fmt(m.profit_factor)}</div></div>
    </div>
    <p style="margin-top:10px;font-size:11px;color:var(--text-muted)">⚠ Synthetic data + B-S pricing. Signal logic check only.</p>`;
}

function resetKillSwitch() {
  fetch('/api/risk/reset_kill_switch', { method: 'POST' }).then(() => loadDashboard());
}

// ================================================================
// BTC LIVE PAGE
// ================================================================
async function loadBtcKpis() {
  try {
    const d = await fetch('/api/market/ticker').then(r => r.json());
    document.getElementById('btc-kpi-usd').textContent  = d.btc_usd  ? fmtUSD(d.btc_usd) : 'N/A';
    document.getElementById('btc-kpi-inr').textContent  = d.btc_inr  ? fmtINRPlain(d.btc_inr) : 'N/A';
    const chgEl = document.getElementById('btc-kpi-chg');
    const chg = d.btc_chg24;
    chgEl.textContent  = chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : 'N/A';
    chgEl.style.color  = chg >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('btc-kpi-vol').textContent  = d.btc_vol24 ? '$' + (d.btc_vol24 / 1e9).toFixed(2) + 'B' : 'N/A';
  } catch (e) {}
}

async function loadBtcChart() {
  const interval = document.getElementById('btc-interval')?.value || '5m';
  try {
    const data = await fetch(`/api/market/btc_candles?interval=${interval}&limit=100`).then(r => r.json());
    if (!data.length || data[0].error) return;

    if (btcPriceChart) btcPriceChart.destroy();
    btcPriceChart = new Chart(document.getElementById('btc-price-chart'), {
      type: 'line',
      data: {
        labels: data.map(d => d.timestamp.slice(-5)),
        datasets: [
          { label: 'Close', data: data.map(d => d.close), borderColor: '#14b8a6', borderWidth: 2, fill: false, tension: 0.3, pointRadius: 0 },
          { label: 'High',  data: data.map(d => d.high),  borderColor: 'rgba(34,197,94,0.4)', borderWidth: 1, fill: false, tension: 0.3, pointRadius: 0 },
          { label: 'Low',   data: data.map(d => d.low),   borderColor: 'rgba(239,68,68,0.4)',  borderWidth: 1, fill: false, tension: 0.3, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { boxWidth: 10 } }, tooltip: { callbacks: { label: ctx => `$${ctx.parsed.y.toFixed(0)}` } } },
        scales: {
          x: { ticks: { maxTicksLimit: 10 }, grid: { color: '#242e48' } },
          y: { grid: { color: '#242e48' }, ticks: { callback: v => '$' + (v/1000).toFixed(0) + 'k' } },
        },
      },
    });
  } catch (e) { console.warn('BTC chart failed:', e); }
}

async function loadBtcZscore() {
  const window = document.getElementById('btc-zscore-window')?.value || 20;
  const interval = document.getElementById('btc-interval')?.value || '5m';
  try {
    const data = await fetch(`/api/signals/btc_live?interval=${interval}&window=${window}`).then(r => r.json());
    if (!data.length || data[0].error) return;

    if (btcZscoreChart) btcZscoreChart.destroy();
    btcZscoreChart = new Chart(document.getElementById('btc-zscore-chart'), {
      type: 'line',
      data: {
        labels: data.map(d => d.timestamp.slice(-5)),
        datasets: [
          { label: 'Z-Score', data: data.map(d => d.zscore), borderColor: '#f59e0b', borderWidth: 2, fill: false, tension: 0.3, pointRadius: 0 },
          { label: '+2σ', data: data.map(() => 2),  borderColor: 'rgba(239,68,68,0.5)', borderDash: [4,4], borderWidth: 1, pointRadius: 0, fill: false },
          { label: '-2σ', data: data.map(() => -2), borderColor: 'rgba(34,197,94,0.5)',  borderDash: [4,4], borderWidth: 1, pointRadius: 0, fill: false },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { labels: { boxWidth: 10 } } },
        scales: {
          x: { display: false },
          y: { grid: { color: '#242e48' }, min: -4, max: 4 },
        },
      },
    });
  } catch (e) { console.warn('BTC z-score failed:', e); }
}

// Auto-refresh BTC every 30 s when on BTC page
setInterval(() => {
  if (document.getElementById('page-btc')?.classList.contains('active')) {
    loadBtcChart();
    loadBtcKpis();
  }
}, 30000);

// ================================================================
// BACKTEST LAB
// ================================================================
function switchBtTab(tab) {
  ['synthetic', 'upload', 'live'].forEach(t => {
    document.getElementById('bt-panel-' + t).classList.remove('show');
    document.getElementById('tab-' + t).classList.remove('active');
  });
  document.getElementById('bt-panel-' + tab).classList.add('show');
  document.getElementById('tab-' + tab).classList.add('active');
}

// Init the first tab
document.addEventListener('DOMContentLoaded', () => {
  switchBtTab('synthetic');

  // Set default dates for live fetch
  const now = new Date();
  const from = new Date(now - 30 * 24 * 60 * 60 * 1000);
  const toStr  = now.toISOString().slice(0, 16);
  const frStr  = from.toISOString().slice(0, 16);
  const toEl   = document.getElementById('bt-to');
  const fromEl = document.getElementById('bt-from');
  if (toEl)   toEl.value   = toStr;
  if (fromEl) fromEl.value = frStr;

  loadDashboard();
  loadConfig();
});

function checkBrokerForBacktest() {
  fetch('/api/broker/status').then(r => r.json()).then(d => {
    const banner = document.getElementById('bt-broker-banner');
    if (banner) banner.style.display = d.connected ? 'none' : 'flex';
  });
}

async function runFullBacktest(mode) {
  document.getElementById('bt-loading').style.display = 'flex';
  document.getElementById('bt-results').style.display = 'none';
  const btns = ['bt-run-btn', 'bt-upload-btn', 'bt-live-btn'];
  btns.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = true; });

  try {
    let res;
    if (mode === 'synthetic') {
      const strategy   = document.getElementById('bt-strategy').value;
      const instrument = document.getElementById('bt-instrument').value;
      const n_bars     = parseInt(document.getElementById('bt-bars').value);
      const base_price = parseFloat(document.getElementById('bt-price').value);
      res = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy, instrument, n_bars, base_price }),
      });
    } else if (mode === 'upload') {
      const file = document.getElementById('bt-csv-file').files[0];
      if (!file) { alert('Please select a CSV file.'); return; }
      const strategy   = document.getElementById('bt-strategy-upload').value;
      const instrument = document.getElementById('bt-instrument-upload').value;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('strategy', strategy);
      fd.append('instrument', instrument);
      res = await fetch('/api/backtest/upload', { method: 'POST', body: fd });
    } else {
      // live fetch from Angel One or Binance
      const body = {
        strategy:     document.getElementById('bt-strategy-live').value,
        instrument:   document.getElementById('bt-instrument-live').value,
        symbol_token: document.getElementById('bt-token').value,
        exchange:     document.getElementById('bt-exchange').value,
        interval:     document.getElementById('bt-interval').value,
        from_date:    document.getElementById('bt-from').value.replace('T', ' '),
        to_date:      document.getElementById('bt-to').value.replace('T', ' '),
      };
      res = await fetch('/api/backtest/fetch_and_run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    }

    const d = await res.json();
    if (d.error) {
      alert('Backtest error: ' + d.error + (d.problems ? '\n' + d.problems.join('\n') : ''));
      return;
    }
    renderBacktestResults(d);
  } finally {
    document.getElementById('bt-loading').style.display = 'none';
    btns.forEach(id => { const el = document.getElementById(id); if (el) el.disabled = false; });
    document.getElementById('bt-results').style.display = 'block';
  }
}

function renderBacktestResults(d) {
  const m = d.metrics || {};
  document.getElementById('bt-trades').textContent  = m.trades || 0;
  document.getElementById('bt-trade-count').textContent = `${m.trades || 0} trades`;
  const pnlEl = document.getElementById('bt-pnl');
  pnlEl.textContent  = fmtINR(m.total_pnl);
  pnlEl.style.color  = (m.total_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('bt-winrate').textContent = m.win_rate != null ? (m.win_rate*100).toFixed(1)+'%' : '—';
  document.getElementById('bt-dd').textContent      = fmt(m.max_drawdown_pct) + '%';
  document.getElementById('bt-sharpe').textContent  = fmt(m.sharpe_approx);
  document.getElementById('bt-pf').textContent      = fmt(m.profit_factor);

  const srcTag = document.getElementById('bt-data-src');
  if (srcTag) {
    const src = { synthetic: '⚠ Synthetic data + B-S pricer', uploaded_csv: '✓ Real historical CSV data', angel_one_live: '✓ Live Angel One historical data' };
    srcTag.textContent = (src[d.data_source] || d.data_source) + ` | ${d.days_backtested} days | ${d.rows || '—'} bars`;
  }

  const equity = d.equity_curve || [];
  if (equityChart) equityChart.destroy();
  equityChart = new Chart(document.getElementById('equity-chart'), {
    type: 'line',
    data: {
      labels: equity.map((_, i) => i),
      datasets: [{ label: 'Equity (₹)', data: equity, borderColor: '#4f8ef7', backgroundColor: 'rgba(79,142,247,0.08)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0 }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { display: false }, y: { grid: { color: '#242e48' }, ticks: { callback: v => '₹' + (v/1000).toFixed(0) + 'k' } } },
    },
  });

  const daily = d.daily_metrics || [];
  if (dailyPnlChart) dailyPnlChart.destroy();
  dailyPnlChart = new Chart(document.getElementById('daily-pnl-chart'), {
    type: 'bar',
    data: {
      labels: daily.map(r => (r.date || '').slice(5)),
      datasets: [{ label: 'Daily P&L (₹)', data: daily.map(r => r.pnl || 0), backgroundColor: daily.map(r => (r.pnl || 0) >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'), borderRadius: 4 }],
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { grid: { color: '#242e48' } } } },
  });

  const tbody = document.getElementById('bt-trade-body');
  tbody.innerHTML = '';
  (d.trades || []).forEach(t => {
    const pnl = t.pnl || 0;
    const dir = t.direction || '—';
    const dirClass = ['CE','LONG'].includes(dir) ? 'td-ce' : 'td-pe';
    const strike = t.strike || t.entry_price;
    tbody.innerHTML += `<tr>
      <td>${(t.entry_time || '').slice(0,19)}</td>
      <td>${(t.exit_time  || '').slice(0,19)}</td>
      <td class="${dirClass}">${dir}</td>
      <td>${typeof strike === 'number' ? strike.toFixed(0) : strike || '—'}</td>
      <td>${fmt(t.entry_premium || t.entry_price)}</td>
      <td>${fmt(t.exit_premium  || t.exit_price)}</td>
      <td>${t.exit_reason || '—'}</td>
      <td class="${colorClass(pnl)}">${fmtINR(pnl)}</td>
    </tr>`;
  });
}

// ================================================================
// PAPER TRADING
// ================================================================
function startPaper(useReal) {
  fetch('/api/paper/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ use_real: useReal }),
  }).then(r => r.json()).then(d => {
    document.getElementById('paper-dot').className = 'dot running';
    document.getElementById('paper-status-text').textContent = 'Running';
    const badge = document.getElementById('paper-src-badge');
    badge.style.display = 'inline-flex';
    badge.textContent   = d.source || (useReal ? 'real price' : 'simulated');
    document.getElementById('btn-paper-stop').disabled = false;
    document.getElementById('btn-paper-real').disabled = true;
    document.getElementById('btn-paper-sim').disabled  = true;
    refreshPaperStatus();
  });
}

function stopPaper() {
  fetch('/api/paper/stop', { method: 'POST' }).then(() => {
    document.getElementById('paper-dot').className = 'dot';
    document.getElementById('paper-status-text').textContent = 'Stopped';
    document.getElementById('paper-src-badge').style.display = 'none';
    document.getElementById('btn-paper-stop').disabled = true;
    document.getElementById('btn-paper-real').disabled = false;
    document.getElementById('btn-paper-sim').disabled  = false;
  });
}

function resetPaper() {
  fetch('/api/paper/reset', { method: 'POST' }).then(() => {
    document.getElementById('paper-dot').className = 'dot';
    document.getElementById('paper-status-text').textContent = 'Stopped';
    document.getElementById('paper-src-badge').style.display = 'none';
    document.getElementById('btn-paper-stop').disabled = true;
    document.getElementById('btn-paper-real').disabled = false;
    document.getElementById('btn-paper-sim').disabled  = false;
    document.getElementById('paper-pnl').textContent  = '₹0.00';
    document.getElementById('paper-bars').textContent = '0';
    document.getElementById('paper-ks').textContent   = 'Safe';
    document.getElementById('paper-log').innerHTML    = '';
    document.getElementById('paper-trade-display').textContent = 'No open trade';
    document.getElementById('paper-trade-display').className   = 'trade-display empty';
  });
}

function updatePaperUI(d) {
  if (!d) return;
  const pnlEl = document.getElementById('paper-pnl');
  pnlEl.textContent = fmtINR(d.daily_pnl);
  pnlEl.style.color = d.daily_pnl >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('paper-bars').textContent = d.bars_collected;
  const ksEl = document.getElementById('paper-ks');
  ksEl.textContent  = d.kill_switch ? '⚠ TRIPPED' : 'Safe';
  ksEl.style.color  = d.kill_switch ? 'var(--red)' : 'var(--green)';
  updateKsChip(d.kill_switch);

  const tradeEl = document.getElementById('paper-trade-display');
  if (d.open_trade) {
    const t = d.open_trade;
    tradeEl.className = 'trade-display active';
    tradeEl.innerHTML = `
      <div class="cfg-row"><span>Direction</span><span style="color:${t.direction === 'CE' ? 'var(--accent)' : 'var(--purple)'}">${t.direction}</span></div>
      <div class="cfg-row"><span>Strike</span><span>${t.strike}</span></div>
      <div class="cfg-row"><span>Entry Price</span><span>${fmtINRPlain(t.entry_price)}</span></div>
      <div class="cfg-row"><span>Bars Held</span><span>${t.bars_held}</span></div>
      <div class="cfg-row"><span>Entry Time</span><span>${(t.entry_time || '').slice(11,19)}</span></div>`;
  } else {
    tradeEl.className = 'trade-display empty';
    tradeEl.textContent = 'No open trade';
  }

  const logEl = document.getElementById('paper-log');
  const logCount = document.getElementById('paper-log-count');
  const logs = d.log || [];
  if (logCount) logCount.textContent = logs.length + ' events';
  logEl.innerHTML = logs.slice().reverse().map(l => {
    let cls = 'log-line';
    if (l.includes('ENTRY')) cls += ' entry';
    else if (l.includes('🟢 EXIT')) cls += ' exit-win';
    else if (l.includes('🔴 EXIT')) cls += ' exit-loss';
    return `<div class="${cls}">${l}</div>`;
  }).join('');
}

async function refreshPaperStatus() {
  const d = await fetch('/api/paper/status').then(r => r.json());
  updatePaperUI(d);
}

// Auto-tick every 5 s when paper is running
setInterval(async () => {
  try {
    const status = await fetch('/api/paper/status').then(r => r.json());
    if (status.running) {
      const d = await fetch('/api/paper/tick', { method: 'POST' }).then(r => r.json());
      if (document.getElementById('page-paper')?.classList.contains('active')) {
        updatePaperUI(d);
      }
    }
  } catch (e) {}
}, 5000);

// ================================================================
// STRATEGY EXECUTION
// ================================================================
let execPriceChart = null;

async function execUpdateChart() {
  const inst = document.getElementById('exec-instrument').value;
  try {
    let data;
    if (inst === 'BTC') {
      data = await fetch(`/api/market/btc_candles?interval=1m&limit=100`).then(r => r.json());
      document.getElementById('exec-ltp-badge').textContent = `Live: $${fmt(liveBtcUsd)}`;
    } else {
      // For NIFTY we use pattern_demo for now since Angel One 1m historical needs token/exchange args and time
      data = await fetch(`/api/signals/pattern_demo?n=100`).then(r => r.json());
      document.getElementById('exec-ltp-badge').textContent = `Live: ₹${fmt(liveNiftyLtp)}`;
    }

    if (execPriceChart) execPriceChart.destroy();
    
    // Fake signals if BTC for demo, or real signals from pattern_demo
    const chartData = {
      labels: data.map(d => (d.timestamp || '').slice(11,16)),
      datasets: [
        { label: 'Close', data: data.map(d => d.close), borderColor: '#4f8ef7', borderWidth: 1.5, fill: false, tension: 0.2, pointRadius: 0 },
        { label: 'LONG Signal', data: data.map(d => (d.signal === 'LONG' || d.signal === 'CE') ? d.close : null), type: 'scatter', pointBackgroundColor: '#22c55e', pointRadius: 7, pointStyle: 'triangle' },
        { label: 'SHORT Signal', data: data.map(d => (d.signal === 'SHORT' || d.signal === 'PE') ? d.close : null), type: 'scatter', pointBackgroundColor: '#ef4444', pointRadius: 7, pointStyle: 'triangle', rotation: 180 },
      ],
    };

    execPriceChart = new Chart(document.getElementById('exec-price-chart'), {
      type: 'line',
      data: chartData,
      options: { responsive: true, plugins: { legend: { labels: { boxWidth: 10 } } }, scales: { x: { display: true }, y: { grid: { color: '#242e48' } } } },
    });

    // Auto-fill entry if there's a recent close
    if (data.length > 0) {
      const last = data[data.length - 1];
      document.getElementById('exec-entry').value = last.close;
      
      // Look for last signal
      let lastSig = null;
      for (let i = data.length - 1; i >= 0; i--) {
        if (data[i].signal) { lastSig = data[i].signal; break; }
      }
      
      const sigBadge = document.getElementById('exec-signal-badge');
      if (lastSig) {
        sigBadge.textContent = 'Active Signal: ' + lastSig;
        sigBadge.className = 'badge ' + (lastSig === 'LONG' || lastSig === 'CE' ? 'green' : 'red');
        document.getElementById('exec-direction').value = (lastSig === 'LONG' || lastSig === 'CE') ? 'LONG' : 'SHORT';
      } else {
        sigBadge.textContent = 'No Signal';
        sigBadge.className = 'badge';
      }
      
      execRecalcTrade();
    }
  } catch (e) { console.warn('Exec chart failed:', e); }
}

async function execRecalcTrade() {
  const entry = parseFloat(document.getElementById('exec-entry').value);
  if (!entry || isNaN(entry)) return;
  
  const inst = document.getElementById('exec-instrument').value;
  const dir  = document.getElementById('exec-direction').value;
  const rr   = parseFloat(document.getElementById('exec-rr').value) || 2;
  
  const res = await fetch('/api/execution/trade_info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instrument: inst, direction: dir, entry: entry, rr: rr })
  });
  
  const d = await res.json();
  document.getElementById('exec-sl').value = d.stop;
  document.getElementById('exec-target').value = d.target;
  document.getElementById('exec-qty').value = d.qty;
  
  document.getElementById('exec-risk-val').textContent = inst === 'BTC' ? fmtUSD(d.risk_rs) : fmtINR(d.risk_rs);
  document.getElementById('exec-reward-val').textContent = inst === 'BTC' ? fmtUSD(d.reward_rs) : fmtINR(d.reward_rs);
}

function execUpdateRiskReward() {
  const entry = parseFloat(document.getElementById('exec-entry').value);
  const sl    = parseFloat(document.getElementById('exec-sl').value);
  const rr    = parseFloat(document.getElementById('exec-rr').value) || 2;
  const qty   = parseFloat(document.getElementById('exec-qty').value) || 1;
  const dir   = document.getElementById('exec-direction').value;
  
  if (isNaN(entry) || isNaN(sl)) return;
  
  const riskPts = Math.abs(entry - sl);
  const target = dir === 'LONG' ? entry + (rr * riskPts) : entry - (rr * riskPts);
  document.getElementById('exec-target').value = target.toFixed(2);
  
  const inst = document.getElementById('exec-instrument').value;
  document.getElementById('exec-risk-val').textContent = inst === 'BTC' ? fmtUSD(riskPts * qty) : fmtINR(riskPts * qty);
  document.getElementById('exec-reward-val').textContent = inst === 'BTC' ? fmtUSD(riskPts * rr * qty) : fmtINR(riskPts * rr * qty);
}

async function execPlaceOrder() {
  const req = {
    instrument: document.getElementById('exec-instrument').value,
    mode:       document.getElementById('exec-mode').value,
    direction:  document.getElementById('exec-direction').value,
    entry:      parseFloat(document.getElementById('exec-entry').value),
    stop:       parseFloat(document.getElementById('exec-sl').value),
    target:     parseFloat(document.getElementById('exec-target').value),
    qty:        parseInt(document.getElementById('exec-qty').value),
    rr:         parseFloat(document.getElementById('exec-rr').value),
  };
  
  const res = await fetch('/api/execution/place_order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req)
  });
  
  const d = await res.json();
  if (d.error) {
    alert("Order Failed: " + d.error);
  } else {
    alert("Order Placed! ID: " + d.order_id);
    execLoadPositions();
  }
}

async function execLoadPositions() {
  const res = await fetch('/api/execution/positions');
  const d = await res.json();
  
  const tbody = document.getElementById('exec-positions-body');
  if (!tbody) return;
  tbody.innerHTML = '';
  
  const all = [...d.open, ...d.closed];
  if (all.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center">No trades today</td></tr>';
    return;
  }
  
  all.forEach(t => {
    const isClosed = t.closed;
    const isNifty = t.instrument === 'NIFTY';
    const fmtMoney = isNifty ? fmtINR : fmtUSD;
    
    tbody.innerHTML += `
      <tr>
        <td>${t.id} <br><small style="color:var(--text-muted)">${t.time.slice(11)}</small></td>
        <td>${t.instrument} ${isClosed ? '' : '<span class="badge blue">OPEN</span>'}</td>
        <td class="${t.direction === 'LONG' ? 'td-ce' : 'td-pe'}">${t.direction}</td>
        <td>${t.qty}</td>
        <td>${fmt(t.entry)}</td>
        <td>${fmt(isClosed ? t.exit : t.current_price)}</td>
        <td>${fmt(t.stop)} / ${fmt(t.target)}</td>
        <td class="${colorClass(t.pnl)} font-mono">${fmtMoney(t.pnl)}</td>
        <td>
          ${!isClosed ? `<button class="btn btn-primary btn-sm" onclick="execCloseTrade(${t.id})">Close</button>` : '—'}
        </td>
      </tr>
    `;
  });
}

async function execCloseTrade(id) {
  if(!confirm('Close this trade at market price?')) return;
  await fetch('/api/execution/close_trade', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id })
  });
  execLoadPositions();
}

// Ensure execution page initializes correctly
document.addEventListener('DOMContentLoaded', () => {
  setInterval(() => {
    if (document.getElementById('page-signals')?.classList.contains('active')) {
      execLoadPositions();
    }
  }, 5000);
});

// ================================================================
// OPTION CHAIN
// ================================================================
async function loadOptionChain() {
  const underlying = document.getElementById('oc-underlying')?.value || 'NIFTY';
  const expiry     = document.getElementById('oc-expiry')?.value    || '';

  document.getElementById('oc-loading').style.display = 'flex';
  document.getElementById('oc-error').style.display   = 'none';
  document.getElementById('oc-body').innerHTML        = '';

  try {
    const url = `/api/options/chain?underlying=${underlying}` + (expiry ? `&expiry=${expiry}` : '');
    const d   = await fetch(url).then(r => r.json());

    document.getElementById('oc-loading').style.display = 'none';

    if (!d.chain || d.chain[0]?.error) {
      const errEl = document.getElementById('oc-error');
      errEl.style.display = 'flex';
      errEl.textContent   = '⚠ ' + (d.chain?.[0]?.error || 'Failed to load option chain. Check broker connection.');
      return;
    }

    document.getElementById('oc-expiry-badge').textContent = d.nearest_expiry || expiry || '—';
    document.getElementById('oc-info').textContent = `Underlying: ${d.underlying} | Spot: ${fmtINRPlain(d.spot)} | ${d.chain.length} strikes`;

    const tbody = document.getElementById('oc-body');
    tbody.innerHTML = d.chain.map(row => `
      <tr class="${row.atm ? 'atm-row' : ''}">
        <td class="${row.atm ? 'td-ce' : ''}">${row.ce_symbol || '—'}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted)">${row.ce_token || '—'}</td>
        <td class="strike-col">${row.strike?.toFixed(0)}${row.atm ? ' ★' : ''}</td>
        <td class="${row.atm ? 'td-pe' : ''}">${row.pe_symbol || '—'}</td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted)">${row.pe_token || '—'}</td>
      </tr>
    `).join('');
  } catch (e) {
    document.getElementById('oc-loading').style.display = 'none';
    const errEl = document.getElementById('oc-error');
    errEl.style.display = 'flex';
    errEl.textContent   = '⚠ Network error: ' + e.message;
  }
}

// ================================================================
// OPTION PRICER
// ================================================================
function autofillPricerSpot() {
  if (liveNiftyLtp) {
    document.getElementById('pr-spot').value = Math.round(liveNiftyLtp);
    document.getElementById('pr-strike').value = Math.round(liveNiftyLtp / 50) * 50;
  } else {
    alert('Live NIFTY price not available. Please check broker connection.');
  }
}

async function runPricer() {
  const spot   = parseFloat(document.getElementById('pr-spot').value);
  const strike = parseFloat(document.getElementById('pr-strike').value);
  const tte    = parseFloat(document.getElementById('pr-tte').value);
  const iv     = parseFloat(document.getElementById('pr-iv').value) / 100;
  const rate   = parseFloat(document.getElementById('pr-rate').value) / 100;

  const res = await fetch('/api/pricer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ spot, strike, tte_days: tte, iv, rate }),
  });
  const d = await res.json();
  if (d.error) { alert('Error: ' + d.error); return; }

  document.getElementById('pricer-output').innerHTML = `
    <div class="pricer-grid">
      <div class="pricer-item"><div class="pricer-item-label">CE Premium</div><div class="pricer-item-value ce">₹${fmt(d.ce_price)}</div><div class="pricer-item-sub">Intrinsic ₹${fmt(d.intrinsic_ce)} | Time ₹${fmt(d.time_value_ce)}</div></div>
      <div class="pricer-item"><div class="pricer-item-label">PE Premium</div><div class="pricer-item-value pe">₹${fmt(d.pe_price)}</div><div class="pricer-item-sub">Intrinsic ₹${fmt(d.intrinsic_pe)} | Time ₹${fmt(d.time_value_pe)}</div></div>
      <div class="pricer-item"><div class="pricer-item-label">Delta (CE / PE)</div><div class="pricer-item-value" style="font-size:16px">${fmt(d.delta_ce,4)} / ${fmt(d.delta_pe,4)}</div></div>
      <div class="pricer-item"><div class="pricer-item-label">Gamma</div><div class="pricer-item-value" style="font-size:16px">${fmt(d.gamma,6)}</div></div>
      <div class="pricer-item"><div class="pricer-item-label">Moneyness</div><div class="pricer-item-value" style="font-size:16px">${spot > strike ? 'ITM ↑' : spot < strike ? 'OTM ↓' : 'ATM ●'}</div></div>
      <div class="pricer-item"><div class="pricer-item-label">Input IV / Rate</div><div class="pricer-item-value" style="font-size:16px">${(iv*100).toFixed(1)}% / ${(rate*100).toFixed(2)}%</div></div>
    </div>
    <p style="margin-top:12px;font-size:11px;color:var(--text-muted)">Black-Scholes (European, flat IV, no skew). Intraday index approximation.</p>`;
}

async function buildIVSurface() {
  const spot = parseFloat(document.getElementById('pr-spot').value) || 22000;
  const tte  = parseFloat(document.getElementById('pr-tte').value)  || 3;
  const rate = parseFloat(document.getElementById('pr-rate').value) / 100 || 0.065;
  const strikes = [], cePrices = [], pePrices = [];
  const step = 100;

  for (let offset = -1000; offset <= 1000; offset += step) {
    const k = spot + offset;
    strikes.push(k);
    const r = await fetch('/api/pricer', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({spot, strike: k, tte_days: tte, iv: 0.14, rate}) });
    const d = await r.json();
    cePrices.push(d.ce_price);
    pePrices.push(d.pe_price);
  }

  if (ivSurfaceChart) ivSurfaceChart.destroy();
  ivSurfaceChart = new Chart(document.getElementById('iv-surface-chart'), {
    type: 'line',
    data: {
      labels: strikes.map(k => k.toFixed(0)),
      datasets: [
        { label: 'CE', data: cePrices, borderColor: '#4f8ef7', backgroundColor: 'rgba(79,142,247,0.1)', fill: true, tension: 0.4, pointRadius: 3 },
        { label: 'PE', data: pePrices, borderColor: '#a855f7', backgroundColor: 'rgba(168,85,247,0.1)',  fill: true, tension: 0.4, pointRadius: 3 },
      ],
    },
    options: { responsive: true, plugins: { legend: { labels: { boxWidth: 10 } } }, scales: { x: { title: { display: true, text: 'Strike' }, grid: { color: '#242e48' } }, y: { title: { display: true, text: 'Premium (₹)' }, grid: { color: '#242e48' } } } },
  });
}

// ================================================================
// JOURNAL
// ================================================================
async function loadJournal() {
  const d = await fetch('/api/journal').then(r => r.json());
  const entries = d.entries || [];
  const countEl = document.getElementById('journal-count');
  if (countEl) countEl.textContent = d.total + ' entries';

  if (!entries.length) {
    document.getElementById('journal-empty').style.display = 'block';
    document.getElementById('journal-table-wrap').style.display = 'none';
  } else {
    document.getElementById('journal-empty').style.display = 'none';
    document.getElementById('journal-table-wrap').style.display = 'block';
    document.getElementById('journal-body').innerHTML = entries.map(e => `
      <tr>
        <td>${e.open_time}</td>
        <td><span class="badge blue">${e.strategy}</span></td>
        <td>${e.instrument}</td>
        <td class="${['CE','LONG'].includes(e.direction) ? 'td-ce' : 'td-pe'}">${e.direction}</td>
        <td>${e.qty}</td>
        <td>${fmt(e.entry)}</td>
        <td>${e.exit ? fmt(e.exit) : '—'}</td>
        <td class="${colorClass(e.pnl)}">${e.pnl != null ? fmtINR(e.pnl) : '—'}</td>
        <td><span class="badge ${e.status === 'OPEN' ? 'blue' : ''}">${e.status}</span></td>
      </tr>`).join('');
  }
}

// ================================================================
// CONFIG
// ================================================================
async function loadConfig() {
  try {
    const d = await fetch('/api/config').then(r => r.json());
    document.getElementById('mode-badge').textContent = (d.mode || 'BACKTEST').toUpperCase();

    renderCfg('cfg-instrument', [
      ['Mode', d.mode], ['Underlying', d.underlying], ['Exchange', 'NFO'],
      ['Strike Step', '₹' + d.strike_step], ['Active Strategy', d.active_strategy],
    ]);
    renderCfg('cfg-risk', [
      ['Capital', fmtINRPlain(d.capital)],
      ['Max Lots / Trade', d.max_lots], ['Max Concurrent', d.max_positions],
      ['Daily Loss Limit', d.daily_loss_limit_pct + '%'], ['Stop Loss / Trade', '35%'],
      ['Target / Trade', '50%'], ['Square-off', d.square_off_time],
    ]);
    renderCfg('cfg-mr', [
      ['Z-score Window', d.zscore_window + ' bars'],
      ['Entry Threshold', d.zscore_entry + 'σ'], ['Exit Threshold', d.zscore_exit + 'σ'],
      ['Assumed IV', d.assumed_iv + '%'], ['Risk-Free Rate', d.risk_free_rate + '%'],
      ['Bar Interval', 'FIVE_MINUTE'],
    ]);
    renderCfg('cfg-pattern', [
      ['EMA Length', d.pattern_ema], ['RSI Length', d.pattern_rsi],
      ['Pivot Length', d.pattern_pivot_len], ['RSI Oversold', d.pattern_rsi_oversold],
      ['RSI Overbought', d.pattern_rsi_overbought],
    ]);
    renderCfg('cfg-costs', [
      ['Brokerage / Order', '₹' + d.brokerage_per_order],
      ['STT (Options)', d.stt_options_pct + '%'],
      ['Slippage', d.slippage_pct + '%'], ['Lot Size', d.lot_size + ' units'],
      ['Train/Test Split', d.train_test_split_date],
    ]);
    renderCfg('cfg-broker', [
      ['NIFTY Token', d.nifty_token], ['BANKNIFTY Token', d.bnifty_token],
      ['API Key', '••••• (config.py)'], ['TOTP Secret', '••••• (config.py)'],
      ['SDK', 'smartapi-python'], ['Static IP', 'Required (SEBI 2026)'],
    ]);
  } catch (e) {}
}

function renderCfg(id, rows) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = rows.map(([k, v]) =>
    `<div class="cfg-row"><span>${k}</span><span>${v}</span></div>`
  ).join('');
}

// ================================================================
// PERIODIC REFRESH
// ================================================================
setInterval(loadDashboard, 10000);
