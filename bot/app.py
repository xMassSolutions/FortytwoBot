import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

import wallets as wstore
from chain import get_for_balance, get_native_balance
from dashboard_html import DASHBOARD_HTML
from db import init_schema
from rewards import tracker as rewards_tracker
from store import Snapshot, store

log = logging.getLogger("bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

AGENT_TOKEN = os.environ["AGENT_TOKEN"]
WALLET = os.environ["WALLET"]
FOR_CONTRACT = os.environ.get("FOR_CONTRACT", "0xf6B888f442277F01294F94D555608A2E8Bc86430")
MONAD_RPC_URL = os.environ.get("MONAD_RPC_URL", "https://testnet-rpc.monad.xyz/")

# Balance cache — at 5s dashboard refresh × N viewers, hitting Monad RPC every
# request gets us rate-limited. Cache the operator wallet balances for 30s.
_BALANCE_TTL = 30.0
_balance_cache: dict = {"value": None, "error": None, "ts": 0.0}
_monad_balance_cache: dict = {"value": None, "error": None, "ts": 0.0}


# Hard per-request RPC ceiling. The cache absorbs sustained traffic; this just
# guards the cache-miss path against a slow/flaky public RPC. On timeout the
# old cached value is returned with the error annotated so the dashboard stays
# responsive instead of bubbling a network error to the browser.
_RPC_REQUEST_TIMEOUT = 5.0


async def _cached_balance() -> tuple[float | None, str | None]:
    if time.time() - _balance_cache["ts"] < _BALANCE_TTL:
        return _balance_cache["value"], _balance_cache["error"]
    try:
        v = await asyncio.wait_for(
            get_for_balance(MONAD_RPC_URL, FOR_CONTRACT, WALLET),
            timeout=_RPC_REQUEST_TIMEOUT,
        )
        _balance_cache.update({"value": v, "error": None, "ts": time.time()})
        return v, None
    except Exception as e:
        msg = "timeout" if isinstance(e, asyncio.TimeoutError) else str(e)
        # Don't overwrite a recent good value with a transient error — keep
        # serving the last-known balance while logging the failure.
        _balance_cache["error"] = msg
        _balance_cache["ts"] = time.time()
        return _balance_cache["value"], msg


async def _cached_monad_balance() -> tuple[float | None, str | None]:
    if time.time() - _monad_balance_cache["ts"] < _BALANCE_TTL:
        return _monad_balance_cache["value"], _monad_balance_cache["error"]
    try:
        v = await asyncio.wait_for(
            get_native_balance(MONAD_RPC_URL, WALLET),
            timeout=_RPC_REQUEST_TIMEOUT,
        )
        _monad_balance_cache.update({"value": v, "error": None, "ts": time.time()})
        return v, None
    except Exception as e:
        msg = "timeout" if isinstance(e, asyncio.TimeoutError) else str(e)
        _monad_balance_cache["error"] = msg
        _monad_balance_cache["ts"] = time.time()
        return _monad_balance_cache["value"], msg


# Background rewards refresher — runs every _BALANCE_TTL seconds independent
# of dashboard requests. Decoupling means a cold-start chain scan (which on
# Monad's public RPC can take 60-90s for the first run) never blocks the
# /v1/dashboard-data response, so the user never sees a network error.
async def _background_rewards_refresher() -> None:
    while True:
        try:
            await rewards_tracker.refresh(MONAD_RPC_URL, FOR_CONTRACT, WALLET)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover — defensive
            log.warning("background rewards refresh failed: %s", e)
        await asyncio.sleep(_BALANCE_TTL)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_schema()
    log.info("SQLite schema initialised")
    refresher = asyncio.create_task(_background_rewards_refresher())
    try:
        yield
    finally:
        refresher.cancel()
        try:
            await refresher
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)


class StatusPayload(BaseModel):
    ts: str
    agent_version: str | None = None
    model: str | None = None
    model_short: str | None = None
    model_size_gb: float | None = None
    model_debug: dict | None = None
    capsule_max_tps: int | None = None
    capsule_version: str | None = None
    protocol_version: str | None = None
    capsule_uptime_seconds: int | None = None
    rounds_participated_today: int = 0
    rounds_observed_today: int = 0
    errors_today: int = 0
    first_round_today_iso: str | None = None
    last_round_today_iso: str | None = None
    last_round_duration_s: int | None = None
    last_reward_amount: float | None = None
    last_reward_iso: str | None = None
    rewards_today_total: float | None = None
    wins_today: int = 0
    rewards_logged_today: int = 0
    tps_current: float | None = None
    symbols_current: float | None = None
    max_symbols: float | None = None
    gpu_name: str | None = None
    gpu_vram_used_mb: int | None = None
    gpu_vram_total_mb: int | None = None
    capsule_pid: int | None = None
    protocol_pid: int | None = None
    capsule_alive: bool = False
    protocol_alive: bool = False
    recent_rounds: list[dict] = Field(default_factory=list)
    all_rounds_today: list[dict] = Field(default_factory=list)
    rounds_history: dict[str, int] = Field(default_factory=dict)
    recent_errors: list[dict] = Field(default_factory=list)
    log_extended: list[str] = Field(default_factory=list)
    log_capsule: list[str] = Field(default_factory=list)


def _require_agent_token(authorization: str | None) -> None:
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid token")


@app.post("/v1/status")
async def v1_status(payload: StatusPayload, authorization: str = Header(None)):
    _require_agent_token(authorization)
    snap = Snapshot(received_at=time.time(), **payload.model_dump())
    store.set(snap)
    return {"ok": True, "received_at": snap.received_at}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


class AddWalletPayload(BaseModel):
    address: str
    label: str | None = None


@app.post("/v1/wallets")
async def add_wallet(payload: AddWalletPayload):
    try:
        addr = wstore.add_watched(payload.address, payload.label)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "address": addr}


@app.get("/v1/wallets")
async def list_wallets():
    rows = wstore.list_watched()
    enriched: list[dict] = []
    for w in rows:
        addr = w["address"]
        for_bal = None
        mon_bal = None
        try:
            for_bal = await get_for_balance(MONAD_RPC_URL, FOR_CONTRACT, addr)
        except Exception:
            pass
        try:
            mon_bal = await get_native_balance(MONAD_RPC_URL, addr)
        except Exception:
            pass
        enriched.append({
            "address": addr,
            "label": w.get("label"),
            "added_at": w.get("added_at"),
            "for_balance": for_bal,
            "monad_balance": mon_bal,
            "is_operator": addr.lower() == WALLET.lower(),
        })
    return {"wallets": enriched}


@app.get("/v1/dashboard-data")
async def dashboard_data():
    s = store.latest
    balance, balance_error = await _cached_balance()
    monad_balance, monad_balance_error = await _cached_monad_balance()
    # Chain-rewards refresh runs in `_background_rewards_refresher` (lifespan
    # task). Reading the summary is in-memory and instant. First few requests
    # after a fresh deploy may see empty data until the background task lands
    # its first successful scan.
    chain_rewards = rewards_tracker.summary()

    snapshot_dict = None
    if s:
        snapshot_dict = {
            "received_at": s.received_at,
            "ts": s.ts,
            "agent_version": s.agent_version,
            "model_short": s.model_short,
            "model_size_gb": s.model_size_gb,
            "model_debug": s.model_debug,
            "capsule_max_tps": s.capsule_max_tps,
            "capsule_version": s.capsule_version,
            "protocol_version": s.protocol_version,
            "capsule_uptime_seconds": s.capsule_uptime_seconds,
            "rounds_participated_today": s.rounds_participated_today,
            "rounds_observed_today": s.rounds_observed_today,
            "errors_today": s.errors_today,
            "first_round_today_iso": s.first_round_today_iso,
            "last_round_today_iso": s.last_round_today_iso,
            "last_round_duration_s": s.last_round_duration_s,
            "last_reward_amount": s.last_reward_amount,
            "last_reward_iso": s.last_reward_iso,
            "rewards_today_total": s.rewards_today_total,
            "wins_today": s.wins_today,
            "rewards_logged_today": s.rewards_logged_today,
            "tps_current": s.tps_current,
            "symbols_current": s.symbols_current,
            "max_symbols": s.max_symbols,
            "gpu_name": s.gpu_name,
            "gpu_vram_used_mb": s.gpu_vram_used_mb,
            "gpu_vram_total_mb": s.gpu_vram_total_mb,
            "capsule_pid": s.capsule_pid,
            "protocol_pid": s.protocol_pid,
            "capsule_alive": s.capsule_alive,
            "protocol_alive": s.protocol_alive,
            # Chain-side tx_hash backfill: recent Capsule versions stopped
            # logging "Resolution of ... receipt hash 0x..." entirely, so the
            # agent can't pair tx hashes from logs. The tracker matches each
            # round to the nearest on-chain Transfer by timestamp (±60s) and
            # injects the tx_hash. Rounds with a tx_hash already populated by
            # the agent are left untouched. Falls back to passing through
            # untouched if today_transfers is empty.
            "recent_rounds": rewards_tracker.attach_tx_hashes(
                s.recent_rounds, (s.ts or "")[:10]
            ),
            "all_rounds_today": rewards_tracker.attach_tx_hashes(
                s.all_rounds_today, (s.ts or "")[:10]
            ),
            "rounds_history": s.rounds_history,
            "recent_errors": s.recent_errors,
            "log_extended": s.log_extended,
            "log_capsule": s.log_capsule,
        }
    return JSONResponse({
        "snapshot": snapshot_dict,
        "balance": balance,
        "balance_error": balance_error,
        "monad_balance": monad_balance,
        "monad_balance_error": monad_balance_error,
        "chain_rewards": chain_rewards,
        "wallet": WALLET,
        "wallet_short": f"{WALLET[:6]}…{WALLET[-4:]}",
    })
