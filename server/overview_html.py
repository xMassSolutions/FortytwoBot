"""All-nodes overview page. Single string constant served from
GET /dashboard. Same dark-theme palette as dashboard_html.py.

Vanilla HTML + a tiny script that polls /v1/dashboard-overview every 5s
and renders one card per node plus a totals row. Click a node card to
drill into its full per-node page.
"""

OVERVIEW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>FortyTwo Network: All Nodes</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><g transform='rotate(-20 32 32)'><circle cx='32' cy='32' r='28' fill='none' stroke='%2360a5fa' stroke-width='2.5'/><circle cx='52' cy='32' r='3' fill='%234ade80'/></g><circle cx='32' cy='32' r='22' fill='%23141414'/><text x='32' y='42' text-anchor='middle' font-family='ui-monospace,monospace' font-weight='700' font-size='26' fill='%23e8e8e8'>42</text></svg>">
<style>
:root { --bg:#0a0a0a; --card:#141414; --text:#e8e8e8; --muted:#888; --green:#4ade80; --red:#f87171; --blue:#60a5fa; --border:#2a2a2a; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; padding: 16px; max-width: 1100px; margin: 0 auto; }
header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 16px; gap: 16px; flex-wrap: wrap; }
h1 { font-size: 16px; font-weight: 600; }
.meta { color: var(--muted); font-size: 13px; margin-top: 4px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; }
.card h2 { font-size: 11px; text-transform: uppercase; color: var(--muted); margin-bottom: 12px; letter-spacing: 0.5px; font-weight: 600; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 4px 0; font-size: 13px; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.row .label { color: var(--muted); flex-shrink: 0; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge.ok { background: rgba(74,222,128,0.15); color: var(--green); }
.badge.down { background: rgba(248,113,113,0.15); color: var(--red); }
.badge.muted { background: rgba(136,136,136,0.15); color: var(--muted); }
footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 24px; padding-bottom: 16px; }
a { color: var(--blue); text-decoration: none; }
.totals { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 16px; }
.totals .stat { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 18px; }
.totals .stat .label { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
.totals .stat .value { font-size: 22px; font-weight: 600; font-family: ui-monospace, "SF Mono", Menlo, monospace; margin-top: 4px; }
.totals .stat .sub { color: var(--muted); font-size: 11px; margin-top: 2px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
a.node-card { display: block; background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; color: var(--text); text-decoration: none; transition: border-color 0.1s; }
a.node-card:hover { border-color: var(--blue); }
.node-card h3 { font-size: 14px; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.node-card .wallet { font-family: ui-monospace, monospace; font-size: 11px; color: var(--muted); margin-bottom: 12px; }
.node-card .big { font-size: 24px; font-weight: 600; font-family: ui-monospace, monospace; }
.node-card .big .unit { color: var(--muted); font-size: 13px; font-weight: 400; }
.node-card .sub { color: var(--muted); font-size: 12px; margin-top: 4px; font-family: ui-monospace, monospace; }
form#logout-form button { background: transparent; border: 1px solid var(--border); color: var(--muted); padding: 4px 10px; border-radius: 4px; font-size: 11px; cursor: pointer; font-family: inherit; text-transform: uppercase; letter-spacing: 0.5px; }
form#logout-form button:hover { color: var(--text); }
</style>
</head>
<body>
<header>
  <div>
    <h1>FortyTwo Network: All Nodes</h1>
    <div class="meta"><span id="updated">loading…</span></div>
  </div>
  <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
    <label style="font-size:12px;color:var(--muted);cursor:pointer;display:flex;gap:6px;align-items:center">
      <input type="checkbox" id="show-placeholders" style="cursor:pointer"> show empty nodes
    </label>
    <form id="logout-form" method="post" action="/logout" style="display:none">
      <button type="submit">logout</button>
    </form>
  </div>
</header>

<div id="totals" class="totals">
  <div class="stat"><div class="label">Today's FOR</div><div class="value" id="t-earned">—</div><div class="sub" id="t-earned-sub">across all wallets</div></div>
  <div class="stat"><div class="label">Active nodes</div><div class="value" id="t-active">—</div><div class="sub" id="t-active-sub">&nbsp;</div></div>
  <div class="stat"><div class="label">Rounds today</div><div class="value" id="t-rounds">—</div><div class="sub">summed across nodes</div></div>
</div>

<div id="nodes" class="grid"></div>

<footer>Auto-refresh every 5s</footer>

<script>
function fmtNum(n){ return n==null ? '—' : Number(n).toLocaleString(undefined, {maximumFractionDigits: 2}); }
function escapeHtml(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
function fmtAgo(ts){
  if (ts == null) return '—';
  const s = Math.max(0, Math.floor(Date.now()/1000 - ts));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
}
function nodeStatusBadge(n){
  if (!n.received_at) return '<span class="badge muted">NO DATA</span>';
  const ageS = Math.max(0, Date.now()/1000 - n.received_at);
  if (ageS > 180) return '<span class="badge down" title="No agent push in '+Math.round(ageS)+'s">STALE</span>';
  if (n.capsule_alive && n.protocol_alive) return '<span class="badge ok">UP</span>';
  return '<span class="badge down">DOWN</span>';
}
function uptimeColor(p){
  if (p == null) return 'var(--muted)';
  if (p >= 99) return 'var(--green)';
  if (p >= 90) return 'var(--text)';
  return 'var(--red)';
}
function renderNode(n){
  const badge = nodeStatusBadge(n);
  const walletLine = n.wallet_short
    ? `<div class="wallet">${escapeHtml(n.wallet_short)}</div>`
    : `<div class="wallet">no wallet bound</div>`;
  const earned = (n.earned_today != null) ? fmtNum(n.earned_today) : '—';
  const tpsLine = (n.tps_current != null) ? `${fmtNum(n.tps_current)} <span class="unit">TPS</span>` : '— <span class="unit">TPS</span>';
  const upPct = (n.uptime_pct_24h != null) ? `${Number(n.uptime_pct_24h).toFixed(1)}%` : '—';
  const upColor = uptimeColor(n.uptime_pct_24h);
  const seen = n.received_at ? fmtAgo(n.received_at) : 'no push yet';
  return `
    <a class="node-card" href="/dashboard/${n.node_id}">
      <h3>Node ${n.node_id} ${badge}</h3>
      ${walletLine}
      <div class="big">${earned} <span class="unit">FOR today</span></div>
      <div class="sub">${tpsLine} · ${n.rounds_participated_today || 0} rounds · last push ${seen}</div>
      <div class="sub">24h uptime <span style="color:${upColor}">${upPct}</span></div>
    </a>
  `;
}
// Placeholder-nodes toggle. Server always returns {1,2} fallback so the
// dashboard can show "about to come online" tiles, but for single-node ops
// the empty Node-2 card is noise. Default off; persists per browser.
function showPlaceholders(){
  try { return localStorage.getItem('ft.overview.showPlaceholders') === '1'; } catch(_) { return false; }
}
const cbox = document.getElementById('show-placeholders');
if (cbox) {
  cbox.checked = showPlaceholders();
  cbox.addEventListener('change', () => {
    try { localStorage.setItem('ft.overview.showPlaceholders', cbox.checked ? '1' : '0'); } catch(_) {}
    refresh();
  });
}

async function refresh(){
  let data;
  try {
    const r = await fetch('/v1/dashboard-overview', {cache: 'no-store'});
    if (r.status === 401) { location.href = '/login'; return; }
    data = await r.json();
  } catch(e) {
    document.getElementById('updated').textContent = 'fetch error: ' + e.message;
    return;
  }
  document.getElementById('updated').textContent = 'updated ' + new Date().toLocaleTimeString();
  const logoutForm = document.getElementById('logout-form');
  if (logoutForm) logoutForm.style.display = data.auth_enabled ? 'inline' : 'none';

  // Filter empty placeholder tiles unless the operator opts in.
  let nodes = data.nodes || [];
  if (!showPlaceholders()) {
    nodes = nodes.filter(n => n.received_at != null);
  }

  const t = data.totals || {};
  document.getElementById('t-earned').textContent = fmtNum(t.earned_today);
  document.getElementById('t-earned-sub').textContent = (t.distinct_wallets || 0) + ' wallet' + ((t.distinct_wallets === 1) ? '' : 's');
  const visibleKnown = showPlaceholders() ? (t.nodes_known || 0) : nodes.length;
  document.getElementById('t-active').innerHTML = `${t.nodes_active || 0} <span style="color:var(--muted);font-size:13px;font-weight:400">of ${visibleKnown}</span>`;
  document.getElementById('t-active-sub').textContent = (t.nodes_active === visibleKnown) ? 'all up' : ((visibleKnown - t.nodes_active) + ' missing');
  document.getElementById('t-rounds').textContent = fmtNum(t.rounds_participated_today);

  const grid = document.getElementById('nodes');
  grid.innerHTML = nodes.length
    ? nodes.map(renderNode).join('')
    : '<div style="color:var(--muted);font-size:13px;padding:20px;text-align:center;grid-column:1/-1">No nodes have pushed yet. Tick &ldquo;show empty nodes&rdquo; to see placeholders.</div>';
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
