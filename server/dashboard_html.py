DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>FortyTwo Network: Node Analysis</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Inline SVG favicon: stylized "42" inside an orbital ring with a satellite dot.
     Single source — same SVG renders as the header logo (see <header> below). -->
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><g transform='rotate(-20 32 32)'><circle cx='32' cy='32' r='28' fill='none' stroke='%2360a5fa' stroke-width='2.5'/><circle cx='52' cy='32' r='3' fill='%234ade80'/></g><circle cx='32' cy='32' r='22' fill='%23141414'/><text x='32' y='42' text-anchor='middle' font-family='ui-monospace,monospace' font-weight='700' font-size='26' fill='%23e8e8e8'>42</text></svg>">
<style>
:root { --bg:#0a0a0a; --card:#141414; --text:#e8e8e8; --muted:#888; --green:#4ade80; --red:#f87171; --blue:#60a5fa; --border:#2a2a2a; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 16px; line-height: 1.5; }
.container { max-width: 1200px; margin: 0 auto; }
header { margin-bottom: 24px; }
h1 { font-size: 22px; font-weight: 600; }
.meta { color: var(--muted); font-size: 13px; margin-top: 4px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h2 { font-size: 11px; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; letter-spacing: 0.5px; font-weight: 600; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 5px 0; font-size: 14px; gap: 12px; }
.row .label { color: var(--muted); flex-shrink: 0; }
.row .value { font-family: ui-monospace, "SF Mono", Menlo, monospace; text-align: right; word-break: break-all; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge.ok { background: rgba(74,222,128,0.15); color: var(--green); }
.badge.down { background: rgba(248,113,113,0.15); color: var(--red); }
.chart-wrap { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.chart-wrap canvas { max-height: 240px; }
.rounds-list { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
td { padding: 8px; font-family: ui-monospace, "SF Mono", Menlo, monospace; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
.balance-big { font-size: 30px; font-weight: 600; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.balance-reward { color: var(--green); font-size: 13px; margin-top: 6px; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 24px; padding-bottom: 16px; }
a { color: var(--blue); text-decoration: none; }
.section-title { font-size: 11px; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; letter-spacing: 0.5px; font-weight: 600; }
.section-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.section-header .section-title { margin-bottom: 0; }
.toggle-group { display: inline-flex; gap: 4px; }
.toggle-btn { background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 4px 10px; border-radius: 4px; font-size: 11px; cursor: pointer; font-family: inherit; text-transform: uppercase; letter-spacing: 0.5px; }
.toggle-btn:hover { color: var(--text); }
.toggle-btn.active { background: var(--blue); color: #000; border-color: var(--blue); }
.log-view { white-space: pre-wrap; max-height: 400px; overflow-y: auto; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11px; color: var(--muted); background: var(--bg); padding: 12px; border-radius: 6px; margin: 0; word-break: break-all; }
.err-msg { color: var(--red); word-break: break-word; white-space: pre-wrap; font-size: 12px; }
/* Per-card kebab (hamburger) settings menu. The card sets position:relative
   and the popup floats anchored to the top-right corner. Click the icon to
   open, click outside or the icon again to close. Each card carries its own
   popup so toggles stay scoped to the data they affect. */
.has-settings { position: relative; }
.kebab-btn { background: transparent; border: 1px solid var(--border); color: var(--muted); width: 28px; height: 28px; border-radius: 4px; cursor: pointer; font-size: 14px; line-height: 1; padding: 0; display: inline-flex; align-items: center; justify-content: center; font-family: inherit; }
.kebab-btn:hover { color: var(--text); border-color: var(--muted); }
.kebab-btn.open { background: var(--blue); color: #000; border-color: var(--blue); }
.settings-popup { position: absolute; bottom: 100%; right: 12px; margin-bottom: 8px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; z-index: 10; box-shadow: 0 -4px 16px rgba(0,0,0,0.4); display: flex; flex-direction: column; gap: 10px; min-width: 200px; }
.settings-popup.open-below { bottom: auto; top: 44px; margin-bottom: 0; box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
.settings-popup[hidden] { display: none; }
.settings-popup .pop-row { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
.settings-popup .pop-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
/* FOR Balance card now also hosts the earnings projection so it's taller. */
.balance-card { display: flex; flex-direction: column; }
/* Today card reward-outcome doughnut (FortyTwo brand colors). */
.donut-wrap { position: relative; width: 100%; max-width: 190px; margin: 4px auto 14px; }
.donut-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; }
.donut-pct { font-size: 28px; font-weight: 700; color: var(--text); line-height: 1; }
.donut-cap { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin-top: 3px; }
.donut-legend { display: flex; flex-direction: column; gap: 7px; font-size: 13px; }
.lg-item { display: flex; align-items: center; gap: 8px; }
.lg-dot { width: 10px; height: 10px; border-radius: 2px; flex: none; }
.lg-val { margin-left: auto; color: var(--muted); font-variant-numeric: tabular-nums; }
.projection-section { border-top: 1px solid var(--border); margin-top: 14px; padding-top: 14px; }
.projection-section::before { content: 'Earnings projection'; display: block; font-size: 10px; text-transform: uppercase; color: var(--muted); letter-spacing: 0.5px; font-weight: 600; margin-bottom: 10px; }
</style>
</head>
<body>
<div class="container">
  <header style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap">
    <div>
      <h1 id="h1-title">FortyTwo Network: Node Analysis</h1>
      <div class="meta" id="meta">Loading…</div>
    </div>
    <!-- Logout button. Hidden via JS when /v1/dashboard-data tells us auth
         is disabled (set CSS hidden until first refresh resolves it). -->
    <form id="logout-form" method="post" action="/logout" style="display:none">
      <button class="toggle-btn" type="submit">logout</button>
    </form>
  </header>
  <!-- Back-link to the all-nodes overview. Per-node navigation lives there. -->
  <div style="margin-bottom:16px">
    <a href="/dashboard" class="toggle-btn" style="text-decoration:none">&larr; All nodes</a>
  </div>
  <div class="grid">
    <div class="card balance-card">
      <h2>FOR Balance (Monad Testnet)</h2>
      <div id="balance-content">…</div>
      <div id="projection-content" class="projection-section">…</div>
    </div>
    <div class="card has-settings">
      <div class="section-header">
        <h2 id="node-title" style="margin-bottom:0">Node</h2>
        <button class="kebab-btn" type="button" data-pop="node-pop" aria-label="Node settings" aria-expanded="false">&#9776;</button>
      </div>
      <div id="node-pop" class="settings-popup" hidden>
        <div class="pop-row">
          <span class="pop-label">TPS display</span>
          <span class="toggle-group">
            <button class="toggle-btn" data-tps="actual">Actual</button>
            <button class="toggle-btn" data-tps="max">Max</button>
          </span>
        </div>
      </div>
      <div id="node-content">…</div>
    </div>
    <div class="card"><h2>Today (UTC)</h2>
      <div id="today-content">
        <div class="donut-wrap">
          <canvas id="today-donut"></canvas>
          <div id="today-center" class="donut-center"></div>
        </div>
        <div id="today-legend" class="donut-legend"></div>
      </div>
    </div>
  </div>
  <div class="chart-wrap has-settings">
    <div class="section-header">
      <span class="section-title">Rounds participated</span>
      <span id="power-stat" style="margin-left:auto;font-size:12px;color:var(--muted);text-transform:none;letter-spacing:0;font-weight:400"></span>
      <button class="kebab-btn" type="button" data-pop="chart-pop" aria-label="Chart settings" aria-expanded="false">&#9776;</button>
    </div>
    <div id="chart-pop" class="settings-popup" hidden>
      <div class="pop-row">
        <span class="pop-label">Chart period</span>
        <span class="toggle-group">
          <button class="toggle-btn" data-mode="hourly">24h</button>
          <button class="toggle-btn" data-mode="daily">7d</button>
          <button class="toggle-btn" data-mode="weekly">4w</button>
        </span>
      </div>
    </div>
    <canvas id="hourChart"></canvas>
  </div>
  <div class="rounds-list">
    <div class="section-title">Recent rounds</div>
    <table>
      <thead><tr><th>Time UTC</th><th>Duration</th><th>Round hash</th><th>Tx hash</th></tr></thead>
      <tbody id="rounds-body"></tbody>
    </table>
  </div>

  <div class="rounds-list has-settings" style="margin-top: 16px;">
    <div class="section-header">
      <span class="section-title">Node log (last 500 lines)</span>
      <button class="kebab-btn" type="button" data-pop="log-pop" aria-label="Log settings" aria-expanded="false">&#9776;</button>
    </div>
    <div id="log-pop" class="settings-popup" hidden>
      <div class="pop-row">
        <span class="pop-label">Source</span>
        <span class="toggle-group">
          <button class="toggle-btn" data-log="extended">extended</button>
          <button class="toggle-btn" data-log="capsule">capsule</button>
        </span>
      </div>
      <div class="pop-row">
        <span class="pop-label">Filter</span>
        <span class="toggle-group">
          <button class="toggle-btn" data-logfilter="all">All</button>
          <button class="toggle-btn" data-logfilter="events">Events</button>
        </span>
      </div>
    </div>
    <pre id="log-view" class="log-view"></pre>
  </div>

  <div class="rounds-list" style="margin-top: 16px;">
    <div class="section-title">Last 3 errors</div>
    <table>
      <thead><tr><th>Time UTC</th><th>Message</th></tr></thead>
      <tbody id="errors-body"><tr><td colspan="2" style="color:var(--muted);text-align:center">Loading…</td></tr></tbody>
    </table>
  </div>

  <div class="rounds-list" style="margin-top: 16px;">
    <div class="section-title">Watched wallets (multi-wallet)</div>
    <p style="color: var(--muted); font-size: 13px; margin-bottom: 12px;">
      Add any Monad Testnet wallet to watch its FOR + MONAD balance.
    </p>
    <form id="add-form" style="display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;">
      <input id="addr-input" type="text" placeholder="0x… wallet address" required pattern="^0x[0-9a-fA-F]{40}$"
        style="flex: 1; min-width: 220px; padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; font-family: ui-monospace, monospace; font-size: 13px;">
      <input id="label-input" type="text" placeholder="label (optional)" maxlength="40"
        style="width: 180px; padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; font-size: 13px;">
      <button type="submit" style="padding: 8px 16px; background: var(--blue); color: #000; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 13px;">Add</button>
    </form>
    <div id="add-msg" style="font-size: 12px; min-height: 16px; margin-bottom: 8px;"></div>
    <table>
      <thead><tr><th>Wallet</th><th>Label</th><th>FOR Balance</th><th>MONAD</th><th></th></tr></thead>
      <tbody id="wallets-body"><tr><td colspan="5" style="color:var(--muted);text-align:center">Loading…</td></tr></tbody>
    </table>
  </div>

  <footer>Auto-refresh every 5s · <span id="updated"></span></footer>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
// Per-node dashboard: read the node id from the URL path's trailing segment.
// /dashboard/1 → 1, /dashboard/2 → 2, /dashboard (legacy) is server-redirected
// to /dashboard/1 so we never see it here in practice.
const NODE_ID = parseInt(location.pathname.split('/').filter(Boolean).pop()) || 1;
document.title = 'FortyTwo Network: Node ' + NODE_ID;
(function(){ const h = document.getElementById('h1-title'); if (h) h.textContent = 'FortyTwo Network: Node ' + NODE_ID; })();
let chart;
let todayChart;
// Per-node localStorage prefs so switching nodes carries its own settings.
// Wrapped in try/catch -- Safari private mode and disabled-storage browsers
// throw on access. Fall back to the supplied default silently.
function loadPref(key, fallback){
  try { const v = localStorage.getItem('ft.' + key + '.node' + NODE_ID); return v == null ? fallback : v; }
  catch(_) { return fallback; }
}
function savePref(key, value){
  try { localStorage.setItem('ft.' + key + '.node' + NODE_ID, value); } catch(_) {}
}
let chartMode = loadPref('chartMode', 'hourly');
let logMode = loadPref('logMode', 'extended');
let logFilter = loadPref('logFilter', 'all');
const LOG_EVENT_RE = /Completed inference participation|Inference round \w+ completed|FOR balance (before|after) reward|Submitting intent resolution|Resolution of .* resolved|Node's balance is|Operator Wallet Address| ERROR /;
let tpsMode = loadPref('tpsMode', 'actual');
let lastSnapshot = null;
let lastChainRewards = null;  // most recent chain_rewards payload — needed by chart-mode toggle
let lastUptime = null;        // most recent uptime payload — needed when re-rendering on toggles
let lastPower = null;         // most recent power/energy payload — chart-card kW/kWh stat

function pad(n){ return String(n).padStart(2,'0'); }
function fmt(v){return v==null?'—':v;}
function fmtNum(n){return n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:2});}
function updateProjection(p){
  // Prefer today's pace (projected forward from elapsed UTC hours). If
  // it's too early in the day (server suppresses the fields below ~1h
  // elapsed) we fall back to the 7-day average so the card is never blank
  // mid-day. With neither -- show a friendly placeholder.
  const el = document.getElementById('projection-content');
  if (!p) { el.innerHTML = '<div style="color:var(--muted);font-size:13px">Awaiting on-chain data…</div>'; return; }
  const hasToday = p.today_projected_weekly != null;
  const hasAvg = p.avg_7d_daily != null;
  if (!hasToday && !hasAvg) {
    el.innerHTML =
      `<div style="color:var(--muted);font-size:13px">Not enough history yet — earn FOR through a UTC day to project.</div>`
      + `<div class="balance-reward" style="color:var(--muted)">${p.hours_elapsed?.toFixed(1) ?? '0'}h into today's UTC day</div>`;
    return;
  }
  let html = '';
  if (hasToday) {
    html += `<div class="balance-big">${fmtNum(p.today_projected_weekly)} <span style="color:var(--muted);font-size:14px;font-weight:400">FOR / wk</span></div>`;
    html += `<div class="balance-reward">${fmtNum(p.today_projected_daily)} FOR/day · ${fmtNum(p.today_projected_monthly)} FOR/mo</div>`;
    html += `<div class="balance-reward" style="color:var(--muted)">today's pace · ${p.hours_elapsed?.toFixed(1) ?? '0'}h elapsed</div>`;
  } else {
    html += `<div style="color:var(--muted);font-size:13px;margin-bottom:6px">Pace projection paused — too early in UTC day.</div>`;
  }
  if (hasAvg) {
    html += `<div class="balance-reward" style="color:var(--muted)">7-day avg: ${fmtNum(p.avg_7d_daily)} FOR/day (${p.days_used_for_avg}d seen)</div>`;
  }
  el.innerHTML = html;
}
function fmtAgo(epoch){if(!epoch)return'never';const d=Date.now()/1000-epoch;if(d<60)return`${Math.round(d)}s ago`;if(d<3600)return`${Math.round(d/60)}m ago`;if(d<86400)return`${Math.round(d/3600)}h ago`;return`${Math.round(d/86400)}d ago`;}
function fmtUp(s){if(!s)return'—';const d=Math.floor(s/86400),h=Math.floor((s%86400)/3600),m=Math.floor((s%3600)/60);if(d>0)return`${d}d ${h}h`;if(h>0)return`${h}h ${m}m`;return`${m}m`;}
function row(l,v){return`<div class="row"><span class="label">${l}</span><span class="value">${v}</span></div>`;}
function escapeHtml(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function hourKeyFromDate(d){return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}`;}

// bucket() returns labels + two parallel data arrays: `data` (rounds count
// from agent's rounds_history) and `forData` (FOR earned per bucket from
// chain_rewards.transfers_by_hour). Same hour-key format means both maps share
// the same lookup loop.
function bucket(history, forByHour, mode){
  history = history || {};
  forByHour = forByHour || {};
  const now = new Date();
  if (mode === 'hourly'){
    const anchorMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours());
    const labels=[], data=[], forData=[];
    for (let i=23; i>=0; i--){
      const t = new Date(anchorMs - i*3600e3);
      const key = hourKeyFromDate(t);
      labels.push(pad(t.getUTCHours()));
      data.push(history[key] || 0);
      forData.push(forByHour[key] || 0);
    }
    return {labels, data, forData};
  }
  if (mode === 'daily'){
    const todayMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const labels=[], data=[], forData=[];
    for (let i=6; i>=0; i--){
      const d = new Date(todayMs - i*86400e3);
      const datePrefix = `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
      let sum = 0, forSum = 0;
      for (let h=0; h<24; h++){
        const k = `${datePrefix}T${pad(h)}`;
        sum += history[k] || 0;
        forSum += forByHour[k] || 0;
      }
      labels.push(`${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`);
      data.push(sum);
      forData.push(forSum);
    }
    return {labels, data, forData};
  }
  if (mode === 'weekly'){
    const todayMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const dow = (new Date(todayMs).getUTCDay() + 6) % 7;
    const weekStartMs = todayMs - dow*86400e3;
    const labels=[], data=[], forData=[];
    for (let w=3; w>=0; w--){
      const startMs = weekStartMs - w*7*86400e3;
      let sum = 0, forSum = 0;
      for (let day=0; day<7; day++){
        const d = new Date(startMs + day*86400e3);
        const datePrefix = `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
        for (let h=0; h<24; h++){
          const k = `${datePrefix}T${pad(h)}`;
          sum += history[k] || 0;
          forSum += forByHour[k] || 0;
        }
      }
      const startD = new Date(startMs);
      labels.push(`wk ${pad(startD.getUTCMonth()+1)}-${pad(startD.getUTCDate())}`);
      data.push(sum);
      forData.push(forSum);
    }
    return {labels, data, forData};
  }
  return {labels:[], data:[], forData:[]};
}

function updateChart(history, forByHour){
  const { labels, data, forData } = bucket(history || {}, forByHour || {}, chartMode);
  if (!chart){
    const ctx = document.getElementById('hourChart').getContext('2d');
    chart = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [{
        data,
        forPerBucket: forData,           // sidecar — read by tooltip callback below
        backgroundColor: '#60a5fa',
        borderColor: '#3b82f6',
        borderWidth: 1,
        borderRadius: 3
      }] },
      options: { responsive: true, maintainAspectRatio: true, aspectRatio: 4,
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: c => {
            const rounds = c.parsed.y;
            const ds = c.chart.data.datasets[0];
            const forV = (ds.forPerBucket && ds.forPerBucket[c.dataIndex]) || 0;
            const forStr = forV > 0
              ? `${forV.toLocaleString(undefined, {maximumFractionDigits: 2})} FOR`
              : '— FOR';
            return [`${rounds} round${rounds === 1 ? '' : 's'}`, forStr];
          }
        } } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#888', font: { size: 10 } } },
          y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#888', precision: 0 } }
        }
      }
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    chart.data.datasets[0].forPerBucket = forData;
    chart.update('none');
  }
}

// kW / kWh stat on the Rounds-participated card: live GPU draw + the energy
// total for the period the chart toggle currently shows (24h->today, 7d, 4w).
function updatePowerStat(){
  const el = document.getElementById('power-stat'); if (!el) return;
  const p = lastPower;
  if (!p || (p.current_kw == null && !p.kwh_4w)) { el.textContent = ''; return; }
  const kw = (p.current_kw != null) ? p.current_kw.toFixed(3) + ' kW' : '— kW';
  const win = ({ hourly: ['kwh_today', 'today'], daily: ['kwh_7d', '7d'], weekly: ['kwh_4w', '4w'] })[chartMode]
            || ['kwh_today', 'today'];
  el.textContent = `⚡ ${kw} · ${fmtNum(p[win[0]] || 0)} kWh ${win[1]}`;
}

// FortyTwo brand colors (orange excluded) for the Today reward-outcome donut.
const TODAY_COLORS = { rewarded: '#C3F53B', unrewarded: '#2D2BF7', observed: '#8A8A8A' };
// Reward-outcome doughnut. participated/rewarded come from data.today (the
// durable Neon rounds table, so it renders even on a cold start when the live
// snapshot `s` is null); observed-only comes from the live snapshot.
function renderToday(data, s){
  const t = data.today || null;
  const P = (t && t.participated != null) ? t.participated : (s ? (s.rounds_participated_today || 0) : 0);
  const R = (t && t.rewarded != null) ? t.rewarded : 0;
  const U = Math.max(0, P - R);
  const O = s ? Math.max(0, (s.rounds_observed_today || 0) - (s.rounds_participated_today || 0)) : 0;
  const center = document.getElementById('today-center');
  const legend = document.getElementById('today-legend');
  if (P === 0 && O === 0){
    if (todayChart){ todayChart.destroy(); todayChart = null; }
    center.innerHTML = '';
    legend.innerHTML = '<div style="color:var(--muted);font-size:13px;text-align:center">No rounds today yet</div>';
    return;
  }
  const segs = [
    ['Rewarded', R, TODAY_COLORS.rewarded],
    ['Unrewarded', U, TODAY_COLORS.unrewarded],
    ['Observed', O, TODAY_COLORS.observed],
  ].filter(seg => seg[1] > 0);
  const labels = segs.map(x => x[0]), vals = segs.map(x => x[1]), cols = segs.map(x => x[2]);
  const ctx = document.getElementById('today-donut').getContext('2d');
  if (!todayChart){
    todayChart = new Chart(ctx, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: vals, backgroundColor: cols, borderColor: '#141414', borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: true, aspectRatio: 1, cutout: '68%',
        plugins: { legend: { display: false },
          tooltip: { callbacks: { label: c => `${c.label}: ${fmtNum(c.parsed)}` } } } }
    });
  } else {
    todayChart.data.labels = labels;
    todayChart.data.datasets[0].data = vals;
    todayChart.data.datasets[0].backgroundColor = cols;
    todayChart.update('none');
  }
  const pct = P ? Math.round(100 * R / P) : 0;
  center.innerHTML = `<div class="donut-pct">${pct}%</div><div class="donut-cap">rewarded</div>`;
  legend.innerHTML = segs.map(([lab, val, col]) =>
    `<div class="lg-item"><span class="lg-dot" style="background:${col}"></span>${lab}<span class="lg-val">${fmtNum(val)}</span></div>`
  ).join('');
}

function updateLog(s){
  const pre = document.getElementById('log-view');
  if (!s) { pre.textContent = '(no data)'; return; }
  // Sticky scroll: if the user is already at (or within 20 px of) the bottom,
  // auto-scroll to the new bottom after re-render. Otherwise preserve their
  // current scrollTop so they can read older entries without being yanked.
  // 20 px tolerates anti-aliasing rounding while still being tight enough
  // that "scrolled up reading" doesn't count as "at bottom."
  const wasAtBottom = (pre.scrollHeight - pre.scrollTop - pre.clientHeight) < 20;
  const oldScrollTop = pre.scrollTop;
  let lines = (logMode === 'extended' ? s.log_extended : s.log_capsule) || [];
  if (logFilter === 'events') {
    lines = lines.filter(ln => LOG_EVENT_RE.test(ln));
  }
  pre.textContent = lines.length
    ? lines.join('\n')
    : (logFilter === 'events' ? '(no matching events in this window)' : '(no log lines received)');
  if (wasAtBottom) {
    pre.scrollTop = pre.scrollHeight;
  } else {
    pre.scrollTop = oldScrollTop;
  }
}

function updateErrors(s){
  const errs = (s && s.recent_errors) || [];
  const body = document.getElementById('errors-body');
  body.innerHTML = errs.length
    ? errs.map(e => `<tr><td style="white-space:nowrap">${escapeHtml(e.iso||'—')}</td><td class="err-msg">${escapeHtml(e.message||'')}</td></tr>`).join('')
    : '<tr><td colspan="2" style="color:var(--muted);text-align:center">No errors today</td></tr>';
}

function renderTpsRows(s){
  if (tpsMode === 'max') {
    return row('Max TPS', fmt(s.capsule_max_tps))
      + row('Max symbols/sec', s.max_symbols != null ? fmtNum(s.max_symbols) : '—');
  }
  return row('TPS', s.tps_current != null ? fmtNum(s.tps_current) : '—')
    + row('Symbols/sec', s.symbols_current != null ? fmtNum(s.symbols_current) : '—');
}

function fmtPct(v){ return v==null ? '—' : `${Number(v).toFixed(1)}%`; }
function renderUptimeRow(u){
  // u is the server-rolled uptime object. We show 24h / 7d side-by-side
  // with sample counts in muted parens so the operator can tell whether
  // 100% is "yes, perfect" vs "yes, only 3 samples so far".
  if (!u) return '';
  const samples24 = u.samples_24h || 0;
  const samples7d = u.samples_7d || 0;
  // No samples yet -> placeholder. Samples take a minute each to accumulate
  // so it's normal for a brand-new node to show "—" briefly.
  if (!samples24 && !samples7d) {
    return row('Heartbeat uptime', '<span style="color:var(--muted);font-size:12px">collecting…</span>');
  }
  const colour = (p) => p == null ? 'var(--muted)' : (p >= 99 ? 'var(--green)' : (p >= 90 ? 'var(--text)' : 'var(--red)'));
  const c24 = colour(u.pct_24h);
  const c7d = colour(u.pct_7d);
  return row('Heartbeat uptime',
    `<span style="color:${c24}">${fmtPct(u.pct_24h)}</span> <span style="color:var(--muted);font-size:11px">24h (${samples24})</span>`
    + ` <span style="color:var(--muted)">·</span> `
    + `<span style="color:${c7d}">${fmtPct(u.pct_7d)}</span> <span style="color:var(--muted);font-size:11px">7d (${samples7d})</span>`
  );
}
function renderNodeCard(s, uptime){
  const titleEl = document.getElementById('node-title');
  const el = document.getElementById('node-content');
  if (!s) {
    if (titleEl) titleEl.style.color = '';
    el.innerHTML = row('Status', '<span class="badge down">No data</span>') + renderUptimeRow(uptime);
    return;
  }
  const alive = s.capsule_alive && s.protocol_alive;
  if (titleEl) titleEl.style.color = alive ? 'var(--green)' : 'var(--red)';

  const gpuName = s.gpu_name || '—';
  const vram = (s.gpu_vram_used_mb != null && s.gpu_vram_total_mb)
    ? `${(s.gpu_vram_used_mb/1024).toFixed(1)} GB / ${(s.gpu_vram_total_mb/1024).toFixed(1)} GB`
    : '—';

  // Model row: name + file size (GB) when the agent could stat the file.
  const sizeFrag = (s.model_size_gb && s.model_size_gb > 0)
    ? ` <span style="color:var(--muted)">(${Number(s.model_size_gb).toFixed(1)} GB)</span>`
    : '';
  el.innerHTML =
      row('Model', `<span style="font-size:11px">${s.model_short||'—'}${sizeFrag}</span>`)
    + row('GPU', `<span style="font-size:12px">${escapeHtml(gpuName)}</span>`)
    + row('VRAM', vram)
    + renderTpsRows(s)
    + row('Capsule', `${s.capsule_version||'—'} <span style="color:var(--muted)">PID ${s.capsule_pid||'—'}</span>`)
    + row('Protocol', `${s.protocol_version||'—'} <span style="color:var(--muted)">PID ${s.protocol_pid||'—'}</span>`)
    + row('Uptime', fmtUp(s.capsule_uptime_seconds))
    + renderUptimeRow(uptime);
}

async function refresh(){
  let data;
  try {
    const r = await fetch('/v1/dashboard-data?node='+NODE_ID,{cache:'no-store'});
    // Session expired (or never existed) -- bounce to login. Full navigation
    // because the page might be stale and we want a fresh render after auth.
    if (r.status === 401) { location.href = '/login'; return; }
    data = await r.json();
  }
  catch(e){ document.getElementById('meta').textContent='fetch error: '+e.message; return; }

  const s = data.snapshot;
  lastSnapshot = s;
  // Node's real FortyTwo three-word name (server-resolved from the leaderboard
  // by operator wallet) -- shown in the page title + browser tab ONLY; the node
  // card keeps its plain "Node" label. Falls back to "Node N" when unknown.
  const nodeLabel = data.node_name || ('Node ' + NODE_ID);
  document.title = 'FortyTwo Network: ' + nodeLabel;
  { const h = document.getElementById('h1-title'); if (h) h.textContent = 'FortyTwo Network: ' + nodeLabel; }
  lastChainRewards = data.chain_rewards || null;
  lastUptime = data.uptime || null;
  lastPower = data.power || null;
  document.getElementById('updated').textContent = 'updated '+new Date().toLocaleTimeString();

  // Reveal the logout button only when the server says auth is enabled.
  // When auth is disabled (local dev, unconfigured deploy) the form stays
  // display:none -- nothing to log out of.
  const logoutForm = document.getElementById('logout-form');
  if (logoutForm) {
    logoutForm.style.display = data.auth_enabled ? 'inline' : 'none';
  }

  // Staleness threshold: heartbeat is 60s; flag anything older than 3 min
  // (3 missed heartbeats) as STALE to leave room for jitter / network blips
  // without false-positive flapping.
  const ageS = s ? (Date.now()/1000 - s.received_at) : null;
  const staleBadge = (ageS != null && ageS > 180)
    ? ` <span class="badge down" title="No agent push received in ${Math.round(ageS)}s">STALE</span>`
    : '';
  // Agent version (short git SHA) — operator can see which commit the agent
  // is running. Useful for confirming an auto-update landed.
  const versionFrag = (s && s.agent_version)
    ? ` · <span style="font-family:monospace;font-size:11px">v ${escapeHtml(s.agent_version)}</span>`
    : '';
  document.getElementById('meta').innerHTML = s
    ? `Wallet <span style="font-family:monospace">${data.wallet_short}</span> · last push ${fmtAgo(s.received_at)} (UTC ${s.ts?s.ts.slice(11,19):'—'})${versionFrag}${staleBadge}`
    : '<span class="badge down">No data</span> — workstation agent has not pushed yet';

  if(!s){
    renderNodeCard(null, lastUptime);
    document.getElementById('rounds-body').innerHTML = '<tr><td colspan="3" style="color:var(--muted);text-align:center">No data</td></tr>';
  } else {
    renderNodeCard(s, lastUptime);

    const recent = s.recent_rounds || [];
    document.getElementById('rounds-body').innerHTML = recent.length
      ? recent.map(r => {
          const roundHash = (r.hash || '').slice(0, 16);
          const txHash = r.tx_hash;
          // Tx hash is the on-chain Monad receipt that paid the round's reward
          // (from "Resolution of ... resolved. receipt hash 0x…" in the log).
          // Link goes to monadscan testnet so the user can verify on-chain.
          const txCell = txHash
            ? `<a href="https://testnet.monadscan.com/tx/${txHash}" target="_blank" rel="noopener" style="color:var(--blue);text-decoration:none" title="${txHash}">${txHash.slice(0,12)}…</a>`
            : '<span style="color:var(--muted)">—</span>';
          return `<tr>`
            + `<td>${r.completed_iso}</td>`
            + `<td>${r.duration_s}s</td>`
            + `<td style="color:var(--muted)">${roundHash}…</td>`
            + `<td>${txCell}</td>`
            + `</tr>`;
        }).join('')
      : '<tr><td colspan="4" style="color:var(--muted);text-align:center">No rounds today</td></tr>';
  }

  // Today doughnut: participated/rewarded from Neon (data.today, DB-backed so
  // it survives cold starts); observed-only from the live snapshot.
  renderToday(data, s);

  if(data.balance!=null){
    // Earned today + last reward: prefer chain-derived (authoritative for
    // total payouts to the wallet, including observer/periodic distributions
    // the Capsule log doesn't record). Fall back to the agent's log-derived
    // values if the chain scan is empty or errored — better to show a slightly
    // low number than to show nothing.
    const cr = data.chain_rewards || {};
    const usingChain = !!(cr.earned_today && !cr.error);
    const earned = usingChain ? cr.earned_today : (s && s.rewards_today_total);
    const earnedSource = usingChain ? '' : ' <span style="color:var(--muted);font-size:10px">(agent estimate)</span>';
    const lastAmt = usingChain ? cr.last_transfer_amount : (s && s.last_reward_amount);
    const lastIso = usingChain
      ? (cr.last_transfer_iso ? cr.last_transfer_iso.slice(11,19) : null)
      : (s && s.last_reward_iso);

    const monadStr = data.monad_balance != null
      ? `${Number(data.monad_balance).toFixed(4)} MON`
      : (data.monad_balance_error ? '<span style="color:var(--red)">MON RPC err</span>' : null);

    document.getElementById('balance-content').innerHTML =
      `<div class="balance-big">${fmtNum(data.balance)} <span style="color:var(--muted);font-size:14px;font-weight:400">FOR</span></div>`
      + (monadStr ? `<div class="balance-reward" style="color:var(--muted)">${monadStr}</div>` : '')
      + (earned ? `<div class="balance-reward">+${fmtNum(earned)} FOR earned today${earnedSource}</div>` : '')
      + (cr.transfers_today ? `<div class="balance-reward" style="color:var(--muted)">${cr.transfers_today} distributions today</div>` : '')
      + (lastAmt ? `<div class="balance-reward" style="color:var(--muted)">last +${fmtNum(lastAmt)} FOR at ${lastIso||'—'} UTC</div>` : '');
  } else {
    document.getElementById('balance-content').innerHTML = `<div style="color:var(--red);font-size:13px">RPC error: ${escapeHtml(data.balance_error||'unknown')}</div>`;
  }

  updateProjection(data.projections);

  updateChart(s ? s.rounds_history : {}, lastChainRewards ? lastChainRewards.transfers_by_hour : {});
  updatePowerStat();
  updateErrors(s);
  updateLog(s);
}
async function refreshWallets(){
  try {
    const r = await fetch('/v1/wallets', {cache:'no-store'});
    const data = await r.json();
    const rows = data.wallets || [];
    if (!rows.length) {
      document.getElementById('wallets-body').innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center">No wallets watched yet</td></tr>';
      return;
    }
    document.getElementById('wallets-body').innerHTML = rows.map(w => {
      const op = w.is_operator ? ' <span class="badge ok" style="margin-left:4px">OPERATOR</span>' : '';
      const forBal = w.for_balance != null ? fmtNum(w.for_balance) : '—';
      const monBal = w.monad_balance != null ? Number(w.monad_balance).toFixed(4) : '—';
      const label = w.label ? escapeHtml(w.label) : '<span style="color:var(--muted)">—</span>';
      const addr = String(w.address || '');
      const short = escapeHtml(`${addr.slice(0,8)}…${addr.slice(-6)}`);
      return `<tr>
        <td style="font-size:12px">${short}${op}</td>
        <td>${label}</td>
        <td>${forBal}</td>
        <td>${monBal}</td>
        <td><button onclick="copyAddr('${escapeHtml(addr)}')" style="background:none;border:1px solid var(--border);color:var(--muted);padding:2px 8px;border-radius:4px;cursor:pointer;font-size:11px">copy</button></td>
      </tr>`;
    }).join('');
  } catch(e){
    document.getElementById('wallets-body').innerHTML = `<tr><td colspan="5" style="color:var(--red);text-align:center">load error: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function copyAddr(a){ navigator.clipboard.writeText(a); }

document.getElementById('add-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const address = document.getElementById('addr-input').value.trim();
  const label = document.getElementById('label-input').value.trim() || null;
  const msg = document.getElementById('add-msg');
  msg.textContent = 'Adding…';
  msg.style.color = 'var(--muted)';
  try {
    const r = await fetch('/v1/wallets', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({address, label}),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || 'failed');
    msg.textContent = `Added ${j.address}`;
    msg.style.color = 'var(--green)';
    document.getElementById('addr-input').value = '';
    document.getElementById('label-input').value = '';
    refreshWallets();
  } catch(err){
    msg.textContent = 'Error: ' + err.message;
    msg.style.color = 'var(--red)';
  }
});

function syncActive(attr, value){
  document.querySelectorAll('.toggle-btn[data-' + attr + ']').forEach(b => b.classList.toggle('active', b.dataset[attr] === value));
}

document.querySelectorAll('.toggle-btn[data-mode]').forEach(btn => {
  btn.addEventListener('click', () => {
    chartMode = btn.dataset.mode;
    savePref('chartMode', chartMode);
    syncActive('mode', chartMode);
    updateChart(lastSnapshot ? lastSnapshot.rounds_history : {}, lastChainRewards ? lastChainRewards.transfers_by_hour : {});
    updatePowerStat();
  });
});

document.querySelectorAll('.toggle-btn[data-log]').forEach(btn => {
  btn.addEventListener('click', () => {
    logMode = btn.dataset.log;
    savePref('logMode', logMode);
    syncActive('log', logMode);
    updateLog(lastSnapshot);
  });
});

document.querySelectorAll('.toggle-btn[data-logfilter]').forEach(btn => {
  btn.addEventListener('click', () => {
    logFilter = btn.dataset.logfilter;
    savePref('logFilter', logFilter);
    syncActive('logfilter', logFilter);
    updateLog(lastSnapshot);
  });
});

document.querySelectorAll('.toggle-btn[data-tps]').forEach(btn => {
  btn.addEventListener('click', () => {
    tpsMode = btn.dataset.tps;
    savePref('tpsMode', tpsMode);
    syncActive('tps', tpsMode);
    if (lastSnapshot) renderNodeCard(lastSnapshot, lastUptime);
  });
});

// Sync the Settings-panel buttons' .active state to the current (possibly
// localStorage-loaded) prefs once on init. Without this, the panel always
// shows the FIRST button highlighted regardless of what's actually selected.
syncActive('mode', chartMode);
syncActive('tps', tpsMode);
syncActive('log', logMode);
syncActive('logfilter', logFilter);

// Per-card kebab popups. Each ☰ button opens its sibling popup (the one
// whose id matches the button's data-pop). Clicking the icon again or
// anywhere outside the open popup closes it. Only one popup open at a time
// -- opening a different card's menu auto-closes the first.
(function(){
  function closeAll(except){
    document.querySelectorAll('.settings-popup').forEach(p => {
      if (p === except) return;
      if (!p.hasAttribute('hidden')) {
        p.setAttribute('hidden', '');
        const btn = document.querySelector(`.kebab-btn[data-pop="${p.id}"]`);
        if (btn) { btn.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
      }
    });
  }
  // Default direction is "above" (opens upward). For cards near the top of
  // the page that doesn't leave room, so we flip individual popups downward
  // here by mutating CSS. Done on each open since the relevant heights/
  // scroll position can change between opens.
  function positionPopup(pop, btn){
    // Reset any prior flip so we measure the natural upward layout first.
    pop.classList.remove('open-below');
    const btnRect = btn.getBoundingClientRect();
    const needed = pop.offsetHeight + 12;  // popup height + breathing room
    if (btnRect.top - needed < 0) {
      pop.classList.add('open-below');
    }
  }
  document.querySelectorAll('.kebab-btn[data-pop]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const pop = document.getElementById(btn.dataset.pop);
      if (!pop) return;
      const wasHidden = pop.hasAttribute('hidden');
      closeAll(wasHidden ? pop : null);
      if (wasHidden) {
        pop.removeAttribute('hidden');
        // offsetHeight needs the popup to be visible to measure it.
        positionPopup(pop, btn);
        btn.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
      } else {
        pop.setAttribute('hidden', '');
        btn.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
      }
    });
  });
  // Click outside any open popup closes it. Clicks inside the popup
  // (e.g. on a toggle button) don't bubble up to here because the popup
  // stops at its own listener if needed; in practice the toggle handlers
  // don't call stopPropagation, so we must filter by ancestor.
  document.addEventListener('click', (e) => {
    if (e.target.closest('.settings-popup')) return;  // click was inside a popup
    if (e.target.closest('.kebab-btn')) return;       // handled by the button itself
    closeAll(null);
  });
  // Escape key closes the open popup.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAll(null);
  });
})();

refresh();
refreshWallets();
let refreshTimer = null;
let walletsTimer = null;

function startTimers() {
  if (!refreshTimer)  refreshTimer  = setInterval(refresh, 5000);
  if (!walletsTimer)  walletsTimer  = setInterval(refreshWallets, 30000);
}
function stopTimers() {
  if (refreshTimer) { clearInterval(refreshTimer);  refreshTimer  = null; }
  if (walletsTimer) { clearInterval(walletsTimer);  walletsTimer  = null; }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopTimers();
  } else {
    refresh();
    refreshWallets();
    startTimers();
  }
});

startTimers();
</script>
</body>
</html>
"""
