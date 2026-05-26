import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

import wallets as wstore
from chain import get_for_balance, get_native_balance
from dashboard_html import DASHBOARD_HTML
from db import init_schema, load_rounds_history, upsert_rounds_history
from rewards import get_tracker
from store import Snapshot, store

_HEX_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

log = logging.getLogger("bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

AGENT_TOKEN = os.environ["AGENT_TOKEN"]
WALLET = os.environ["WALLET"]
FOR_CONTRACT = os.environ.get("FOR_CONTRACT", "0xf6B888f442277F01294F94D555608A2E8Bc86430")
MONAD_RPC_URL = os.environ.get("MONAD_RPC_URL", "https://testnet-rpc.monad.xyz/")

# Balance caches — at 5s dashboard refresh × N viewers, hitting Monad RPC every
# request gets us rate-limited. Cache per wallet for 30s. Keyed by lowercased
# operator wallet so two nodes with distinct wallets each get their own slot.
_BALANCE_TTL = 30.0
_balance_cache: dict[str, dict] = {}        # wallet_lc → {value, error, ts}
_monad_balance_cache: dict[str, dict] = {}


# Hard per-request RPC ceiling. The cache absorbs sustained traffic; this just
# guards the cache-miss path against a slow/flaky public RPC. On timeout the
# old cached value is returned with the error annotated so the dashboard stays
# responsive instead of bubbling a network error to the browser.
_RPC_REQUEST_TIMEOUT = 5.0


async def _cached_balance(wallet: str) -> tuple[float | None, str | None]:
    wlc = wallet.lower()
    slot = _balance_cache.setdefault(wlc, {"value": None, "error": None, "ts": 0.0})
    if time.time() - slot["ts"] < _BALANCE_TTL:
        return slot["value"], slot["error"]
    try:
        v = await asyncio.wait_for(
            get_for_balance(MONAD_RPC_URL, FOR_CONTRACT, wallet),
            timeout=_RPC_REQUEST_TIMEOUT,
        )
        slot.update({"value": v, "error": None, "ts": time.time()})
        return v, None
    except Exception as e:
        msg = "timeout" if isinstance(e, asyncio.TimeoutError) else str(e)
        # Don't overwrite a recent good value with a transient error — keep
        # serving the last-known balance while logging the failure.
        slot["error"] = msg
        slot["ts"] = time.time()
        return slot["value"], msg


async def _cached_monad_balance(wallet: str) -> tuple[float | None, str | None]:
    wlc = wallet.lower()
    slot = _monad_balance_cache.setdefault(wlc, {"value": None, "error": None, "ts": 0.0})
    if time.time() - slot["ts"] < _BALANCE_TTL:
        return slot["value"], slot["error"]
    try:
        v = await asyncio.wait_for(
            get_native_balance(MONAD_RPC_URL, wallet),
            timeout=_RPC_REQUEST_TIMEOUT,
        )
        slot.update({"value": v, "error": None, "ts": time.time()})
        return v, None
    except Exception as e:
        msg = "timeout" if isinstance(e, asyncio.TimeoutError) else str(e)
        slot["error"] = msg
        slot["ts"] = time.time()
        return slot["value"], msg


# Background rewards refresher — runs every _BALANCE_TTL seconds independent
# of dashboard requests. Decoupling means a cold-start chain scan (which on
# Monad's public RPC can take 60-90s for the first run) never blocks the
# /v1/dashboard-data response, so the user never sees a network error.
#
# Multi-node: refreshes one tracker per distinct operator wallet seen across
# all known nodes. The server's `WALLET` env var is always included as a
# back-compat default for legacy agents (node-1 without node_wallet pushed).
def _merge_rounds_history(node_id: int, live: dict[str, int] | None) -> dict[str, int]:
    """Merge persisted rounds_history with the agent's current snapshot.
    Live agent value wins per hour (it's >= persisted by DB upsert
    semantics). Returns {} when neither source has anything."""
    try:
        merged: dict[str, int] = dict(load_rounds_history(node_id))
    except Exception as e:  # pragma: no cover -- defensive
        log.warning("load_rounds_history failed for node %d: %s", node_id, e)
        merged = {}
    for k, v in (live or {}).items():
        try:
            v_int = int(v)
        except (TypeError, ValueError):
            continue
        if v_int > merged.get(k, 0):
            merged[k] = v_int
    return merged


def _active_wallets() -> set[str]:
    wallets: set[str] = set()
    for nid in store.known_node_ids():
        w = store.wallet_for(nid)
        if w:
            wallets.add(w.lower())
    if WALLET:
        wallets.add(WALLET.lower())
    return wallets


async def _background_rewards_refresher() -> None:
    while True:
        for w in _active_wallets():
            try:
                await get_tracker(w).refresh(MONAD_RPC_URL, FOR_CONTRACT)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # pragma: no cover — defensive
                log.warning("rewards refresh failed for %s: %s", w, e)
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
    # Numeric node identifier (1, 2, …). Defaults to 1 for legacy agents that
    # don't send the field. Validated as positive int below.
    node_id: int = 1
    # Per-node operator wallet. When omitted, the server falls back to its
    # WALLET env var so an un-upgraded node-1 keeps working unchanged.
    node_wallet: str | None = None
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

    @field_validator("node_id")
    @classmethod
    def _validate_node_id(cls, v: int) -> int:
        if v < 1:
            raise ValueError("node_id must be a positive integer")
        return v

    @field_validator("node_wallet")
    @classmethod
    def _validate_node_wallet(cls, v: str | None) -> str | None:
        if v is not None and not _HEX_ADDR_RE.match(v):
            raise ValueError("node_wallet must be a 0x-prefixed 40-hex address")
        return v


def _require_agent_token(authorization: str | None) -> None:
    if authorization != f"Bearer {AGENT_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid token")


@app.post("/v1/status")
async def v1_status(payload: StatusPayload, authorization: str = Header(None)):
    _require_agent_token(authorization)
    # Cheap node_id-collision detector: incoming wallet doesn't match what's
    # already stored for this node. Surfaces "two agents misconfigured with
    # the same NodeId" without adding any storage or breaking the push.
    existing = store.get(payload.node_id)
    if (existing and existing.node_wallet and payload.node_wallet
            and existing.node_wallet.lower() != payload.node_wallet.lower()):
        log.warning(
            "node_id %d wallet changed: %s -> %s (two agents on same NodeId?)",
            payload.node_id, existing.node_wallet, payload.node_wallet,
        )
    snap = Snapshot(received_at=time.time(), **payload.model_dump())
    store.set(snap)
    # Mirror the agent's rolling per-hour rounds count into the DB so a
    # workstation-side file loss can't blank out yesterday's chart bars.
    # Upsert is MAX-merged in the DB layer, so an under-reporting push
    # can't clobber a higher value.
    try:
        upsert_rounds_history(snap.node_id, snap.rounds_history)
    except Exception as e:  # pragma: no cover -- defensive, never block a push
        log.warning("rounds_history upsert failed for node %d: %s", snap.node_id, e)
    return {"ok": True, "received_at": snap.received_at}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard/1")


@app.get("/dashboard", include_in_schema=False)
async def dashboard_legacy():
    # Keep old bookmarks working. The per-node page lives at /dashboard/{id}.
    return RedirectResponse(url="/dashboard/1")


@app.get("/dashboard/{node_id}", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_node(node_id: int):
    if node_id < 1:
        raise HTTPException(status_code=404, detail="not found")
    # All node pages render the same HTML; the SPA reads node_id from the URL
    # and asks /v1/dashboard-data?node=N for the right snapshot.
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
async def dashboard_data(node: int = 1):
    s = store.get(node)
    # Resolve operator wallet for this node:
    #   - node has snapshot with explicit node_wallet → use that
    #   - node has snapshot but no wallet (legacy agent) → server's WALLET env
    #   - no snapshot yet → None (SPA renders the "no data" state, tabs still work)
    if s is None:
        wallet: str | None = None
    else:
        wallet = s.node_wallet or WALLET

    if wallet:
        balance, balance_error = await _cached_balance(wallet)
        monad_balance, monad_balance_error = await _cached_monad_balance(wallet)
        # Chain-rewards refresh runs in `_background_rewards_refresher`
        # (lifespan task). Reading the summary is in-memory and instant. First
        # few requests after a fresh deploy may see empty data until the
        # background task lands its first successful scan.
        chain_rewards = get_tracker(wallet).summary()
    else:
        balance = monad_balance = None
        balance_error = monad_balance_error = None
        chain_rewards = None

    snapshot_dict = None
    if s:
        if wallet:
            # Chain-side tx_hash backfill: recent Capsule versions stopped
            # logging "Resolution of ... receipt hash 0x..." entirely, so the
            # agent can't pair tx hashes from logs. The tracker matches each
            # round to the nearest on-chain Transfer by timestamp (±60s) and
            # injects the tx_hash. Rounds with a tx_hash already populated by
            # the agent are left untouched. Falls back to passing through
            # untouched if today_transfers is empty.
            recent_rounds = get_tracker(wallet).attach_tx_hashes(
                s.recent_rounds, (s.ts or "")[:10]
            )
            all_rounds_today = get_tracker(wallet).attach_tx_hashes(
                s.all_rounds_today, (s.ts or "")[:10]
            )
        else:
            recent_rounds = s.recent_rounds
            all_rounds_today = s.all_rounds_today
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
            "recent_rounds": recent_rounds,
            "all_rounds_today": all_rounds_today,
            # rounds_history is merged with the DB-persisted record so a
            # workstation that lost agent/rounds-history.json still shows
            # the older per-hour bars on the chart. Live agent values win
            # for the current hour because they're strictly >= persisted
            # (DB upsert is MAX-merged).
            "rounds_history": _merge_rounds_history(node, s.rounds_history),
            "recent_errors": s.recent_errors,
            "log_extended": s.log_extended,
            "log_capsule": s.log_capsule,
        }
    # Always surface 1 and 2 in the tab strip even before either has booted
    # so the user can navigate to the about-to-come-online node.
    known_nodes = sorted(set(store.known_node_ids()) | {1, 2})
    return JSONResponse({
        "snapshot": snapshot_dict,
        "balance": balance,
        "balance_error": balance_error,
        "monad_balance": monad_balance,
        "monad_balance_error": monad_balance_error,
        "chain_rewards": chain_rewards,
        "wallet": wallet,
        "wallet_short": (f"{wallet[:6]}…{wallet[-4:]}" if wallet else None),
        "known_nodes": known_nodes,
    })
