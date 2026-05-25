"""On-chain reward tracker — sums ERC-20 Transfer events into the operator
wallet since 00:00 UTC today.

The agent's log-derived `rewards_today_total` only captures rewards the Capsule
log emits a `FOR balance before/after reward` pair for, which structurally
undercounts (observer rewards, periodic distributions land on-chain but never in
the log). This tracker is the authoritative number for the dashboard's
"FOR earned today" headline.

Design:
- Singleton `tracker` instance. Refresh is idempotent + cached (30s TTL,
  matching `_cached_balance`).
- First call after a fresh deploy: find the block whose timestamp >= today's
  UTC midnight via binary search (~20 RPC calls). Then scan from there to
  `latest` in chunks of <=1000 blocks via `get_transfer_events`.
- Subsequent calls: scan from `last_scanned_block + 1` to `latest` (usually
  <30 blocks → 1 RPC call).
- UTC day rollover: clear today_transfers, re-find midnight block on next
  refresh.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from chain import (
    get_block_timestamp,
    get_latest_block,
    get_transfer_events,
)
from db import load_daily_totals, upsert_daily_total

_TTL_SECONDS = 30.0
# Monad's public testnet RPC (https://testnet-rpc.monad.xyz/) returns
# `413 Request Entity Too Large` on eth_getLogs over wide ranges. 100 blocks
# is the safe upper bound we've observed. If you point MONAD_RPC_URL at a paid
# provider (Alchemy, BlockVision, etc.) you can bump this without code changes.
_CHUNK_SIZE = 100
_MIN_CHUNK_SIZE = 5  # halving floor on retry — below this we skip the chunk
# Per-request cap when fanning out blockNumber → timestamp lookups
_MAX_BLOCK_TS_LOOKUPS_PER_CHUNK = 50


def _utc_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_midnight_ts() -> int:
    """Unix timestamp at 00:00:00 UTC today."""
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


@dataclass
class _Transfer:
    amount: float
    tx_hash: str
    block_number: int
    log_index: int
    ts: int  # block timestamp, unix seconds UTC

    @property
    def iso(self) -> str:
        return datetime.fromtimestamp(self.ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class RewardsTracker:
    today_utc_date: str | None = None
    today_midnight_ts: int | None = None
    today_midnight_block: int | None = None
    today_transfers: list[_Transfer] = field(default_factory=list)
    # Yesterday's transfers — preserved across UTC-midnight rollover so the
    # 24h rounds chart's earlier bars (which span yesterday's hours) can
    # show real FOR/hour in their tooltips instead of "—".
    yesterday_transfers: list[_Transfer] = field(default_factory=list)
    yesterday_utc_date: str | None = None
    # Historical per-hour totals loaded from SQLite on startup. Keyed
    # "YYYY-MM-DDTHH" so it stacks cleanly into transfers_by_hour without
    # collisions. Survives container restarts inside a single deploy;
    # NOT Render redeploys (filesystem is ephemeral on free tier).
    historical_by_hour: dict[str, float] = field(default_factory=dict)
    last_scanned_block: int | None = None
    last_refresh_ts: float = 0.0
    last_error: str | None = None
    _historical_loaded: bool = False  # one-shot guard for lazy load

    def _ensure_historical_loaded(self) -> None:
        """Load daily_totals rows from SQLite into self.historical_by_hour.
        Called lazily on first refresh so we don't crash if db.py isn't
        importable (e.g. during tests that stub the chain module)."""
        if self._historical_loaded:
            return
        try:
            for row in load_daily_totals():
                for k, v in (row.get("by_hour") or {}).items():
                    try:
                        self.historical_by_hour[k] = float(v)
                    except (TypeError, ValueError):
                        continue
        except Exception:
            pass  # SQLite unavailable / empty — non-fatal
        self._historical_loaded = True

    def _persist_today(self) -> None:
        """Upsert today's current state into the daily_totals table."""
        if not self.today_utc_date:
            return
        by_hour: dict[str, float] = {}
        for t in self.today_transfers:
            dt = datetime.fromtimestamp(t.ts, tz=timezone.utc)
            key = dt.strftime("%Y-%m-%dT%H")
            by_hour[key] = by_hour.get(key, 0.0) + t.amount
        try:
            upsert_daily_total(
                self.today_utc_date,
                {k: round(v, 6) for k, v in by_hour.items()},
                round(sum(t.amount for t in self.today_transfers), 6),
                len(self.today_transfers),
                time.time(),
            )
            # Also fold today's keys into historical_by_hour so subsequent
            # summary() calls see the latest without re-reading SQLite.
            for k, v in by_hour.items():
                self.historical_by_hour[k] = round(v, 6)
        except Exception:
            pass  # non-fatal

    def _reset_for_new_day(self) -> None:
        # Persist the day we're leaving BEFORE clearing in-memory state, so
        # we never lose a finished day to a poorly-timed redeploy.
        if self.today_transfers and self.today_utc_date:
            self._persist_today()
            self.yesterday_transfers = self.today_transfers
            self.yesterday_utc_date = self.today_utc_date
        self.today_utc_date = _utc_today_str()
        self.today_midnight_ts = _utc_midnight_ts()
        self.today_midnight_block = None
        self.today_transfers = []
        self.last_scanned_block = None

    async def _find_midnight_block(self, rpc_url: str) -> int:
        """Binary-search the first block whose timestamp >= today's UTC midnight.

        Bounds:
          high = latest block
          low  = high - ceil(seconds_since_midnight / min_block_seconds) * safety
        Falls back to scanning the last 200k blocks if estimation fails.
        """
        assert self.today_midnight_ts is not None
        target = self.today_midnight_ts

        latest = await get_latest_block(rpc_url)
        latest_ts = await get_block_timestamp(rpc_url, latest)
        if latest_ts <= target:
            # Edge: midnight hasn't started producing blocks yet. Use latest.
            return latest

        # Monad testnet blocks are ~1s; over-estimate to 0.5s for safety.
        elapsed = max(1, latest_ts - target)
        est_blocks = int(elapsed / 0.5) + 100
        low = max(0, latest - est_blocks)

        # If our estimated low isn't actually before midnight, widen until it is.
        for _ in range(5):
            low_ts = await get_block_timestamp(rpc_url, low)
            if low_ts < target:
                break
            low = max(0, low - est_blocks)
            if low == 0:
                break
        high = latest

        # Binary search: first block with ts >= target.
        while low < high:
            mid = (low + high) // 2
            ts = await get_block_timestamp(rpc_url, mid)
            if ts < target:
                low = mid + 1
            else:
                high = mid
        return low

    async def _fetch_chunk_with_halving(
        self, rpc_url: str, for_contract: str, wallet: str,
        cursor: int, chunk_end: int,
    ) -> tuple[list[dict], int, str | None]:
        """Try eth_getLogs over [cursor, chunk_end]. On 413 or timeout, halve
        the range and retry, down to `_MIN_CHUNK_SIZE`. Returns
        (events, last_block_actually_scanned, error_or_None).
        """
        attempt_end = chunk_end
        last_err: str | None = None
        while attempt_end >= cursor:
            try:
                events = await get_transfer_events(
                    rpc_url, for_contract, [wallet], cursor, attempt_end
                )
                return events, attempt_end, None
            except Exception as e:
                msg = str(e)
                last_err = f"{type(e).__name__}: {msg}"
                # Halve only on size-related errors; bail on other errors.
                if "413" not in msg and "Too Large" not in msg and "timeout" not in msg.lower():
                    return [], cursor - 1, last_err
                span = attempt_end - cursor + 1
                if span <= _MIN_CHUNK_SIZE:
                    # Give up on this chunk; skip past it so we make progress next refresh.
                    return [], attempt_end, last_err
                attempt_end = cursor + (span // 2) - 1
        return [], cursor - 1, last_err

    async def refresh(self, rpc_url: str, for_contract: str, wallet: str) -> None:
        now = time.time()
        today = _utc_today_str()

        # Lazy-load persisted daily_totals on first refresh.
        self._ensure_historical_loaded()

        # Day rollover
        if today != self.today_utc_date:
            self._reset_for_new_day()

        # TTL — don't hammer RPC
        if now - self.last_refresh_ts < _TTL_SECONDS and self.today_midnight_block is not None:
            return

        try:
            if self.today_midnight_block is None:
                self.today_midnight_block = await self._find_midnight_block(rpc_url)
                self.last_scanned_block = self.today_midnight_block - 1

            latest = await get_latest_block(rpc_url)
            assert self.last_scanned_block is not None
            from_block = self.last_scanned_block + 1
            if from_block > latest:
                self.last_refresh_ts = now
                self.last_error = None
                return

            # Chunk to respect eth_getLogs range limits. Each successful chunk
            # advances `last_scanned_block` so partial progress sticks across
            # refreshes — a 413 on the 5th chunk doesn't lose the first 4.
            chunk_err: str | None = None
            cursor = from_block
            while cursor <= latest:
                chunk_end = min(cursor + _CHUNK_SIZE - 1, latest)
                events, advanced_to, err = await self._fetch_chunk_with_halving(
                    rpc_url, for_contract, wallet, cursor, chunk_end,
                )
                if err and not events:
                    chunk_err = err
                    if advanced_to >= cursor:
                        # We gave up on this range — skip past it.
                        self.last_scanned_block = advanced_to
                        cursor = advanced_to + 1
                        continue
                    # Couldn't make progress at all → bail out for this refresh.
                    break

                # Annotate with block timestamp (one extra RPC per unique block,
                # capped per chunk so a transfer-heavy block range can't blow
                # out the per-request budget).
                seen_block_ts: dict[int, int] = {}
                ts_lookups = 0
                for ev in events:
                    bn = ev["block_number"]
                    if bn not in seen_block_ts:
                        if ts_lookups >= _MAX_BLOCK_TS_LOOKUPS_PER_CHUNK:
                            # Skip the timestamp lookup; approximate from chunk_end
                            # block time (close enough for "today" filtering).
                            seen_block_ts[bn] = self.today_midnight_ts or 0
                        else:
                            try:
                                seen_block_ts[bn] = await get_block_timestamp(rpc_url, bn)
                                ts_lookups += 1
                            except Exception:
                                seen_block_ts[bn] = self.today_midnight_ts or 0
                    ts = seen_block_ts[bn]
                    if ts < (self.today_midnight_ts or 0):
                        continue
                    self.today_transfers.append(
                        _Transfer(
                            amount=ev["amount"],
                            tx_hash=ev["tx_hash"],
                            block_number=bn,
                            log_index=ev["log_index"],
                            ts=ts,
                        )
                    )
                self.last_scanned_block = advanced_to
                cursor = advanced_to + 1

            # Sort by (block, log_index) so summary() last-item is genuinely latest.
            self.today_transfers.sort(key=lambda t: (t.block_number, t.log_index))
            self.last_refresh_ts = now
            # Partial-success semantics: clear last_error if we made progress
            # (transfers got appended); keep error context if we made none.
            self.last_error = chunk_err if (chunk_err and not self.today_transfers) else None
            # Persist today's state to SQLite so a container restart inside
            # this deploy doesn't lose the data. (Render redeploys still
            # wipe the SQLite file — see db.py header.)
            self._persist_today()
        except Exception as e:
            # Keep last-known good state; surface error so dashboard can show it
            # rather than blanking the card.
            self.last_error = f"{type(e).__name__}: {e}"

    def attach_tx_hashes(
        self,
        rounds: list[dict[str, Any]],
        today_date: str | None,
        pad_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        """Inject `tx_hash` into round dicts whose tx_hash is null/missing,
        sourcing from `self.today_transfers` by interval-overlap match.

        Why: recent Capsule versions stopped logging `Resolution of ...
        receipt hash 0x...` so the agent's parser can't pair tx hashes.
        Chain-side matching is format-independent and uses the authoritative
        Monad receipt.

        Matching window — the chain settlement happens MID-ROUND (when the
        Resolution call lands on-chain), not at the round-completed log
        line. A round takes typically 3-5 min from "Participating" to
        "completed", and the on-chain tx fires somewhere in that interval.
        We compute `start_ts = completed_ts - duration_s` and accept any
        transfer in `[start_ts - pad, completed_ts + pad]` as a candidate.
        With pad=120s this covers the round's full execution window plus
        2 min of slop on either side for chain-settlement jitter.

        Greedy assignment: rounds in chronological order each claim the
        unused transfer whose ts is closest to the round's mid-point, but
        only if that transfer is inside the round's accepted window.

        Returns a NEW list (doesn't mutate input). Rounds with a non-null
        tx_hash already populated by the agent are left untouched.

        Pre-conditions: `today_date` is a "YYYY-MM-DD" string used to convert
        each round's `completed_iso` (HH:MM:SS) to a UTC epoch.
        """
        if not rounds or not self.today_transfers or not today_date:
            return rounds
        try:
            midnight = datetime.fromisoformat(today_date).replace(tzinfo=timezone.utc)
            midnight_ts = int(midnight.timestamp())
        except Exception:
            return rounds

        avail: list[tuple[int, str]] = sorted(
            [(t.ts, t.tx_hash) for t in self.today_transfers],
            key=lambda x: x[0],
        )
        used: set[int] = set()

        def _round_interval(r: dict[str, Any]) -> tuple[int, int, int] | None:
            """Return (start_ts, completed_ts, mid_ts) or None."""
            iso = r.get("completed_iso")
            if not iso:
                return None
            try:
                h, m, s = (int(x) for x in str(iso).split(":"))
                completed = midnight_ts + h * 3600 + m * 60 + s
                duration = int(r.get("duration_s") or 0)
                start = completed - duration
                mid = (start + completed) // 2
                return start, completed, mid
            except Exception:
                return None

        # Match greedily in chronological order (by completed_ts) so the
        # earliest-completed unmatched round claims first.
        def _completed(i: int) -> int:
            iv = _round_interval(rounds[i])
            return iv[1] if iv else 0
        order = sorted(
            range(len(rounds)),
            key=lambda i: (_round_interval(rounds[i]) is None, _completed(i)),
        )
        matches: dict[int, str] = {}
        for orig_i in order:
            r = rounds[orig_i]
            if r.get("tx_hash"):
                continue
            # Skip observer rounds — they didn't participate, didn't compute,
            # got no on-chain reward. Default to True for backward compat with
            # snapshots from pre-v8.6 agents that don't emit this field
            # (better to over-pair legacy data than under-pair it).
            if r.get("participated", True) is False:
                continue
            iv = _round_interval(r)
            if iv is None:
                continue
            start_ts, completed_ts, mid_ts = iv
            lo = start_ts - pad_seconds
            hi = completed_ts + pad_seconds
            best_ai = None
            best_delta = float("inf")
            for ai, (ts, _tx) in enumerate(avail):
                if ai in used:
                    continue
                if ts < lo or ts > hi:
                    continue
                d = abs(ts - mid_ts)
                if d < best_delta:
                    best_delta = d
                    best_ai = ai
            if best_ai is not None:
                used.add(best_ai)
                matches[orig_i] = avail[best_ai][1]

        # Rebuild in original order with matched tx_hashes injected.
        out: list[dict[str, Any]] = []
        for i, r in enumerate(rounds):
            if i in matches:
                r2 = dict(r)
                r2["tx_hash"] = matches[i]
                out.append(r2)
            else:
                out.append(r)
        return out

    def summary(self) -> dict[str, Any]:
        earned = sum(t.amount for t in self.today_transfers)
        count = len(self.today_transfers)
        last = self.today_transfers[-1] if self.today_transfers else None
        # Bucket transfers by UTC hour. Keys match the agent's
        # rounds_history format ("YYYY-MM-DDTHH") so the dashboard's
        # bucket() helper can reuse the same lookup pattern for tooltips.
        # Includes today + yesterday (in-memory) + historical (SQLite),
        # so 24h / 7d / 4w chart bars all get per-hour FOR data when
        # the corresponding day was scanned at some point.
        by_hour: dict[str, float] = dict(self.historical_by_hour)  # start with persisted history
        # Today + yesterday in-memory state takes precedence (more recent)
        for t in (*self.today_transfers, *self.yesterday_transfers):
            dt = datetime.fromtimestamp(t.ts, tz=timezone.utc)
            key = dt.strftime("%Y-%m-%dT%H")
            # Recompute the hour bucket from the live list — for today this
            # is more accurate than historical (historical is a snapshot,
            # today is the source of truth).
            if key.startswith(self.today_utc_date or "_"):
                # Will be overwritten below in the second pass for today's keys
                by_hour[key] = 0.0
        for t in (*self.today_transfers, *self.yesterday_transfers):
            dt = datetime.fromtimestamp(t.ts, tz=timezone.utc)
            key = dt.strftime("%Y-%m-%dT%H")
            by_hour[key] = by_hour.get(key, 0.0) + t.amount
        by_hour_rounded = {k: round(v, 6) for k, v in by_hour.items()}
        return {
            "earned_today": round(earned, 6) if earned else 0.0,
            "transfers_today": count,
            "transfers_by_hour": by_hour_rounded,
            "last_transfer_amount": round(last.amount, 6) if last else None,
            "last_transfer_iso": last.iso if last else None,
            "last_transfer_tx": last.tx_hash if last else None,
            "refreshed_at": self.last_refresh_ts or None,
            "error": self.last_error,
        }


tracker = RewardsTracker()
