# FortytwoBot — FortyTwo Network node monitor

Self-hostable dashboard + workstation agent for monitoring a [FortyTwo Network](https://fortytwo.network/) inference node. Tracks rounds, on-chain FOR rewards on Monad Testnet, TPS, and node health — all in one web dashboard reachable from any device.

## Supported platforms

| Layer | Options |
|---|---|
| **Bot host** | Render · Railway · any Docker host (`bot/Dockerfile`) |
| **Agent OS** | Windows (Scheduled Task) · macOS (launchd) · Linux (systemd) |
| **Node runtime** | Native (`pgrep` / `Get-Process`) · Docker (`docker top` / `docker inspect`) |
| **GPU telemetry** | NVIDIA `nvidia-smi` (primary) · Windows WMI fallback · macOS `system_profiler` |

## What you get

- **FOR balance card** — current FOR + MONAD balance, today's on-chain earned, distributions today, last reward (amount + time), refreshed every 30 s.
- **Node card** — model + size on disk, GPU + VRAM, TPS / symbols/sec (Actual / Max toggle), Capsule + Protocol versions + PIDs, uptime.
- **Today (UTC) card** — rounds participated, observed, errors, in-snapshot reward count, first / last round times.
- **Rounds chart** — 24 h / 7 d / 4 w toggle. Tooltip shows rounds + FOR earned per bucket.
- **Recent rounds** — completion time, duration, round hash, and clickable on-chain tx hash (opens monadscan).
- **Node log** — last 500 lines, **All** / **Events** filter, auto-scrolled to newest.
- **Multi-wallet watch** — FOR + MONAD balances for any Monad Testnet address.
- **Auto-update** — agent self-pulls from `origin/main` every 30 min, restarts on the new code, surfaces the running SHA on the dashboard meta line.

Responsive layout, Add-to-Home-Screen friendly.

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
4. Set the two env vars Render asks for (`sync: false`):

   | Var | Required | What to put |
   |---|---|---|
   | `WALLET` | yes | Your Monad Testnet operator wallet (`0x…`) |
   | `AGENT_TOKEN` | yes | The shared secret you generated above |
   | `DATABASE_URL` | recommended | Postgres connection string ([Neon](#durable-storage-neon-postgres) — see below). If unset, falls back to ephemeral SQLite and yesterday's chart bars vanish on every cold start. |

5. **Apply**. First build is 3–5 min (Docker image build).
6. Verify: open `https://<service>.onrender.com/healthz` — should return `{"ok":true}`.
7. (Optional) **Custom domain**: Render → service → **Settings** → **Custom Domains**.

##### Durable storage (Neon Postgres)

Render's free tier wipes `/tmp` (where the bot's default SQLite lives) on every cold start and redeploy — so without Postgres your reward history disappears each time the service sleeps. Free Neon takes ~2 min to set up:

1. Sign up at <https://neon.tech> (free, no card).
2. **Create project**. Pick the region closest to your Render region.
3. From the project dashboard copy the **pooled** connection string. It looks like `postgresql://user:pass@ep-xxxx-pooler.<region>.aws.neon.tech/neondb?sslmode=require`.
4. Paste it as `DATABASE_URL` in your Render service's env vars and redeploy.

The bot creates its tables on first boot. No manual schema setup needed.

#### Railway (alternative)

1. Fork this repo.
2. Sign up at <https://railway.app>.
3. **New Project** → **Deploy from GitHub repo** → pick your fork.
4. In the service's **Settings**, set **Root Directory** to `bot`. Railpack scans the repo root by default and can't find the Dockerfile (it lives in `bot/`). The `railway.json` at repo root configures the rest (Dockerfile path, healthcheck, restart policy).
5. **Variables** → add `WALLET` and `AGENT_TOKEN` (same values as the Render flow).
6. Deploy. First build is 3–5 min.
7. Verify: open `https://<your-app>.up.railway.app/healthz` → `{"ok":true}`.
8. (Optional) Generate a custom domain under **Settings** → **Networking**.

The agent install step below uses whichever URL your bot ended up on. Both Render and Railway are tested with the same `bot/Dockerfile`.

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

#### Linux

In a terminal on the box running your FortyTwo node:

```bash
cd ~
git clone https://github.com/<your-fork>/FortytwoBot
cd FortytwoBot/agent
./install-linux.sh \
    "https://<service>.onrender.com" \
    "<your-agent-token>" \
    "$HOME/path/to/fortytwo-p2p-inference-scripts-main"
```

This writes a **systemd `--user`** unit at `~/.config/systemd/user/fortytwo-agent.service`, enables it, and starts it. The agent restarts on failure (30 s back-off) and writes logs to `~/.cache/fortytwo-agent.log`.

If the box is headless or you want the agent to survive logout, enable lingering once:

```bash
loginctl enable-linger $USER
```

Verify pushes:

```bash
tail -f ~/.cache/fortytwo-agent.log
# or:
systemctl --user status fortytwo-agent
```

For a **system-wide** install (root, no logged-in user required — useful for unattended servers):

```bash
FORTYTWO_SYSTEMD_SCOPE=system sudo -E ./install-linux.sh <args>
```

Unit lives at `/etc/systemd/system/fortytwo-agent.service`, logs go to `/var/log/fortytwo-agent.log`. Manage with `sudo systemctl …` (no `--user`).

Uninstall:

```bash
systemctl --user disable --now fortytwo-agent
rm ~/.config/systemd/user/fortytwo-agent.service
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

#### Running multiple nodes against one dashboard

Each node gets its own page on the dashboard (`/dashboard/1`, `/dashboard/2`, …) with a tab strip across the top for clicking between them. Both agents push to the same `BotUrl` with the same `AgentToken` — node identity comes from `-NodeId`, and each node sends its own operator wallet via `-NodeWallet`.

**Windows (second node):**

```powershell
.\install-as-task.ps1 `
    -BotUrl "https://<service>.onrender.com" `
    -AgentToken "<your-agent-token>" `
    -ScriptsRoot "C:\path\to\fortytwo-p2p-inference-scripts-main" `
    -NodeId 2 `
    -NodeWallet "0x<node-2-operator-wallet>"
```

The scheduled task is named per-node (`FortytwoBotAgent-Node<N>`) so you can install two on the same Windows box if you really want to. Existing single-node installs keep working unchanged — re-run the installer with `-NodeId 1 -NodeWallet 0x…` to upgrade node 1 into the multi-node setup (otherwise it falls back to the bot's `WALLET` env var).

### 3. Open the dashboard

`https://<service>.onrender.com/dashboard` — works on any browser. Bookmark or Add to Home Screen on your phone for an app-like icon. (Multi-node setups: `/dashboard/1` and `/dashboard/2` — root URL redirects to `/dashboard/1`.)

---

## Managing the agent

Day-to-day operations on the workstation running the agent. The bot side
(Render) auto-deploys on every push to `main` — these commands only affect the
local workstation agent.

### Update (pull latest + restart)

The auto-updater (next section) handles this every 30 min on its own. Use this
command when you want a fix immediately:

**Windows** (admin PowerShell):

```powershell
cd $env:USERPROFILE\FortytwoBot
.\agent\update-agent.ps1
```

The helper script does `git pull`, cleanly ends the scheduled task, kills any
stray `push-agent.ps1` processes, restarts the task, and tails the agent log
so you can confirm the bootstrap push.

**macOS / Linux:**

```bash
cd ~/FortytwoBot
./agent/update-agent.sh
```

The helper script does `git pull` and restarts whichever service is running (launchd on macOS, systemd `--user` or system on Linux), then tails the agent log.

### Restart (no code change)

**Windows:**

```powershell
Stop-ScheduledTask  -TaskName FortytwoBotAgent
Start-ScheduledTask -TaskName FortytwoBotAgent
```

(Or run `.\agent\update-agent.ps1` for the full pull+restart with stray cleanup — it works even when there's nothing to pull.)

**macOS:**

```bash
launchctl kickstart -k gui/$(id -u)/com.fortytwo.agent
```

**Linux** (systemd `--user`):

```bash
systemctl --user restart fortytwo-agent
```

(For system-wide installs: `sudo systemctl restart fortytwo-agent`.)

### Stop

**Windows:**

```powershell
Stop-ScheduledTask -TaskName FortytwoBotAgent
```

**macOS:**

```bash
launchctl unload ~/Library/LaunchAgents/com.fortytwo.agent.plist
```

**Linux:**

```bash
systemctl --user stop fortytwo-agent
```

### Start (after stop)

**Windows:**

```powershell
Start-ScheduledTask -TaskName FortytwoBotAgent
```

**macOS:**

```bash
launchctl load ~/Library/LaunchAgents/com.fortytwo.agent.plist
```

**Linux:**

```bash
systemctl --user start fortytwo-agent
```

### Status (is it running?)

**Windows:**

```powershell
Get-ScheduledTaskInfo -TaskName FortytwoBotAgent
```

Shows `LastRunTime`, `LastTaskResult` (0 = success), and `NextRunTime`.

**macOS:**

```bash
launchctl list | grep com.fortytwo.agent
```

First column is the PID (or `-` if not running); second is the last exit code.

**Linux:**

```bash
systemctl --user status fortytwo-agent
```

Shows current state (active/inactive/failed), PID, recent log lines.

### View live logs

**Windows:**

```powershell
Get-Content $env:USERPROFILE\FortytwoBot\agent\agent.log -Tail 20 -Wait
```

**macOS:**

```bash
tail -f ~/Library/Logs/fortytwo-agent.log
```

**Linux:**

```bash
tail -f ~/.cache/fortytwo-agent.log
# or via journald (system-wide install):
journalctl --user -u fortytwo-agent -f
```

You should see a `push ok:` line every ~5 min (heartbeat) plus an extra one
on each inference event. You'll also see `auto-update:` lines every 30 min
when the cycle runs.

### Auto-update

The agent self-pulls from `origin/main` every **30 minutes** by default. When
a new commit lands, the agent:

1. Runs `git pull --ff-only` in its repo directory.
2. On success, exits — the Scheduled Task / launchd `KeepAlive` respawns
   the agent with the new code within seconds.

You'll see this in `agent.log`:

```
[14:32:01] auto-update: remote a1b2c3d differs from local, pulling…
[14:32:02] auto-update: pulled, exiting to restart with new code
```

**Change the cadence:** set `FORTYTWO_AUTOUPDATE_MINUTES=N` in the environment
(integer minutes; `0` disables). For example, `FORTYTWO_AUTOUPDATE_MINUTES=10`
checks every 10 min.

**Disable per-install:**

- Windows: re-run `install-as-task.ps1` with the `-NoAutoUpdate` switch (or edit the task arguments in Task Scheduler).
- macOS: add `--no-auto-update` to the agent invocation in `~/Library/LaunchAgents/com.fortytwo.agent.plist` and reload it.
- Linux: edit `~/.config/systemd/user/fortytwo-agent.service`, append `--no-auto-update` to `ExecStart`, then `systemctl --user daemon-reload && systemctl --user restart fortytwo-agent`.

**Local modifications** (forked / custom commits): `git pull --ff-only` will
fail safely instead of merging. The agent logs the failure and keeps running
on your current code — auto-update never clobbers local work.

The "Update (pull latest + restart)" command above is still useful when you
want a fix immediately and don't want to wait up to 30 min for the next
auto-update cycle.

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

| Platform | Installer |
|---|---|
| Windows | `install-as-task.ps1 -BotUrl <url> -AgentToken <token> -ScriptsRoot <path> [-TaskName ...] [-NoAutoUpdate]` |
| macOS | `install-mac.sh <bot-url> <agent-token> <scripts-root> [docker-container]` |
| Linux | `install-linux.sh <bot-url> <agent-token> <scripts-root> [docker-container]` (set `FORTYTWO_SYSTEMD_SCOPE=system` for system-wide install) |

`-ScriptsRoot` / third arg is the path to your local `fortytwo-p2p-inference-scripts-main` directory (it's where `extended_log.txt` and `FortytwoNode/debug/FortytwoCapsule.log` live).

---

## Troubleshooting

**Dashboard shows "No data" after a Render redeploy.** The bot's snapshot store is in-memory and resets on redeploy. Wait up to 30 s for the next heartbeat from the agent, or restart it — see [Managing the agent → Restart](#restart-no-code-change).

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

## Contributing

This repo ships a pre-commit hook at `.githooks/pre-commit` that blocks
any commit containing non-ASCII characters in a `.ps1` file. PowerShell 5.1
on Windows reads `.ps1` files as cp1252 unless a UTF-8 BOM is present, so a
single em-dash in a comment can break the parser and take the agent offline
(it has, twice).

Enable the hook **once** in your local clone:

```bash
git config core.hooksPath .githooks
```

(One-time per clone. The hook itself is versioned in the repo and picked up
automatically once this config is set.)

---

## License

[MIT](LICENSE) © 2026 xMassSolutions — see the [LICENSE](LICENSE) file for full text.
