import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from chain import get_for_balance
from store import Snapshot, store

log = logging.getLogger("bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
AGENT_TOKEN = os.environ["AGENT_TOKEN"]
WALLET = os.environ.get("WALLET", "0xYourMonadTestnetWallet")
FOR_CONTRACT = os.environ.get("FOR_CONTRACT", "0xf6B888f442277F01294F94D555608A2E8Bc86430")
MONAD_RPC_URL = os.environ.get("MONAD_RPC_URL", "https://testnet-rpc.monad.xyz/")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
WEBHOOK_PATH = "/telegram/webhook"

application: Application | None = None


def fmt_for(n: float) -> str:
    return f"{n:,.2f}"


def fmt_ago(ts_epoch: float | None) -> str:
    if not ts_epoch:
        return "never"
    delta = time.time() - ts_epoch
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h {int((delta % 3600) / 60)}m ago"
    return f"{int(delta / 86400)}d ago"


def short_addr(addr: str) -> str:
    return f"{addr[:6]}…{addr[-4:]}"


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = store.latest
    if not s:
        await update.message.reply_text(
            "No status received yet — the workstation agent hasn't pushed."
        )
        return
    alive = "✅ ALIVE" if s.capsule_alive and s.protocol_alive else "❌ DOWN"
    model = s.model_short or "—"
    msg = (
        f"*Node:* {alive}\n"
        f"*Model:* `{model}`\n"
        f"*Max TPS:* {s.capsule_max_tps or '—'}\n"
        f"*Capsule PID:* {s.capsule_pid or '—'}  "
        f"*Protocol PID:* {s.protocol_pid or '—'}\n"
        f"*Last seen:* {fmt_ago(s.received_at)}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_today(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = store.latest
    if not s:
        await update.message.reply_text("No status received yet.")
        return
    msg = (
        "*Today (UTC)*\n"
        f"Rounds participated: *{s.rounds_participated_today}*\n"
        f"Rounds observed: {s.rounds_observed_today}\n"
        f"Errors: {s.errors_today}\n"
        f"First round: {s.first_round_today_iso or '—'}\n"
        f"Last round: {s.last_round_today_iso or '—'}\n"
        f"_Last seen {fmt_ago(s.received_at)}_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_balance(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        bal = await get_for_balance(MONAD_RPC_URL, FOR_CONTRACT, WALLET)
    except Exception as e:
        log.exception("balance lookup failed")
        await update.message.reply_text(f"RPC error: {e}")
        return
    s = store.latest
    extra = ""
    if s and s.last_reward_amount is not None:
        extra = (
            f"\n*Last reward:* +{fmt_for(s.last_reward_amount)} FOR "
            f"({s.last_reward_iso or '—'} UTC)"
        )
    msg = (
        f"*Wallet:* `{short_addr(WALLET)}` (Monad Testnet)\n"
        f"*FOR balance:* *{fmt_for(bal)}*"
        f"{extra}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_recent(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = store.latest
    if not s or not s.recent_rounds:
        await update.message.reply_text("No round history received yet.")
        return
    lines = ["*Last 5 rounds*"]
    for r in s.recent_rounds[:5]:
        h = (r.get("hash") or "")[:8]
        t = r.get("completed_iso") or ""
        d = r.get("duration_s") or 0
        lines.append(f"`{t}`  {d}s  `{h}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("balance", cmd_balance))
    application.add_handler(CommandHandler("recent", cmd_recent))
    await application.initialize()
    await application.start()
    log.info("Telegram application started")
    try:
        yield
    finally:
        await application.stop()
        await application.shutdown()


app = FastAPI(lifespan=lifespan)


class StatusPayload(BaseModel):
    ts: str
    model: str | None = None
    model_short: str | None = None
    capsule_max_tps: int | None = None
    rounds_participated_today: int = 0
    rounds_observed_today: int = 0
    errors_today: int = 0
    first_round_today_iso: str | None = None
    last_round_today_iso: str | None = None
    last_round_duration_s: int | None = None
    last_reward_amount: float | None = None
    last_reward_iso: str | None = None
    capsule_pid: int | None = None
    protocol_pid: int | None = None
    capsule_alive: bool = False
    protocol_alive: bool = False
    recent_rounds: list[dict] = Field(default_factory=list)


def _require_agent_token(authorization: str | None) -> None:
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid token")


@app.post("/v1/status")
async def v1_status(payload: StatusPayload, authorization: str = Header(None)):
    _require_agent_token(authorization)
    snap = Snapshot(received_at=time.time(), **payload.model_dump())
    store.set(snap)
    return {"ok": True, "received_at": snap.received_at}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if application is None:
        raise HTTPException(503, "application not ready")
    body = await request.json()
    update = Update.de_json(body, application.bot)
    await application.process_update(update)
    return {"ok": True}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/admin/register-webhook")
async def register_webhook(authorization: str = Header(None)):
    _require_agent_token(authorization)
    if not PUBLIC_URL:
        raise HTTPException(500, "PUBLIC_URL env not set")
    url = PUBLIC_URL + WEBHOOK_PATH
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook",
            json={"url": url},
        )
    return r.json()
