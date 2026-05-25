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
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>FortyTwo Network: Node Analysis</h1>
    <div class="meta" id="meta">Loading…</div>
  </header>
  <div class="grid">
    <div class="card"><h2>FOR Balance (Monad Testnet)</h2><div id="balance-content">…</div></div>
    <div class="card">
      <div class="section-header" style="margin-bottom:12px">
        <h2 id="node-title" style="margin-bottom:0">Node</h2>
        <span class="toggle-group">
          <button class="toggle-btn active" data-tps="actual">Actual</button>
          <button class="toggle-btn" data-tps="max">Max</button>
        </span>
      </div>
      <div id="node-content">…</div>
    </div>
    <div class="card"><h2>Today (UTC)</h2><div id="today-content">…</div></div>
  </div>
  <div class="chart-wrap">
    <div class="section-header">
      <span class="section-title">Rounds participated</span>
      <span class="toggle-group">
        <button class="toggle-btn active" data-mode="hourly">24h</button>
        <button class="toggle-btn" data-mode="daily">7d</button>
        <button class="toggle-btn" data-mode="weekly">4w</button>
      </span>
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

  <div class="rounds-list" style="margin-top: 16px;">
    <div class="section-header">
      <span class="section-title">Node log (last 500 lines)</span>
      <span class="toggle-group">
        <button class="toggle-btn active" data-log="extended">extended</button>
        <button class="toggle-btn" data-log="capsule">capsule</button>
      </span>
    </div>
    <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
      <span class="toggle-group">
        <button class="toggle-btn active" data-logfilter="all">All</button>
        <button class="toggle-btn" data-logfilter="events">Events</button>
      </span>
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
let chart;
let chartMode = 'hourly';
let logMode = 'extended';
let logFilter = 'all';
const LOG_EVENT_RE = /Completed inference participation|Inference round \w+ completed|FOR balance (before|after) reward|Submitting intent resolution|Resolution of .* resolved|Node's balance is|Operator Wallet Address| ERROR /;
let tpsMode = 'actual';
let lastSnapshot = null;
let lastChainRewards = null;  // most recent chain_rewards payload — needed by chart-mode toggle

function pad(n){ return String(n).padStart(2,'0'); }
function fmt(v){return v==null?'—':v;}
function fmtNum(n){return n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:2});}
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

function renderNodeCard(s){
  const titleEl = document.getElementById('node-title');
  const el = document.getElementById('node-content');
  if (!s) {
    if (titleEl) titleEl.style.color = '';
    el.innerHTML = row('Status', '<span class="badge down">No data</span>');
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
    + row('Uptime', fmtUp(s.capsule_uptime_seconds));
}

async function refresh(){
  let data;
  try { const r = await fetch('/v1/dashboard-data',{cache:'no-store'}); data = await r.json(); }
  catch(e){ document.getElementById('meta').textContent='fetch error: '+e.message; return; }

  const s = data.snapshot;
  lastSnapshot = s;
  lastChainRewards = data.chain_rewards || null;
  document.getElementById('updated').textContent = 'updated '+new Date().toLocaleTimeString();

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
    document.getElementById('node-content').innerHTML = row('Status','<span class="badge down">No data</span>');
    document.getElementById('today-content').innerHTML = row('Status','—');
    document.getElementById('rounds-body').innerHTML = '<tr><td colspan="3" style="color:var(--muted);text-align:center">No data</td></tr>';
  } else {
    renderNodeCard(s);

    const participated = s.rounds_participated_today || 0;
    // wins_today now mirrors participations on the agent side. rewards_logged_today
    // = positive-delta balance pairs (rewards captured in the Capsule's ~7-sec
    // snapshot window). Shown as a diagnostic for how many rewards were caught
    // in-window — the chain_rewards.transfers_today on the FOR card is the
    // authoritative total.
    const loggedRewards = s.rewards_logged_today || 0;
    const loggedRow = participated > 0
      ? row('Rewarded (log)', `<span style="color:var(--muted)">${loggedRewards} / ${participated} in-snapshot</span>`)
      : '';

    document.getElementById('today-content').innerHTML =
        row('Participated', `<strong style="font-size:18px">${participated}</strong>`)
      + row('Observed', s.rounds_observed_today)
      + row('Errors', s.errors_today)
      + loggedRow
      + row('First round', s.first_round_today_iso||'—')
      + row('Last round', `${s.last_round_today_iso||'—'} <span style="color:var(--muted)">${s.last_round_duration_s?s.last_round_duration_s+'s':''}</span>`);

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
      + (s && s.wins_today ? `<div class="balance-reward" style="color:var(--muted)">${s.wins_today} wins today</div>` : '')
      + (lastAmt ? `<div class="balance-reward" style="color:var(--muted)">last +${fmtNum(lastAmt)} FOR at ${lastIso||'—'} UTC</div>` : '');
  } else {
    document.getElementById('balance-content').innerHTML = `<div style="color:var(--red);font-size:13px">RPC error: ${data.balance_error||'unknown'}</div>`;
  }

  updateChart(s ? s.rounds_history : {}, lastChainRewards ? lastChainRewards.transfers_by_hour : {});
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
      const label = w.label || '<span style="color:var(--muted)">—</span>';
      const short = `${w.address.slice(0,8)}…${w.address.slice(-6)}`;
      return `<tr>
        <td style="font-size:12px">${short}${op}</td>
        <td>${label}</td>
        <td>${forBal}</td>
        <td>${monBal}</td>
        <td><button onclick="copyAddr('${w.address}')" style="background:none;border:1px solid var(--border);color:var(--muted);padding:2px 8px;border-radius:4px;cursor:pointer;font-size:11px">copy</button></td>
      </tr>`;
    }).join('');
  } catch(e){
    document.getElementById('wallets-body').innerHTML = `<tr><td colspan="5" style="color:var(--red);text-align:center">load error: ${e.message}</td></tr>`;
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

document.querySelectorAll('.toggle-btn[data-mode]').forEach(btn => {
  btn.addEventListener('click', () => {
    chartMode = btn.dataset.mode;
    document.querySelectorAll('.toggle-btn[data-mode]').forEach(b => b.classList.toggle('active', b.dataset.mode === chartMode));
    updateChart(lastSnapshot ? lastSnapshot.rounds_history : {}, lastChainRewards ? lastChainRewards.transfers_by_hour : {});
  });
});

document.querySelectorAll('.toggle-btn[data-log]').forEach(btn => {
  btn.addEventListener('click', () => {
    logMode = btn.dataset.log;
    document.querySelectorAll('.toggle-btn[data-log]').forEach(b => b.classList.toggle('active', b.dataset.log === logMode));
    updateLog(lastSnapshot);
  });
});

document.querySelectorAll('.toggle-btn[data-logfilter]').forEach(btn => {
  btn.addEventListener('click', () => {
    logFilter = btn.dataset.logfilter;
    document.querySelectorAll('.toggle-btn[data-logfilter]').forEach(b => b.classList.toggle('active', b.dataset.logfilter === logFilter));
    updateLog(lastSnapshot);
  });
});

document.querySelectorAll('.toggle-btn[data-tps]').forEach(btn => {
  btn.addEventListener('click', () => {
    tpsMode = btn.dataset.tps;
    document.querySelectorAll('.toggle-btn[data-tps]').forEach(b => b.classList.toggle('active', b.dataset.tps === tpsMode));
    if (lastSnapshot) renderNodeCard(lastSnapshot);
  });
});

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
