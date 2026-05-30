import asyncio
import hmac
import logging
import os
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

import bcrypt
import httpx
from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel, Field, field_validator

import wallets as wstore
from chain import get_for_balance, get_native_balance
from dashboard_html import DASHBOARD_HTML
from overview_html import OVERVIEW_HTML
from db import (
    add_energy,
    init_schema,
    insert_uptime_sample,
    load_energy_since,
    load_round_tx,
    load_rounds,
    load_rounds_history,
    load_uptime_samples_since,
    prune_energy_daily_older_than,
    prune_uptime_samples_older_than,
    today_round_summary,
    upsert_rounds,
    upsert_rounds_history,
)
from login_html import LOGIN_HTML
from rewards import get_tracker, projections as _projections
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
# FortyTwo public leaderboard (AWS gateway) -- resolves each node's three-word
# name by operator wallet. Env-overridable in case FortyTwo moves the host.
FORTYTWO_LEADERBOARD_URL = os.environ.get(
    "FORTYTWO_LEADERBOARD_URL",
    "https://8vcuob4bv8.execute-api.us-east-2.amazonaws.com/leaderboard_v2",
)

# --- Dashboard login -------------------------------------------------------
# Opt-in: when both DASHBOARD_USER and DASHBOARD_PASS_HASH are set, the
# dashboard pages and /v1/dashboard-data require a signed session cookie.
# The plaintext password is NEVER stored server-side -- only the bcrypt
# hash lives in env. Generate the hash locally with:
#   python3 -c "import bcrypt,getpass; \
#     print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "").strip()
DASHBOARD_PASS_HASH = os.environ.get("DASHBOARD_PASS_HASH", "").strip()
AUTH_ENABLED = bool(DASHBOARD_USER and DASHBOARD_PASS_HASH)

# Session cookies are HMAC-signed with this key. Setting it explicitly in
# Render lets sessions survive a redeploy; if unset we generate a fresh
# random key per boot so the cookies stay tamper-proof but invalidate
# every restart.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").strip() or secrets.token_hex(32)
_SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days
_SIGNER = TimestampSigner(SESSION_SECRET)
# Whether to mark cookies Secure. False for plain-http local dev; defaults
# True since production is HTTPS-only on Render.
_COOKIE_SECURE = os.environ.get("COOKIE_INSECURE", "").lower() not in ("1", "true", "yes")

# --- /login brute-force rate-limit ----------------------------------------
# Sliding window per client IP. When a single IP racks up
# LOGIN_RATE_LIMIT_MAX failed POST /login attempts inside
# LOGIN_RATE_LIMIT_WINDOW_SECS, further attempts get a 429 + Retry-After
# until the oldest failure ages out. Successful logins clear the counter.
# In-memory only — fine for the free-tier single-instance deploy; resets
# on redeploy, which is acceptable for a brute-force defense.
LOGIN_RATE_LIMIT_MAX = int(os.environ.get("LOGIN_RATE_LIMIT_MAX", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECS = int(os.environ.get("LOGIN_RATE_LIMIT_WINDOW_SECS", "900"))
_login_failures: dict[str, deque] = {}

# Balance caches — at 5s dashboard refresh × N viewers, hitting Monad RPC every
# request gets us rate-limited. Cache per wallet for 30s. Keyed by lowercased
# operator wallet so two nodes with distinct wallets each get their own slot.
_BALANCE_TTL = 30.0
_balance_cache: dict[str, dict] = {}        # wallet_lc → {value, error, ts}
_monad_balance_cache: dict[str, dict] = {}

# Today-card summary cache. The "Today" doughnut reads authoritative
# participated/rewarded counts from the durable rounds table; cache per node so
# the 5s dashboard poll doesn't hit Postgres on every request.
_TODAY_TTL = 30.0
_today_cache: dict[int, dict] = {}          # node_id → {data, ts}


def _today_summary(node: int) -> dict | None:
    """Cached authoritative {participated, rewarded} for the node's Today
    doughnut (~30s TTL). On DB error returns the last good value, else None."""
    now = time.time()
    slot = _today_cache.get(node)
    if slot and now - slot["ts"] < _TODAY_TTL:
        return slot["data"]
    try:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        data = today_round_summary(node, day)
    except Exception as e:
        log.warning("today summary failed for node %d: %s", node, e)
        return slot["data"] if slot else None
    _today_cache[node] = {"data": data, "ts": now}
    return data


# Power/energy summary for the chart card. current_kw is live (from the
# snapshot); the kWh windows come from the energy_daily rollup, cached ~30s.
_POWER_TTL = 30.0
_power_cache: dict[int, dict] = {}          # node_id → {windows, ts}


def _power_summary(node: int) -> dict:
    """{current_kw, kwh_today, kwh_7d, kwh_4w}. current_kw = live GPU draw in kW
    (None if not reported); kWh windows summed from energy_daily (cached)."""
    snap = store.get(node)
    current_kw = (round(snap.gpu_power_w / 1000.0, 3)
                  if snap is not None and snap.gpu_power_w else None)
    now = time.time()
    slot = _power_cache.get(node)
    if slot and now - slot["ts"] < _POWER_TTL:
        windows = slot["windows"]
    else:
        try:
            since = time.strftime("%Y-%m-%d", time.gmtime(now - 27 * 24 * 3600))
            by_date = {r["utc_date"]: r["kwh"] for r in load_energy_since(node, since)}
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            d7 = time.strftime("%Y-%m-%d", time.gmtime(now - 6 * 24 * 3600))
            windows = {
                "kwh_today": round(by_date.get(today, 0.0), 3),
                "kwh_7d": round(sum(v for d, v in by_date.items() if d >= d7), 3),
                "kwh_4w": round(sum(by_date.values()), 3),
            }
            _power_cache[node] = {"windows": windows, "ts": now}
        except Exception as e:
            log.warning("power summary failed for node %d: %s", node, e)
            windows = slot["windows"] if slot else {"kwh_today": 0.0, "kwh_7d": 0.0, "kwh_4w": 0.0}
    return {"current_kw": current_kw, **windows}


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


# Node-name cache. FortyTwo assigns each node a stable three-word name; we
# resolve it from the public leaderboard by operator wallet. Names ~never
# change, so cache success for hours; cache failures briefly so a flaky fetch
# can't hammer their API or spam retries. Keyed by lowercased wallet.
_NODE_NAME_TTL_OK = 6 * 3600.0
_NODE_NAME_TTL_ERR = 300.0
_node_name_cache: dict[str, dict] = {}      # wallet_lc → {name, ts, ok}


async def _cached_node_name(wallet: str | None) -> str | None:
    """Resolve a node's FortyTwo three-word name from the public leaderboard,
    matched by operator wallet (the `participant` field where `original` == the
    wallet). Cached long on success / short on failure; any error → None so the
    dashboard falls back to 'Node N'."""
    if not wallet:
        return None
    wlc = wallet.lower()
    now = time.time()
    slot = _node_name_cache.get(wlc)
    if slot and now - slot["ts"] < (_NODE_NAME_TTL_OK if slot["ok"] else _NODE_NAME_TTL_ERR):
        return slot["name"]
    try:
        async with httpx.AsyncClient(timeout=_RPC_REQUEST_TIMEOUT) as client:
            r = await client.get(
                FORTYTWO_LEADERBOARD_URL,
                params={"period": "all_time", "wallet_filter": wlc},
            )
            r.raise_for_status()
            results = (r.json() or {}).get("results") or []
        name = next(
            (row.get("participant") for row in results
             if str(row.get("original", "")).lower() == wlc),
            (results[0].get("participant") if results else None),
        ) or None
        _node_name_cache[wlc] = {"name": name, "ts": now, "ok": True}
        return name
    except Exception as e:
        log.warning("node name fetch failed for %s: %s", wlc, e)
        _node_name_cache[wlc] = {"name": slot["name"] if slot else None, "ts": now, "ok": False}
        return slot["name"] if slot else None


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


def _verify_session_cookie(token: str | None) -> bool:
    """Return True iff `token` is a signed-by-us cookie whose payload equals
    the configured DASHBOARD_USER and whose timestamp is within
    _SESSION_MAX_AGE. False on tamper, expiry, or any decode error."""
    if not token:
        return False
    try:
        payload = _SIGNER.unsign(token, max_age=_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return payload.decode() == DASHBOARD_USER


def require_login(session: str | None = Cookie(default=None)) -> None:
    """FastAPI dependency for HTML routes: 303 to /login when not authed."""
    if not AUTH_ENABLED:
        return
    if not _verify_session_cookie(session):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def require_login_json(session: str | None = Cookie(default=None)) -> None:
    """Same as require_login but 401 (no redirect) -- right for JSON
    endpoints so the dashboard SPA can detect it and navigate itself."""
    if not AUTH_ENABLED:
        return
    if not _verify_session_cookie(session):
        raise HTTPException(status_code=401, detail="not logged in")


def _issue_session_cookie(resp: Response) -> None:
    token = _SIGNER.sign(DASHBOARD_USER.encode()).decode()
    resp.set_cookie(
        "session", token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        path="/",
    )


def _client_ip(request: Request) -> str:
    # Behind Render's proxy uvicorn is launched with --proxy-headers, so
    # request.client.host already reflects X-Forwarded-For's first hop.
    return (request.client.host if request.client else "") or "unknown"


def _login_blocked_seconds(ip: str) -> int:
    """0 if this IP can attempt now; else seconds until the next slot frees.
    Side-effect: evicts expired failure timestamps from the per-IP deque."""
    if LOGIN_RATE_LIMIT_MAX <= 0 or LOGIN_RATE_LIMIT_WINDOW_SECS <= 0:
        return 0
    now = time.time()
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECS
    dq = _login_failures.get(ip)
    if not dq:
        return 0
    while dq and dq[0] < cutoff:
        dq.popleft()
    if not dq:
        _login_failures.pop(ip, None)
        return 0
    if len(dq) < LOGIN_RATE_LIMIT_MAX:
        return 0
    return max(1, int(dq[0] + LOGIN_RATE_LIMIT_WINDOW_SECS - now))


def _login_record_failure(ip: str) -> None:
    _login_failures.setdefault(ip, deque()).append(time.time())


def _login_record_success(ip: str) -> None:
    _login_failures.pop(ip, None)


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


# --- Uptime sampler -------------------------------------------------------
# Every UPTIME_SAMPLE_INTERVAL_SECS, snapshot per-node alive-ness into the
# uptime_samples table. "Alive" = the agent pushed within the last
# UPTIME_STALE_AFTER_SECS. From the samples we compute rolling 24h / 7d
# uptime percentages for the dashboard.
UPTIME_STALE_AFTER_SECS = int(os.environ.get("UPTIME_STALE_AFTER_SECS", "90"))
UPTIME_SAMPLE_INTERVAL_SECS = int(os.environ.get("UPTIME_SAMPLE_INTERVAL_SECS", "60"))
UPTIME_RETENTION_DAYS = int(os.environ.get("UPTIME_RETENTION_DAYS", "7"))
_UPTIME_PRUNE_EVERY_SECS = 3600.0  # once an hour is plenty


def _is_alive(snap: Snapshot | None, now: float) -> bool:
    if snap is None or snap.received_at is None:
        return False
    return (now - float(snap.received_at)) < UPTIME_STALE_AFTER_SECS


def _uptime_for_node(node_id: int, now: float | None = None) -> dict[str, Any]:
    """Roll up samples into 24h / 7d percentages. Returns None-shaped values
    when there's not enough history to make a number meaningful, so the
    client can render a placeholder instead of a misleading 100%."""
    if now is None:
        now = time.time()
    window_24h = 24 * 3600.0
    window_7d = 7 * 24 * 3600.0
    since = now - window_7d
    samples = load_uptime_samples_since(node_id, since)
    pct_24h: float | None = None
    pct_7d: float | None = None
    n_24h = 0
    n_7d = len(samples)
    if n_7d > 0:
        alive_7d = sum(1 for s in samples if s["alive"])
        pct_7d = round(100.0 * alive_7d / n_7d, 2)
    cutoff_24h = now - window_24h
    samples_24h = [s for s in samples if s["ts"] >= cutoff_24h]
    n_24h = len(samples_24h)
    if n_24h > 0:
        alive_24h = sum(1 for s in samples_24h if s["alive"])
        pct_24h = round(100.0 * alive_24h / n_24h, 2)
    return {
        "pct_24h": pct_24h,
        "pct_7d": pct_7d,
        "samples_24h": n_24h,
        "samples_7d": n_7d,
        "alive_now": _is_alive(store.get(node_id), now),
        "stale_after_secs": UPTIME_STALE_AFTER_SECS,
    }


async def _background_uptime_sampler() -> None:
    """Once per UPTIME_SAMPLE_INTERVAL_SECS, write one (node, ts, alive)
    row per known node. Prunes rows older than retention every hour."""
    if UPTIME_SAMPLE_INTERVAL_SECS <= 0:
        log.info("uptime sampler disabled (UPTIME_SAMPLE_INTERVAL_SECS<=0)")
        return
    last_prune = 0.0
    while True:
        try:
            now = time.time()
            # Sample any node we've ever seen. Skipping store.known_node_ids()
            # cold (no snapshots) means a node's uptime ledger begins at its
            # first push -- which is exactly what we want, otherwise we'd
            # backfill "0% for the last 7d" for a node that just came online.
            for nid in store.known_node_ids():
                snap = store.get(nid)
                alive = _is_alive(snap, now)
                try:
                    insert_uptime_sample(nid, now, alive)
                except Exception as e:  # pragma: no cover -- defensive
                    log.warning("uptime sample insert failed for node %d: %s", nid, e)
                # Accrue energy: integrate the node's reported GPU watts over this
                # tick, but only while it's up AND actually reporting power.
                if alive and snap is not None and snap.gpu_power_w:
                    try:
                        add_energy(nid, time.strftime("%Y-%m-%d", time.gmtime(now)),
                                   snap.gpu_power_w * UPTIME_SAMPLE_INTERVAL_SECS / 3.6e6, now)
                    except Exception as e:  # pragma: no cover -- defensive
                        log.warning("energy accrue failed for node %d: %s", nid, e)
            if (now - last_prune) >= _UPTIME_PRUNE_EVERY_SECS:
                cutoff = now - UPTIME_RETENTION_DAYS * 24 * 3600.0
                try:
                    deleted = prune_uptime_samples_older_than(cutoff)
                    if deleted:
                        log.info("uptime sampler: pruned %d rows older than %dd",
                                 deleted, UPTIME_RETENTION_DAYS)
                except Exception as e:  # pragma: no cover
                    log.warning("uptime prune failed: %s", e)
                try:
                    prune_energy_daily_older_than(
                        time.strftime("%Y-%m-%d", time.gmtime(now - 35 * 24 * 3600)))
                except Exception as e:  # pragma: no cover
                    log.warning("energy prune failed: %s", e)
                last_prune = now
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover -- never let the loop die
            log.warning("uptime sampler tick failed: %s", e)
        await asyncio.sleep(UPTIME_SAMPLE_INTERVAL_SECS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_schema()
    log.info("SQLite schema initialised")
    if AUTH_ENABLED:
        log.info("dashboard auth ENABLED (user=%s)", DASHBOARD_USER)
    else:
        log.warning("dashboard auth DISABLED -- set DASHBOARD_USER and "
                    "DASHBOARD_PASS_HASH to lock down the dashboard")
    if not os.environ.get("SESSION_SECRET", "").strip():
        log.warning("SESSION_SECRET unset -- sessions invalidate on every "
                    "restart (set it in Render to make sessions sticky)")
    refresher = asyncio.create_task(_background_rewards_refresher())
    sampler = asyncio.create_task(_background_uptime_sampler())
    try:
        yield
    finally:
        for t in (refresher, sampler):
            t.cancel()
        for t in (refresher, sampler):
            try:
                await t
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
    gpu_power_w: float | None = None
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
    if not hmac.compare_digest(authorization or "", f"Bearer {AGENT_TOKEN}"):
        raise HTTPException(status_code=401, detail="invalid token")


def _prefill_persisted_tx(
    rounds: list[dict], persisted: dict[str, tuple[str, float | None]]
) -> list[dict]:
    """Return copies of `rounds` with tx_hash/reward_amount filled in from
    already-persisted DB rows (keyed by round hash), for rounds that don't
    already carry a tx. Feeding these claims back in makes the matcher's
    `already_claimed` exclude transfers used on earlier pushes, so the same
    transfer can't be re-attached to a second round (cross-push dup fix)."""
    if not persisted:
        return rounds
    out: list[dict] = []
    for r in rounds:
        p = persisted.get(r.get("hash")) if not r.get("tx_hash") else None
        if p and p[0]:
            r = {**r, "tx_hash": p[0]}
            if r.get("reward_amount") is None:
                r["reward_amount"] = p[1]
        out.append(r)
    return out


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
    # Persist individual rounds. We run the chain-side tx_hash + reward
    # matcher here so the row goes in with as much enrichment as we have.
    # tx_hash / reward_amount may be NULL on this push -- a later push will
    # COALESCE them in once today_transfers has caught up.
    try:
        wallet_for_persist = snap.node_wallet or WALLET
        snap_date = (snap.ts or "")[:10]  # YYYY-MM-DD
        if snap.all_rounds_today and snap_date:
            if wallet_for_persist:
                # The chain matcher is the SOLE authority for tx attribution.
                # 1) Drop any agent-supplied tx_hash (legacy receipt-hash
                #    parsing): it attributes by log proximity and can disagree
                #    with the chain match, stamping one on-chain transfer onto a
                #    second round (the [amt, None] duplicate class).
                # 2) Restore prior chain-matched tx from the DB (cross-push
                #    stability) so a transfer already assigned to one round is in
                #    `already_claimed` and can't be re-attached to another round
                #    on a later push (the [amt, amt] duplicate class).
                # 3) Let the matcher attribute everything still unclaimed.
                base = [{k: v for k, v in r.items() if k != "tx_hash"}
                        for r in snap.all_rounds_today]
                persisted = load_round_tx(snap.node_id, snap_date)
                rounds_in = _prefill_persisted_tx(base, persisted)
                enriched = get_tracker(wallet_for_persist).attach_tx_hashes(
                    rounds_in, snap_date
                )
            else:
                enriched = snap.all_rounds_today
            upsert_rounds(snap.node_id, enriched, snap_date, snap.received_at)
    except Exception as e:  # pragma: no cover -- defensive, never block a push
        log.warning("rounds upsert failed for node %d: %s", snap.node_id, e)
    return {"ok": True, "received_at": snap.received_at}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_overview(_: None = Depends(require_login)):
    # Aggregate view: one tile per node, click to drill into the per-node
    # page at /dashboard/<id>. Data comes from /v1/dashboard-overview.
    return HTMLResponse(content=OVERVIEW_HTML)


@app.get("/dashboard/{node_id}", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_node(node_id: int, _: None = Depends(require_login)):
    if node_id < 1:
        raise HTTPException(status_code=404, detail="not found")
    # All node pages render the same HTML; the SPA reads node_id from the URL
    # and asks /v1/dashboard-data?node=N for the right snapshot.
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/login", include_in_schema=False)
async def login_form(session: str | None = Cookie(default=None)):
    # Already signed in -> straight to the dashboard.
    if AUTH_ENABLED and _verify_session_cookie(session):
        return RedirectResponse(url="/dashboard/1", status_code=303)
    # Auth disabled -> there's nothing to log in to; skip the form.
    if not AUTH_ENABLED:
        return RedirectResponse(url="/dashboard/1", status_code=303)
    return HTMLResponse(content=LOGIN_HTML)


@app.post("/login", include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    # Rate-limit check runs BEFORE bcrypt -- otherwise the bcrypt cost
    # (~100ms per attempt at cost-12) is itself the DoS vector we'd be
    # paying to "defend against." Only enforced when auth is on; with
    # auth disabled there's nothing to brute force.
    ip = _client_ip(request)
    if AUTH_ENABLED:
        retry_after = _login_blocked_seconds(ip)
        if retry_after > 0:
            log.warning("login rate-limit hit from %s (retry in %ds)", ip, retry_after)
            return HTMLResponse(
                content=(
                    "<!DOCTYPE html><html><body style='font-family:system-ui;"
                    "background:#0a0a0a;color:#e8e8e8;display:flex;"
                    "align-items:center;justify-content:center;height:100vh;"
                    "margin:0;'><div style='text-align:center;max-width:360px;"
                    "padding:24px;background:#141414;border:1px solid #2a2a2a;"
                    "border-radius:10px;'><h1 style='font-size:16px;"
                    "margin-bottom:8px;'>Too many login attempts</h1>"
                    f"<p style='color:#888;font-size:13px;'>Try again in "
                    f"{retry_after} seconds.</p></div></body></html>"
                ),
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

    # Always run bcrypt so the response time is the same whether the username
    # was wrong, the password was wrong, or auth is disabled -- avoids a
    # timing oracle for "is this a real username?".
    expected_hash = (DASHBOARD_PASS_HASH or "").encode()
    try:
        pw_ok = bcrypt.checkpw(password.encode(), expected_hash) if expected_hash else False
    except ValueError:
        # Malformed hash in env -- treat as wrong password. Logged at boot
        # already if invalid; no point spamming here.
        pw_ok = False
    user_ok = AUTH_ENABLED and username == DASHBOARD_USER
    if user_ok and pw_ok:
        if AUTH_ENABLED:
            _login_record_success(ip)
        resp = RedirectResponse(url="/dashboard/1", status_code=303)
        _issue_session_cookie(resp)
        return resp
    if AUTH_ENABLED:
        _login_record_failure(ip)
    return RedirectResponse(url="/login?error=1", status_code=303)


@app.post("/logout", include_in_schema=False)
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("session", path="/")
    return resp


class AddWalletPayload(BaseModel):
    address: str
    label: str | None = None


@app.post("/v1/wallets")
async def add_wallet(payload: AddWalletPayload, _: None = Depends(require_login_json)):
    try:
        addr = wstore.add_watched(payload.address, payload.label)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "address": addr}


@app.get("/v1/wallets")
async def list_wallets(_: None = Depends(require_login_json)):
    rows = wstore.list_watched()
    enriched: list[dict] = []
    for w in rows:
        addr = w["address"]
        for_bal = None
        mon_bal = None
        try:
            for_bal = await get_for_balance(MONAD_RPC_URL, FOR_CONTRACT, addr)
        except Exception as e:
            log.warning("FOR balance fetch failed for %s: %s", addr, e)
        try:
            mon_bal = await get_native_balance(MONAD_RPC_URL, addr)
        except Exception as e:
            log.warning("MONAD balance fetch failed for %s: %s", addr, e)
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
async def dashboard_data(node: int = 1, _: None = Depends(require_login_json)):
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
        projections = _projections(wallet)
    else:
        balance = monad_balance = None
        balance_error = monad_balance_error = None
        chain_rewards = None
        projections = None

    snapshot_dict = None
    if s:
        if wallet:
            # Chain matcher is the SOLE authority for tx attribution on the
            # dashboard too (mirrors the persist path): drop any agent-supplied
            # tx_hash, restore the node's already-persisted (clean, deduped) tx
            # from the DB so the card shows exactly what's stored -- stable
            # across refreshes and consistent with /v1/rounds -- and only
            # chain-match rounds that aren't persisted yet.
            day = (s.ts or "")[:10]
            persisted = load_round_tx(node, day)
            tracker = get_tracker(wallet)
            recent_rounds = tracker.attach_tx_hashes(
                _prefill_persisted_tx(
                    [{k: v for k, v in r.items() if k != "tx_hash"} for r in s.recent_rounds],
                    persisted),
                day,
            )
            all_rounds_today = tracker.attach_tx_hashes(
                _prefill_persisted_tx(
                    [{k: v for k, v in r.items() if k != "tx_hash"} for r in s.all_rounds_today],
                    persisted),
                day,
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
            "gpu_power_w": s.gpu_power_w,
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
        "projections": projections,
        "today": _today_summary(node),
        "power": _power_summary(node),
        "node_name": await _cached_node_name(wallet),
        "uptime": _uptime_for_node(node),
        "wallet": wallet,
        "wallet_short": (f"{wallet[:6]}…{wallet[-4:]}" if wallet else None),
        "known_nodes": known_nodes,
        # SPA uses this to decide whether to render the logout button.
        "auth_enabled": AUTH_ENABLED,
    })


# Per-round history query. `node` filters to one node when set; omitting
# returns all nodes. `since` / `until` are full UTC ISO strings
# ("YYYY-MM-DDTHH:MM:SSZ") and compare lexicographically against the
# stored completed_iso. `limit` capped at ROUNDS_QUERY_MAX to keep payload
# size predictable for casual exploration; bump the env var for bulk pulls.
_ROUNDS_QUERY_MAX = int(os.environ.get("ROUNDS_QUERY_MAX", "1000"))


@app.get("/v1/rounds")
async def v1_rounds(
    node: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
    _: None = Depends(require_login_json),
):
    if limit < 1:
        limit = 1
    if limit > _ROUNDS_QUERY_MAX:
        limit = _ROUNDS_QUERY_MAX
    rows = load_rounds(node, since, until, limit)
    return {"rounds": rows, "count": len(rows), "limit": limit}


@app.get("/v1/dashboard-overview")
async def dashboard_overview_data(_: None = Depends(require_login_json)):
    """Per-node tile data + summed totals for the /dashboard overview page.
    Deduplicates `earned_today` per distinct wallet so two nodes sharing one
    operator wallet don't double-count the day's payouts."""
    now = time.time()
    known = sorted(set(store.known_node_ids()) | {1, 2})
    nodes_out: list[dict] = []
    earned_per_wallet: dict[str, float] = {}
    total_participations = 0
    nodes_active = 0
    for nid in known:
        s = store.get(nid)
        # Fall back to server's WALLET env only for node 1 (mirrors legacy
        # behavior in /v1/dashboard-data); other nodes need an explicit
        # node_wallet on their push to show a wallet.
        wallet = (s.node_wallet if s else None) or (WALLET if nid == 1 else None)
        earned_for_node: float | None = None
        if wallet:
            wlc = wallet.lower()
            if wlc in earned_per_wallet:
                earned_for_node = earned_per_wallet[wlc]
            else:
                try:
                    summary = get_tracker(wallet).summary()
                    earned_for_node = float(summary.get("earned_today") or 0.0)
                except Exception:  # pragma: no cover -- defensive
                    earned_for_node = None
                if earned_for_node is not None:
                    earned_per_wallet[wlc] = earned_for_node
        up = _uptime_for_node(nid, now)
        if s is not None:
            nodes_active += 1
            total_participations += int(s.rounds_participated_today or 0)
        nodes_out.append({
            "node_id": nid,
            "wallet": wallet,
            "wallet_short": (f"{wallet[:6]}…{wallet[-4:]}" if wallet else None),
            "received_at": s.received_at if s else None,
            "ts": s.ts if s else None,
            "earned_today": earned_for_node,
            "tps_current": s.tps_current if s else None,
            "rounds_participated_today": (s.rounds_participated_today if s else 0),
            "capsule_alive": (s.capsule_alive if s else False),
            "protocol_alive": (s.protocol_alive if s else False),
            "uptime_pct_24h": up.get("pct_24h"),
        })
    return {
        "nodes": nodes_out,
        "totals": {
            "earned_today": round(sum(earned_per_wallet.values()), 6),
            "distinct_wallets": len(earned_per_wallet),
            "nodes_active": nodes_active,
            "nodes_known": len(known),
            "rounds_participated_today": total_participations,
        },
        "auth_enabled": AUTH_ENABLED,
    }
