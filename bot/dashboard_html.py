DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>FortyTwo Node Status</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
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
    <h1>FortyTwo Node Status</h1>
    <div class="meta" id="meta">Loading…</div>
  </header>
  <div class="grid">
    <div class="card"><h2>FOR Balance (Monad Testnet)</h2><div id="balance-content">…</div></div>
    <div class="card"><h2>Node</h2><div id="node-content">…</div></div>
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
      <thead><tr><th>Time UTC</th><th>Duration</th><th>Request hash</th></tr></thead>
      <tbody id="rounds-body"></tbody>
    </table>
  </div>

  <div class="rounds-list" style="margin-top: 16px;">
    <div class="section-title">Last 3 errors</div>
    <table>
      <thead><tr><th>Time UTC</th><th>Message</th></tr></thead>
      <tbody id="errors-body"><tr><td colspan="2" style="color:var(--muted);text-align:center">Loading…</td></tr></tbody>
    </table>
  </div>

  <div class="rounds-list" style="margin-top: 16px;">
    <div class="section-header">
      <span class="section-title">Node log (last 100 lines)</span>
      <span class="toggle-group">
        <button class="toggle-btn active" data-log="extended">extended</button>
        <button class="toggle-btn" data-log="capsule">capsule</button>
      </span>
    </div>
    <pre id="log-view" class="log-view"></pre>
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

  <footer>Auto-refresh every 3m · <span id="updated"></span></footer>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
let chart;
let chartMode = 'hourly';
let logMode = 'extended';
let lastSnapshot = null;

function pad(n){ return String(n).padStart(2,'0'); }
function fmt(v){return v==null?'—':v;}
function fmtNum(n){return n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:2});}
function fmtAgo(epoch){if(!epoch)return'never';const d=Date.now()/1000-epoch;if(d<60)return`${Math.round(d)}s ago`;if(d<3600)return`${Math.round(d/60)}m ago`;if(d<86400)return`${Math.round(d/3600)}h ago`;return`${Math.round(d/86400)}d ago`;}
function fmtUp(s){if(!s)return'—';const d=Math.floor(s/86400),h=Math.floor((s%86400)/3600),m=Math.floor((s%3600)/60);if(d>0)return`${d}d ${h}h`;if(h>0)return`${h}h ${m}m`;return`${m}m`;}
function row(l,v){return`<div class="row"><span class="label">${l}</span><span class="value">${v}</span></div>`;}
function escapeHtml(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function hourKeyFromDate(d){return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}`;}

function bucket(history, mode){
  history = history || {};
  const now = new Date();
  if (mode === 'hourly'){
    const anchorMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours());
    const labels=[], data=[];
    for (let i=23; i>=0; i--){
      const t = new Date(anchorMs - i*3600e3);
      labels.push(pad(t.getUTCHours()));
      data.push(history[hourKeyFromDate(t)] || 0);
    }
    return {labels, data};
  }
  if (mode === 'daily'){
    const todayMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const labels=[], data=[];
    for (let i=6; i>=0; i--){
      const d = new Date(todayMs - i*86400e3);
      const datePrefix = `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
      let sum = 0;
      for (let h=0; h<24; h++){ sum += history[`${datePrefix}T${pad(h)}`] || 0; }
      labels.push(`${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`);
      data.push(sum);
    }
    return {labels, data};
  }
  if (mode === 'weekly'){
    const todayMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const dow = (new Date(todayMs).getUTCDay() + 6) % 7;
    const weekStartMs = todayMs - dow*86400e3;
    const labels=[], data=[];
    for (let w=3; w>=0; w--){
      const startMs = weekStartMs - w*7*86400e3;
      let sum = 0;
      for (let day=0; day<7; day++){
        const d = new Date(startMs + day*86400e3);
        const datePrefix = `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
        for (let h=0; h<24; h++){ sum += history[`${datePrefix}T${pad(h)}`] || 0; }
      }
      const startD = new Date(startMs);
      labels.push(`wk ${pad(startD.getUTCMonth()+1)}-${pad(startD.getUTCDate())}`);
      data.push(sum);
    }
    return {labels, data};
  }
  return {labels:[], data:[]};
}

function updateChart(history){
  const { labels, data } = bucket(history || {}, chartMode);
  if (!chart){
    const ctx = document.getElementById('hourChart').getContext('2d');
    chart = new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets: [{ data, backgroundColor: '#60a5fa', borderColor: '#3b82f6', borderWidth: 1, borderRadius: 3 }] },
      options: { responsive: true, maintainAspectRatio: true, aspectRatio: 4,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.parsed.y} round(s)` } } },
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#888', font: { size: 10 } } },
          y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#888', precision: 0 } }
        }
      }
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = data;
    chart.update('none');
  }
}

function updateLog(s){
  const pre = document.getElementById('log-view');
  if (!s) { pre.textContent = '(no data)'; return; }
  const lines = (logMode === 'extended' ? s.log_extended : s.log_capsule) || [];
  pre.textContent = lines.length ? lines.join('\n') : '(no log lines received)';
}

function updateErrors(s){
  const errs = (s && s.recent_errors) || [];
  const body = document.getElementById('errors-body');
  body.innerHTML = errs.length
    ? errs.map(e => `<tr><td style="white-space:nowrap">${escapeHtml(e.iso||'—')}</td><td class="err-msg">${escapeHtml(e.message||'')}</td></tr>`).join('')
    : '<tr><td colspan="2" style="color:var(--muted);text-align:center">No errors today</td></tr>';
}

async function refresh(){
  let data;
  try { const r = await fetch('/v1/dashboard-data',{cache:'no-store'}); data = await r.json(); }
  catch(e){ document.getElementById('meta').textContent='fetch error: '+e.message; return; }

  const s = data.snapshot;
  lastSnapshot = s;
  document.getElementById('updated').textContent = 'updated '+new Date().toLocaleTimeString();

  document.getElementById('meta').innerHTML = s
    ? `Wallet <span style="font-family:monospace">${data.wallet_short}</span> · last push ${fmtAgo(s.received_at)} (UTC ${s.ts?s.ts.slice(11,19):'—'})`
    : '<span class="badge down">No data</span> — workstation agent has not pushed yet';

  if(!s){
    document.getElementById('node-content').innerHTML = row('Status','<span class="badge down">No data</span>');
    document.getElementById('today-content').innerHTML = row('Status','—');
    document.getElementById('rounds-body').innerHTML = '<tr><td colspan="3" style="color:var(--muted);text-align:center">No data</td></tr>';
  } else {
    const alive = (s.capsule_alive && s.protocol_alive) ? '<span class="badge ok">ALIVE</span>' : '<span class="badge down">DOWN</span>';
    document.getElementById('node-content').innerHTML =
        row('Status', alive)
      + row('Model', `<span style="font-size:11px">${s.model_short||'—'}</span>`)
      + row('Max TPS', fmt(s.capsule_max_tps))
      + row('Capsule', `${s.capsule_version||'—'} <span style="color:var(--muted)">PID ${s.capsule_pid||'—'}</span>`)
      + row('Protocol', `${s.protocol_version||'—'} <span style="color:var(--muted)">PID ${s.protocol_pid||'—'}</span>`)
      + row('Uptime', fmtUp(s.capsule_uptime_seconds));

    const participated = s.rounds_participated_today || 0;
    const wins = s.wins_today || 0;
    const losses = Math.max(participated - wins, 0);
    const wlRow = participated > 0
      ? row('W / L', `<span style="color:var(--green)">${wins}</span> / <span style="color:var(--red)">${losses}</span>`)
        + row('Win rate', `${Math.round(wins / participated * 100)}%`)
      : '';

    document.getElementById('today-content').innerHTML =
        row('Participated', `<strong style="font-size:18px">${participated}</strong>`)
      + row('Observed', s.rounds_observed_today)
      + row('Errors', s.errors_today)
      + wlRow
      + row('First round', s.first_round_today_iso||'—')
      + row('Last round', `${s.last_round_today_iso||'—'} <span style="color:var(--muted)">${s.last_round_duration_s?s.last_round_duration_s+'s':''}</span>`);

    const recent = s.recent_rounds || [];
    document.getElementById('rounds-body').innerHTML = recent.length
      ? recent.map(r=>`<tr><td>${r.completed_iso}</td><td>${r.duration_s}s</td><td style="color:var(--muted)">${(r.hash||'').slice(0,16)}…</td></tr>`).join('')
      : '<tr><td colspan="3" style="color:var(--muted);text-align:center">No rounds today</td></tr>';
  }

  if(data.balance!=null){
    document.getElementById('balance-content').innerHTML =
      `<div class="balance-big">${fmtNum(data.balance)} <span style="color:var(--muted);font-size:14px;font-weight:400">FOR</span></div>`
      + (s && s.rewards_today_total ? `<div class="balance-reward">+${fmtNum(s.rewards_today_total)} FOR earned today</div>` : '')
      + (s && s.wins_today ? `<div class="balance-reward" style="color:var(--muted)">${s.wins_today} wins today</div>` : '')
      + (s && s.last_reward_amount ? `<div class="balance-reward" style="color:var(--muted)">last +${fmtNum(s.last_reward_amount)} FOR at ${s.last_reward_iso||'—'} UTC</div>` : '');
  } else {
    document.getElementById('balance-content').innerHTML = `<div style="color:var(--red);font-size:13px">RPC error: ${data.balance_error||'unknown'}</div>`;
  }

  updateChart(s ? s.rounds_history : {});
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
    updateChart(lastSnapshot ? lastSnapshot.rounds_history : {});
  });
});

document.querySelectorAll('.toggle-btn[data-log]').forEach(btn => {
  btn.addEventListener('click', () => {
    logMode = btn.dataset.log;
    document.querySelectorAll('.toggle-btn[data-log]').forEach(b => b.classList.toggle('active', b.dataset.log === logMode));
    updateLog(lastSnapshot);
  });
});

refresh();
refreshWallets();
setInterval(refresh, 180000);
setInterval(refreshWallets, 180000);
</script>
</body>
</html>
"""
