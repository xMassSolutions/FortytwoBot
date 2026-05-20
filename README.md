# FortytwoBot

Telegram bot for monitoring a FortyTwo Network inference node. Two pieces:

- **`bot/`** — deploys to Render (free tier), always-on. Reads FOR balance from Monad Testnet. Receives node-status pushes from the workstation. Responds to Telegram commands.
- **`agent/`** — runs on the Windows workstation that runs the node. Parses node logs every 30 seconds and pushes a snapshot to the bot.

If the workstation goes offline, the bot stays up and `/balance` still works (chain-only). Other commands show "last seen N min ago".

## Commands

| Command | What it shows |
|---|---|
| `/status` | Capsule + Protocol alive, current model, advertised max TPS, last-seen time |
| `/today` | Rounds participated today, rounds observed, errors, first/last round time |
| `/balance` | FOR balance read live from Monad Testnet, plus last reward delta from logs |
| `/recent` | Last 5 inference rounds (completion time, duration, hash) |

## Setup

### 1. Create the Telegram bot

In Telegram, message [@BotFather](https://t.me/BotFather):

```
/newbot
<pick a display name, e.g. "Fortytwo Network: Node Analysis">
<pick a username ending in _bot, e.g. yourbot_bot>
```

Save the token it gives you (looks like `1234567890:AAA-BBB-ccc...`).

### 2. Push the code to GitHub

Already done if you cloned this repo. Otherwise, from the project root:

```powershell
git init
git branch -m main
git add .
git commit -m "initial commit"
gh repo create FortytwoBot --private --source=. --push
```

### 3. Deploy the bot to Render

1. Sign up at <https://render.com> (free tier, no credit card required).
2. **New +** → **Blueprint** → connect the GitHub repo you just pushed. Render will auto-detect `render.yaml`.
3. Render will prompt for the three secret env vars (the ones with `sync: false` in `render.yaml`):
   - `TELEGRAM_TOKEN` — paste the @BotFather token
   - `AGENT_TOKEN` — generate a random 32+ char string and paste (see snippet below)
   - `PUBLIC_URL` — leave blank for now; we'll set it after deploy when we know the URL
4. Click **Apply** / **Create New Resources**. First build takes ~3-5 minutes (Docker image build).

Generate a random AGENT_TOKEN locally:

```powershell
-join ((48..57)+(97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})
```

After the first deploy, the service URL appears at the top of the Render service page — typically `https://fortytwo-network-node-analysis.onrender.com`. Go to **Environment** in the Render dashboard, set `PUBLIC_URL` to that URL, and trigger a **Manual Deploy**.

Register the Telegram webhook (one-time, after `PUBLIC_URL` is set):

```powershell
$AppUrl = "https://fortytwo-network-node-analysis.onrender.com"
$AgentToken = "<the-agent-token-you-pasted-into-render>"
Invoke-WebRequest -Uri "$AppUrl/admin/register-webhook" `
    -Method POST -Headers @{Authorization="Bearer $AgentToken"} -UseBasicParsing | Select-Object -ExpandProperty Content
```

You should see `{"ok":true,"result":true,"description":"Webhook was set"}`. Open your bot in Telegram and send `/balance` — should return your FOR balance from chain even before the agent is installed.

> **Note on Render free tier sleep:** Free Web Services sleep after 15 minutes of inactivity. The workstation agent pushes every 30 s, which keeps it awake. If the workstation goes offline for >15 min, the bot will sleep and the first request from Telegram will have a ~30 s cold start. To prevent sleep entirely, add a free [UptimeRobot](https://uptimerobot.com) HTTP monitor hitting `https://<app>.onrender.com/healthz` every 5 minutes.

### 4. Install the workstation agent

In a regular PowerShell on the same machine running your FortyTwo node:

```powershell
cd C:\Users\youruser\FortytwoBot\agent
.\install-as-task.ps1 -BotUrl "https://fortytwo-network-node-analysis.onrender.com" -AgentToken "$AgentToken"
```

This creates a Windows Scheduled Task that:
- runs at logon
- restarts on failure (3 retries, 1 min apart)
- runs forever (no time limit)
- writes a rolling log to `agent\agent.log`

Verify pushes:

```powershell
Get-Content C:\Users\youruser\FortytwoBot\agent\agent.log -Tail 5 -Wait
```

You should see one `push ok:` line every 30 seconds. In Telegram, `/status` should now return your live node info.

## Configuration reference

### Bot env vars (set in Render dashboard → Environment)

| Var | Required | Default | Notes |
|---|---|---|---|
| `TELEGRAM_TOKEN` | yes | — | From @BotFather |
| `AGENT_TOKEN` | yes | — | Shared secret between bot and agent |
| `PUBLIC_URL` | yes | — | `https://<service>.onrender.com` (no trailing slash) |
| `WALLET` | no | `0xYourMonadTestnetWallet` | Operator wallet to query |
| `FOR_CONTRACT` | no | `0xf6B888f442277F01294F94D555608A2E8Bc86430` | FOR token on Monad Testnet |
| `MONAD_RPC_URL` | no | `https://testnet-rpc.monad.xyz/` | Override if rate-limited |

### Agent params

`install-as-task.ps1 -BotUrl <url> -AgentToken <token> [-TaskName ...] [-ScriptsRoot ...]`

`-ScriptsRoot` defaults to your CLI install at `C:\Users\youruser\FortytwoCLI\fortytwo-p2p-inference-scripts-main` — change if your node lives elsewhere.

## Troubleshooting

**Bot doesn't respond in Telegram.** Open the Render dashboard → service → **Logs** and look for errors. Verify the webhook is registered: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`.

**`/balance` works but `/status`, `/today`, `/recent` say "no status received".** Agent isn't pushing. Check `agent\agent.log`. If empty, the Scheduled Task didn't start — `Get-ScheduledTask FortytwoBotAgent | Get-ScheduledTaskInfo`.

**Agent pushes failing with 401.** Token mismatch. Compare the `AGENT_TOKEN` env var in the Render dashboard against the value in `agent\_agent-wrapper.ps1`.

**`/balance` errors with `RPC error`.** Monad public RPC may be rate-limited. Switch to another endpoint: set `MONAD_RPC_URL` to another RPC in Render's **Environment** tab.

**Workstation reboots.** Bot keeps serving `/balance`. `/status` shows "last seen N min ago" until the workstation comes back and the agent resumes pushing at logon.

## Stop / remove

```powershell
# Stop the agent on your workstation
.\agent\uninstall-task.ps1
```

To remove the bot service: Render dashboard → service → **Settings** → **Delete Service**.
