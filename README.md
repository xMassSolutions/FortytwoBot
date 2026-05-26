# FortyTwo Network: Node Analysis

Self-hostable dashboard + workstation agent for monitoring one or more [FortyTwo Network](https://fortytwo.network/) inference nodes. Tracks rounds, on-chain FOR rewards on Monad Testnet, TPS, and node health — all in a single web dashboard reachable from any device.

## What you get

- **One or many nodes, one dashboard.** Each node gets its own page at `/dashboard/<id>`; flip between them with the tab strip across the top. Per-node operator wallets — balances and reward histories stay isolated.
- **Durable reward history.** Point the bot at a free [Neon](https://neon.tech) Postgres and today's per-hour FOR earnings + the rolling rounds-participated chart survive every Render cold start and redeploy. Without it, the bot still runs on ephemeral SQLite — just forgets yesterday.
- **Optional login wall.** Username/password in front of every dashboard page and JSON endpoint. Plaintext password never lives on the server — you generate a bcrypt hash locally and paste only the hash into Render. Sessions stick for 7 days; one click to log out.
- **Live node telemetry.** FOR + MONAD balance, today's on-chain earnings, last reward, model + size, GPU + VRAM, TPS / symbols/sec, Capsule + Protocol versions + uptime, first / last round times — auto-refreshed every 5 s.
- **On-chain truth for rewards.** "FOR earned today" is computed by scanning ERC-20 Transfer events on Monad Testnet directly — not derived from the Capsule log. Recent rounds get their tx hash linked to monadscan automatically; the chain matcher fixes up rounds the log forgot.
- **Auto-updating workstation agent.** Self-pulls from `origin/main` every 30 min and restarts on the new code. Surfaces the running git SHA on the dashboard so you can confirm an update landed.
- **Multi-wallet watch.** Add any Monad Testnet address to track its FOR + MONAD balance alongside your operator wallet.
- **Free-tier friendly.** Designed to run on Render free + Neon free + your own workstation. No paid services required.

Responsive layout, Add-to-Home-Screen friendly.

### Supported platforms

| Layer | Options |
|---|---|
| **Bot host** | Render · Railway · any Docker host (`bot/Dockerfile`) |
| **Postgres** | Neon · Supabase · any standard Postgres URL — optional, SQLite fallback works |
| **Agent OS** | Windows (Scheduled Task) · macOS (launchd) · Linux (systemd) |
| **Node runtime** | Native (`pgrep` / `Get-Process`) · Docker (`docker top` / `docker inspect`) |
| **GPU telemetry** | NVIDIA `nvidia-smi` · Windows WMI fallback · macOS `system_profiler` |

---

## Quick install (give this to an AI agent)

If you have a coding agent with tool use (Claude, ChatGPT-with-tools, etc.), paste the prompt below and it can do the whole install for you. The [manual install](#install) further down covers the same ground if you'd rather drive it yourself.

> Install the FortyTwo Network node monitoring stack from
> `https://github.com/<your-fork>/FortytwoNetworkNode` for me.
>
> 1. Fork the repo to my GitHub account if I haven't already.
> 2. Deploy the `bot/` service to my Render account using the blueprint at
>    `render.yaml`. Prompt me for `WALLET` (my Monad Testnet operator wallet)
>    and generate a random 40-char `AGENT_TOKEN`.
> 3. Set up free [Neon](https://neon.tech) Postgres so reward history
>    survives Render cold starts. Create a project in the region nearest
>    my Render region, copy the pooled connection string, set it as
>    `DATABASE_URL` in Render. (If I say I don't want this, skip and let
>    the bot fall back to ephemeral SQLite.)
> 4. (Optional, ask me first.) Lock the dashboard behind a login:
>    generate a random password, hash it with `bcrypt.hashpw`, set
>    `DASHBOARD_USER`, `DASHBOARD_PASS_HASH`, and a random hex
>    `SESSION_SECRET` on Render. Tell me the password once at the end.
> 5. Detect my OS and install the workstation agent for node 1:
>    - Windows: `agent/install-as-task.ps1 -BotUrl <URL> -AgentToken <TOKEN> -ScriptsRoot <PATH>` where `<PATH>` is my `fortytwo-p2p-inference-scripts-main` folder.
>    - macOS: `agent/install-mac.sh <URL> <TOKEN> <SCRIPTS_ROOT>`.
>    - Linux: `agent/install-linux.sh <URL> <TOKEN> <SCRIPTS_ROOT>`.
> 6. If I have a second node, repeat step 5 with `-NodeId 2 -NodeWallet 0x…`
>    (or the equivalent for Mac/Linux).
> 7. Open `<URL>/dashboard/1`, log in if I set up auth, and confirm
>    the node stats are populating.
> 8. Tell me the dashboard URL (and password if you set one) when done.
>
> Tools required: GitHub access (to fork), terminal access (to install the
> agent), a Render account, and optionally a Neon account. Wallet address
> must come from me — don't guess or auto-generate.

---

## Install

### 1. Deploy the bot

Pick one host — the dashboard is identical either way. Both options are free-tier friendly.

First, generate an `AGENT_TOKEN` you'll reuse across both the bot and the agent:

```bash
# macOS / Linux
openssl rand -hex 20

# Windows (PowerShell)
-join ((48..57)+(97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})
```

#### Render (Blueprint)

1. Fork this repo.
2. Sign up at <https://render.com> (free tier, no card required).
3. In Render, click **New +** → **Blueprint** → connect your fork. Render auto-detects `render.yaml`.
4. Set the env vars Render asks for (`sync: false`):

   | Var | Required | What to put |
   |---|---|---|
   | `WALLET` | yes | Your Monad Testnet operator wallet (`0x…`) |
   | `AGENT_TOKEN` | yes | The shared secret you generated above |
   | `DATABASE_URL` | recommended | Postgres URL — see [Durable storage](#durable-storage-neon-postgres) below. If unset, reward history vanishes on every cold start. |
   | `DASHBOARD_USER`, `DASHBOARD_PASS_HASH`, `SESSION_SECRET` | optional | Set these to lock the dashboard behind a login — see [Dashboard auth](#dashboard-auth-optional) below. |

5. **Apply**. First build is 3–5 min (Docker image build).
6. Verify: open `https://<service>.onrender.com/healthz` — should return `{"ok":true}`.
7. (Optional) **Custom domain**: Render → service → **Settings** → **Custom Domains**.

#### Railway (alternative)

1. Fork this repo.
2. Sign up at <https://railway.app>.
3. **New Project** → **Deploy from GitHub repo** → pick your fork.
4. In the service's **Settings**, set **Root Directory** to `bot`. Railpack scans the repo root by default and can't find the Dockerfile (it lives in `bot/`). The `railway.json` at repo root configures the rest (Dockerfile path, healthcheck, restart policy).
5. **Variables** → add the same env vars from the Render table above.
6. Deploy. First build is 3–5 min.
7. Verify: open `https://<your-app>.up.railway.app/healthz` → `{"ok":true}`.

The agent install step below uses whichever URL your bot ended up on.

### 2. Install the workstation agent

Pick the section matching the OS on the box running your FortyTwo node.

#### Windows

```powershell
cd $env:USERPROFILE
git clone https://github.com/<your-fork>/FortytwoNetworkNode
cd FortytwoNetworkNode\agent
.\install-as-task.ps1 `
    -BotUrl "https://<service>.onrender.com" `
    -AgentToken "<your-agent-token>" `
    -ScriptsRoot "C:\path\to\fortytwo-p2p-inference-scripts-main"
```

Creates a Windows Scheduled Task (`FortytwoBotAgent-Node1`) that runs at logon, restarts on failure, runs indefinitely, and logs to `agent\agent.log`.

Verify pushes:

```powershell
Get-Content $env:USERPROFILE\FortytwoNetworkNode\agent\agent.log -Tail 10 -Wait
```

#### macOS

```bash
cd ~
git clone https://github.com/<your-fork>/FortytwoNetworkNode
cd FortytwoNetworkNode/agent
./install-mac.sh \
    "https://<service>.onrender.com" \
    "<your-agent-token>" \
    "$HOME/path/to/fortytwo-p2p-inference-scripts-main"
```

Writes a launchd plist to `~/Library/LaunchAgents/com.fortytwo.agent.plist`, loads it, restarts at login (`KeepAlive`).

Verify: `tail -f ~/Library/Logs/fortytwo-agent.log`

#### Linux

```bash
cd ~
git clone https://github.com/<your-fork>/FortytwoNetworkNode
cd FortytwoNetworkNode/agent
./install-linux.sh \
    "https://<service>.onrender.com" \
    "<your-agent-token>" \
    "$HOME/path/to/fortytwo-p2p-inference-scripts-main"
```

Writes a **systemd `--user`** unit at `~/.config/systemd/user/fortytwo-agent.service`. For a system-wide install (headless box / unattended server) prepend `FORTYTWO_SYSTEMD_SCOPE=system sudo -E`.

If headless, enable lingering once so the agent survives logout: `loginctl enable-linger $USER`.

Verify: `tail -f ~/.cache/fortytwo-agent.log` (or `journalctl --user -u fortytwo-agent -f`).

#### Docker (FortyTwo node runs in a container)

Pass `-DockerContainer <name>` (Windows) or a 4th positional arg (Mac/Linux) so the agent uses `docker top` / `docker inspect` instead of host `pgrep`. Container needs the Capsule ready port (`42442`) mapped to the host and the scripts/log directory bind-mounted.

```bash
./install-mac.sh "<bot-url>" "<token>" "<bind-mounted-scripts-dir>" "fortytwo-p2p-inference"
```

GPU info still comes from host `nvidia-smi` — works as long as the container has `--gpus all`.

### 3. Open the dashboard

`https://<service>.onrender.com/dashboard` — root redirects to `/dashboard/1`. Bookmark or Add to Home Screen on your phone for an app-like icon.

---

## Optional upgrades

### Durable storage (Neon Postgres)

Render's free tier wipes `/tmp` (where the bot's default SQLite lives) on every cold start and redeploy, so without Postgres your reward history disappears each time. Free Neon takes ~2 min:

1. Sign up at <https://neon.tech> (free, no card).
2. **Create project** in the region closest to your bot's region.
3. Copy the **pooled** connection string — looks like `postgresql://user:pass@ep-xxxx-pooler.<region>.aws.neon.tech/neondb?sslmode=require`.
4. Paste it as `DATABASE_URL` in Render and redeploy.

The bot creates its tables on first boot. No manual schema setup needed. Any standard Postgres URL works — Supabase, self-hosted, whatever.

### Dashboard auth (optional)

By default the dashboard is public to anyone with the URL. Set three env vars to gate it behind a username/password. The **plaintext password never lives on the server** — you store a bcrypt hash and type the real password into a login form.

1. Generate the hash on your local machine:

   ```bash
   python3 -c "import bcrypt, getpass; \
     print(bcrypt.hashpw(getpass.getpass('password: ').encode(), bcrypt.gensalt()).decode())"
   ```

   Prompts hidden, prints a `$2b$…` hash. Copy the hash; save the password in your password manager.

2. Set on Render:

   | Var | What |
   |---|---|
   | `DASHBOARD_USER` | Username (e.g. `admin`) |
   | `DASHBOARD_PASS_HASH` | The `$2b$…` hash from step 1 |
   | `SESSION_SECRET` | Long random string (e.g. `openssl rand -hex 32`). Optional but recommended — without it, sessions invalidate on every redeploy. |

3. Redeploy. Visit `/dashboard/1` and you'll be bounced to the login page. 7-day session; **logout** button in the dashboard header.

To turn auth off: clear `DASHBOARD_USER` and `DASHBOARD_PASS_HASH` and redeploy. The bot logs `WARN: dashboard auth DISABLED …` on every boot while running unprotected.

### Running multiple nodes against one dashboard

Each node gets its own page (`/dashboard/1`, `/dashboard/2`, …) with a tab strip for one-click switching. Both agents push to the same `BotUrl` with the same `AgentToken` — node identity comes from `-NodeId`, and each node sends its own operator wallet via `-NodeWallet`.

Install node 2 alongside node 1:

```powershell
.\install-as-task.ps1 `
    -BotUrl "https://<service>.onrender.com" `
    -AgentToken "<your-agent-token>" `
    -ScriptsRoot "C:\path\to\fortytwo-p2p-inference-scripts-main" `
    -NodeId 2 `
    -NodeWallet "0x<node-2-operator-wallet>"
```

The scheduled task is named `FortytwoBotAgent-Node<N>` so two nodes on one Windows box don't collide. Existing single-node installs keep working unchanged; re-run the installer with `-NodeId 1 -NodeWallet 0x…` to upgrade node 1 (otherwise it falls back to the bot's `WALLET` env var).

---

## Managing the agent

Day-to-day operations on the workstation. The bot side (Render) auto-deploys on every push to `main`.

### Update (pull latest + restart)

Auto-updater handles this every 30 min. Use this for an immediate update:

```powershell
# Windows
cd $env:USERPROFILE\FortytwoNetworkNode
.\agent\update-agent.ps1
```

```bash
# macOS / Linux
cd ~/FortytwoNetworkNode && ./agent/update-agent.sh
```

### Restart / Stop / Start / Status

`<TASK>` below = `FortytwoBotAgent-Node1` (node 1) or `FortytwoBotAgent-Node2` for the second node.

| Op | Windows | macOS | Linux |
|---|---|---|---|
| Restart | `Stop-ScheduledTask <TASK>; Start-ScheduledTask <TASK>` | `launchctl kickstart -k gui/$(id -u)/com.fortytwo.agent` | `systemctl --user restart fortytwo-agent` |
| Stop | `Stop-ScheduledTask <TASK>` | `launchctl unload ~/Library/LaunchAgents/com.fortytwo.agent.plist` | `systemctl --user stop fortytwo-agent` |
| Start | `Start-ScheduledTask <TASK>` | `launchctl load ~/Library/LaunchAgents/com.fortytwo.agent.plist` | `systemctl --user start fortytwo-agent` |
| Status | `Get-ScheduledTaskInfo <TASK>` | `launchctl list \| grep com.fortytwo.agent` | `systemctl --user status fortytwo-agent` |
| Live log | `Get-Content $env:USERPROFILE\FortytwoNetworkNode\agent\agent.log -Tail 20 -Wait` | `tail -f ~/Library/Logs/fortytwo-agent.log` | `tail -f ~/.cache/fortytwo-agent.log` |

You should see a `push ok:` line every heartbeat (~60 s) plus one per inference event, and `auto-update:` lines every 30 min.

### Auto-update

Every **30 min** the agent runs `git ls-remote origin main`; if it differs from local, `git pull --ff-only` and exit so the Scheduled Task / launchd / systemd respawns on the new code.

Change cadence: set `FORTYTWO_AUTOUPDATE_MINUTES=N` (integer minutes; `0` disables). Per-install disable: re-run installer with `-NoAutoUpdate` (Windows) or append `--no-auto-update` to the plist/unit `ExecStart` (Mac/Linux).

**Local modifications** (custom commits): `git pull --ff-only` will fail safely; the agent logs the failure and keeps running. Auto-update never clobbers local work.

---

## Configuration reference

### Bot env vars (Render → Environment)

| Var | Required | Default | Notes |
|---|---|---|---|
| `WALLET` | yes | — | Operator wallet. Service fails to start without it. |
| `AGENT_TOKEN` | yes | — | Shared secret between bot and agent |
| `DATABASE_URL` | recommended | — | Postgres URL. Unset → SQLite at `/tmp` (ephemeral on Render). |
| `DASHBOARD_USER` | optional | — | Set with `DASHBOARD_PASS_HASH` to require login. |
| `DASHBOARD_PASS_HASH` | optional | — | bcrypt hash from the one-liner in [Dashboard auth](#dashboard-auth-optional). |
| `SESSION_SECRET` | optional | random per boot | HMAC key for session cookies. Set it to make sessions survive redeploys. |
| `FOR_CONTRACT` | no | `0xf6B888…6430` | FOR token on Monad Testnet — leave default. |
| `MONAD_RPC_URL` | no | `https://testnet-rpc.monad.xyz/` | Override if rate-limited. |

### Agent params

| Platform | Installer |
|---|---|
| Windows | `install-as-task.ps1 -BotUrl <url> -AgentToken <token> -ScriptsRoot <path> [-NodeId 1] [-NodeWallet 0x…] [-DockerContainer <name>] [-NoAutoUpdate]` |
| macOS | `install-mac.sh <bot-url> <agent-token> <scripts-root> [docker-container]` |
| Linux | `install-linux.sh <bot-url> <agent-token> <scripts-root> [docker-container]` (set `FORTYTWO_SYSTEMD_SCOPE=system` for system-wide install) |

`-ScriptsRoot` / third arg is the path to your local `fortytwo-p2p-inference-scripts-main` directory — that's where `extended_log.txt` and `FortytwoNode/debug/FortytwoCapsule.log` live.

---

## Troubleshooting

**Dashboard shows "No data" after a Render redeploy.** The in-memory snapshot store resets on redeploy. Wait up to 60 s for the next agent heartbeat. Chart bars repopulate from Postgres immediately if `DATABASE_URL` is set.

**Balance card shows `RPC error`.** The default `MONAD_RPC_URL` may be rate-limited. Set it to an alternate RPC endpoint in Render.

**Agent pushes failing with HTTP 401.** Token mismatch — compare `AGENT_TOKEN` in Render against the value the installer used. Re-run the installer with the matching value.

**Can't log in: wrong password.** Cookies are `Secure`, so logging in over plain http won't stick — use the Render HTTPS URL. If you set the hash via `bcrypt.hashpw` make sure the password didn't pick up trailing whitespace from a paste.

**Render free-tier sleep.** Free Web Services sleep after 15 min of inactivity. The agent's heartbeat keeps it awake. If the workstation goes offline > 15 min the first request from a phone/browser eats a ~30 s cold start. Optional: free [UptimeRobot](https://uptimerobot.com) HTTP monitor on `/healthz` every 5 min to keep it hot.

---

## Architecture

- **Bot** (`bot/`) — Python FastAPI service. Receives agent pushes at `POST /v1/status`, serves the dashboard at `GET /dashboard/<id>`, scans Monad Testnet for FOR Transfer events to compute today's authoritative reward total. Persists daily reward totals + per-hour rounds history to Postgres (or SQLite fallback); in-memory snapshot store for the latest live data per node.
- **Agent** (`agent/`) — workstation-resident script. Polls the Capsule log for new inference events on a 5 s tick, pushes a snapshot to the bot on each event plus a regular heartbeat. Maintains a rolling 30-day per-hour rounds buffer locally (`agent/rounds-history.json`); the bot mirrors this into Postgres on every push so it survives a workstation reinstall.
- **Dashboard** (`bot/dashboard_html.py`) — single-file HTML+JS, no build step. Reads `node_id` from the URL path, fetches `/v1/dashboard-data?node=<id>` every 5 s, renders the tab strip / cards / chart from one JSON response. Chart.js for the rounds bar chart.
- **Auth** (`bot/login_html.py` + login routes in `app.py`) — optional. Form-based login, signed session cookie via `itsdangerous`, bcrypt verification. Disabled when env vars are unset.

---

## Contributing

Pre-commit hook at `.githooks/pre-commit` blocks any commit containing non-ASCII characters in a `.ps1` file. PowerShell 5.1 on Windows reads `.ps1` files as cp1252 unless a UTF-8 BOM is present — a single em-dash in a comment can break the parser and take the agent offline (it has, twice).

Enable once per clone:

```bash
git config core.hooksPath .githooks
```

The hook itself is versioned in the repo; this config tells git to use it.

---

## License

[MIT](LICENSE) © 2026 xMassSolutions — see the [LICENSE](LICENSE) file for full text.
