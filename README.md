# FortytwoBot — FortyTwo Network node monitor

A self-hostable dashboard + workstation agent for monitoring a [FortyTwo Network](https://fortytwo.network/) inference node. Tracks rounds, wins/losses, FOR rewards on Monad Testnet, TPS, and node health — all in a single web dashboard you reach from any browser.

```
   ┌──────────────────┐         ┌────────────────────┐
   │ FortyTwo node    │ logs    │ Workstation agent  │ HTTPS push
   │ (Windows / Mac)  │────────▶│ (PowerShell / Py)  │──────────────┐
   └──────────────────┘         └────────────────────┘              │
                                                                    ▼
                                              ┌────────────────────────────┐
                                              │ Bot + dashboard (Render)   │
                                              │ FastAPI + Chart.js         │
                                              │ /dashboard accessible from │
                                              │ any device with the URL    │
                                              └────────────────────────────┘
```

## What you get

- **Live balance card** — FOR balance read from Monad Testnet RPC every 3 min, plus today's earned and wins count.
- **Node card** — process status, capsule/protocol versions, uptime, plus a **Max / Actual** toggle for TPS and symbols-per-second.
- **Today card (UTC)** — rounds participated, observed, errors, W/L counts and win rate.
- **Rounds chart** — toggleable 24-hour, 7-day, or 4-week view of participation.
- **Recent rounds, last 3 errors, last 100 log lines** — each in its own card.
- **Multi-wallet watch** — track FOR + MONAD balances on any address.

The dashboard URL works on phones, tablets, and desktops (responsive layout, Add-to-Home-Screen for app-like access).

---

## Quick install (AI agent)

If you have a coding agent with tool use (Claude, ChatGPT-with-tools, etc.), paste this prompt and it should handle the whole install:

> Install the FortyTwo Network node monitoring stack from
> `https://github.com/<your-fork>/FortytwoBot` for me.
>
> Steps:
> 1. Fork the repo to my GitHub account if I haven't already.
> 2. Deploy the `bot/` service to my Render account using the blueprint at
>    `render.yaml`. Prompt me for `WALLET` (my Monad Testnet operator wallet)
>    and generate a random 40-char `AGENT_TOKEN`.
> 3. Detect my OS and install the workstation agent:
>    - Windows: run `agent/install-as-task.ps1 -BotUrl <URL> -AgentToken <TOKEN> -ScriptsRoot <PATH>` where `<PATH>` points at my `fortytwo-p2p-inference-scripts-main` folder.
>    - macOS: run `agent/install-mac.sh <URL> <TOKEN> <SCRIPTS_ROOT>`.
> 4. Open `<URL>/dashboard` and confirm the node stats are populating.
> 5. Tell me the dashboard URL when done.
>
> Tools required: GitHub access (to fork), terminal access (to install the agent),
> and a Render account (browser or API). Wallet address must come from me — don't
> guess or auto-generate.

The block is informational — copy it into another LLM session if you want the install done for you. The manual steps below cover the same ground.

---

## Manual install

### 1. Deploy the bot to Render

1. Fork this repo to your GitHub account.
2. Sign up at <https://render.com> (free tier, no card required).
3. In Render, click **New +** → **Blueprint** → connect your forked repo. Render auto-detects `render.yaml`.
4. Render will prompt you for these env vars (all marked `sync: false` so you set them per deploy):

   | Var | Required | What to put |
   |---|---|---|
   | `WALLET` | yes | Your Monad Testnet operator wallet (`0x…`) |
   | `AGENT_TOKEN` | yes | Random 32+ char shared secret — generate one |

   Generate an `AGENT_TOKEN`:

   ```bash
   # macOS / Linux
   openssl rand -hex 20

   # Windows (PowerShell)
   -join ((48..57)+(97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})
   ```

5. **Apply**. First build is 3–5 min (Docker image build).
6. Verify: open `https://<service>.onrender.com/healthz` — should return `{"ok":true}`.
7. (Optional) **Custom domain**: in Render → service → **Settings** → **Custom Domains**, add your domain. Render gives you the DNS records to configure with your registrar.

### 2. Install the workstation agent

#### Windows

In PowerShell on the machine running your FortyTwo node:

```powershell
cd $env:USERPROFILE
git clone https://github.com/<your-fork>/FortytwoBot
cd FortytwoBot\agent
.\install-as-task.ps1 `
    -BotUrl "https://<service>.onrender.com" `
    -AgentToken "<your-agent-token>" `
    -ScriptsRoot "C:\path\to\fortytwo-p2p-inference-scripts-main"
```

This creates a Windows Scheduled Task that:
- runs at logon
- restarts on failure (3 retries, 1 min apart)
- runs indefinitely (no time limit)
- writes a rolling log to `agent\agent.log`

Verify pushes:

```powershell
Get-Content $env:USERPROFILE\FortytwoBot\agent\agent.log -Tail 10 -Wait
```

Expect a `push ok:` line every ~30 seconds (or every 10 minutes when idle).

#### macOS

In Terminal on the machine running your FortyTwo node:

```bash
cd ~
git clone https://github.com/<your-fork>/FortytwoBot
cd FortytwoBot/agent
./install-mac.sh \
    "https://<service>.onrender.com" \
    "<your-agent-token>" \
    "$HOME/path/to/fortytwo-p2p-inference-scripts-main"
```

This writes a launchd plist to `~/Library/LaunchAgents/com.fortytwo.agent.plist`, loads it, and starts pushing. The agent restarts at login and survives crashes (`KeepAlive`).

Verify pushes:

```bash
tail -f ~/Library/Logs/fortytwo-agent.log
```

Uninstall:

```bash
./uninstall-mac.sh
```

#### Docker (FortyTwo node runs in a container)

If you run the node via Docker (e.g., the official [`fortytwo-p2p-inference-docker`](https://github.com/Fortytwo-Network/fortytwo-p2p-inference-docker) image), pass the container name so the agent uses `docker top` / `docker inspect` for process detection instead of host `pgrep` / `Get-Process`. The agent still runs natively on the host — it just queries Docker.

Requirements:
- The Docker container must expose the Capsule ready port (default `42442`) on the host (`-p 42442:42442` in `docker run`, or `ports:` in compose).
- Bind-mount the scripts/log directory so the host can read `extended_log.txt` and `FortytwoNode/debug/FortytwoCapsule.log` (or symlink them to a host path).
- The user running the agent needs permission to call `docker` (group `docker` on Linux, or admin on Windows).

**Windows:**

```powershell
.\install-as-task.ps1 `
    -BotUrl "https://<service>.onrender.com" `
    -AgentToken "<your-agent-token>" `
    -ScriptsRoot "C:\path\to\bind-mounted\scripts" `
    -DockerContainer "fortytwo-p2p-inference"
```

**macOS / Linux:**

```bash
./install-mac.sh \
    "https://<service>.onrender.com" \
    "<your-agent-token>" \
    "$HOME/path/to/bind-mounted/scripts" \
    "fortytwo-p2p-inference"
```

The 4th positional argument is the container name. Leave it out for native (non-Docker) installs.

Caveats in Docker mode:
- `capsule_uptime_seconds` reports **container uptime** (proxy for Capsule uptime). If the Capsule restarts inside a long-running container, this won't reset.
- GPU info still comes from host `nvidia-smi`. Works if the container uses `--gpus all` — `nvidia-smi` on the host sees all GPU activity (host + containers).
- `capsule_alive` is determined by HTTP ready probe (same as native), so it's accurate as long as the ready port is mapped.

### 3. Open the dashboard

`https://<service>.onrender.com/dashboard` — works on any browser. Bookmark or Add to Home Screen on your phone for an app-like icon.

---

## Configuration

### Bot env vars (set in Render → Environment)

| Var | Required | Default | Notes |
|---|---|---|---|
| `WALLET` | yes | — | Your operator wallet. App fails to start without it. |
| `AGENT_TOKEN` | yes | — | Shared secret between bot and agent |
| `FOR_CONTRACT` | no | `0xf6B888…6430` | FOR token on Monad Testnet — leave default |
| `MONAD_RPC_URL` | no | `https://testnet-rpc.monad.xyz/` | Override if rate-limited |

### Agent params

`install-as-task.ps1 -BotUrl <url> -AgentToken <token> -ScriptsRoot <path> [-TaskName ...]`

`install-mac.sh <bot-url> <agent-token> <scripts-root>`

`-ScriptsRoot` / third arg is the path to your local `fortytwo-p2p-inference-scripts-main` directory (it's where `extended_log.txt` and `FortytwoNode/debug/FortytwoCapsule.log` live).

---

## Troubleshooting

**Dashboard shows "No data" after a Render redeploy.** The bot's snapshot store is in-memory and resets on redeploy. Wait up to 10 min for the next heartbeat from the agent, or restart the agent:

```powershell
# Windows
Restart-ScheduledTask -TaskName FortytwoBotAgent
```

```bash
# macOS
launchctl kickstart -k gui/$(id -u)/com.fortytwo.agent
```

**Balance card shows `RPC error`.** The default `MONAD_RPC_URL` may be rate-limited. Set it to an alternate RPC endpoint in the Render dashboard.

**Agent pushes failing with HTTP 401.** Token mismatch. Compare `AGENT_TOKEN` in Render → Environment against the value the agent install scripts used. Re-run the installer with the matching value.

**Bot deploy fails with `KeyError: 'WALLET'`.** You haven't set the `WALLET` env var in Render. Add it under Environment and trigger a Manual Deploy.

**Workstation reboots.** Bot keeps serving the live FOR balance from chain. Dashboard shows "last seen N min ago" until the workstation comes back and the agent resumes at logon (Win) or login (Mac).

**Render free-tier sleep.** Free Web Services sleep after 15 min of inactivity. The 10-min heartbeat from the agent keeps it awake. If the workstation goes offline for > 15 min the bot will sleep and the first request from a phone/browser will have a ~30s cold start. Optional: free [UptimeRobot](https://uptimerobot.com) HTTP monitor on `/healthz` every 5 min to keep it hot.

---

## Architecture

- **Bot** (`bot/`) — Python FastAPI service on Render. Receives agent pushes at `POST /v1/status`, serves the dashboard at `GET /dashboard`, reads on-chain balance from Monad Testnet for the balance card. State is in-memory (`bot/store.py`); the only persistent storage is a tiny SQLite for the dashboard's multi-wallet watch list.

- **Agent** (`agent/`) — workstation-resident script. Polls `extended_log.txt` for new inference events (5s tick), pushes a snapshot to the bot via HTTPS on each event, plus a 10-minute heartbeat. Maintains a rolling 30-day hourly-rounds buffer in `rounds-history.json` next to the script (survives bot redeploys; lost only on workstation reformat).

- **Dashboard** (`bot/dashboard_html.py`) — single-file HTML+JS. Fetches `/v1/dashboard-data` every 3 min. Chart.js bar chart with 24h/7d/4w toggle. No build step.

---

## Stop / remove

```powershell
# Windows
.\agent\uninstall-task.ps1
```

```bash
# macOS
./agent/uninstall-mac.sh
```

To remove the bot service: Render dashboard → service → **Settings** → **Delete Service**.

---

## License

TBD.
