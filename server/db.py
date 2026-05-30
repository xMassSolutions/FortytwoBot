"""Persistence layer for FortytwoBot.

Backend is chosen at import time:
  - DATABASE_URL set  -> Postgres via psycopg2 (durable, recommended)
  - DATABASE_URL unset -> SQLite at DB_PATH (default /tmp/fortytwobot.db)

SQLite is fine for local dev but EPHEMERAL on Render's free tier
(filesystem resets on cold start and redeploy). Use Postgres -- e.g.
a free Neon project -- for any deployment where you want reward
history to survive a bot restart.

SQL is written for both backends: `?` placeholders (translated to `%s`
for Postgres by the connection wrapper), and `ON CONFLICT ... DO ...`
upserts (supported by SQLite 3.24+ and Postgres 9.5+).
"""

import json
import os
import sqlite3
import threading
import time
from typing import Any, Iterable, Iterator

DB_PATH = os.environ.get("DB_PATH", "/tmp/fortytwobot.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

_lock = threading.Lock()

if USE_PG:
    import psycopg2  # type: ignore[import-not-found]


class _Cursor:
    """Iterator that yields dict rows uniformly across SQLite and Postgres.
    Iterate inside the connection's `with` block; results are not available
    after the connection closes."""

    def __init__(self, raw: Any, is_pg: bool) -> None:
        self._raw = raw
        self._is_pg = is_pg

    def __iter__(self) -> Iterator[dict[str, Any]]:
        if self._is_pg:
            cols = [d[0] for d in self._raw.description] if self._raw.description else []
            for row in self._raw:
                yield dict(zip(cols, row))
            self._raw.close()
        else:
            for row in self._raw:
                yield dict(row)

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.__iter__())

    def fetchone(self) -> dict[str, Any] | None:
        row = self._raw.fetchone()
        if row is None:
            return None
        if self._is_pg:
            cols = [d[0] for d in self._raw.description]
            return dict(zip(cols, row))
        return dict(row)

    @property
    def rowcount(self) -> int:
        return self._raw.rowcount


class _Conn:
    """Backend-agnostic connection wrapper. Use `?` placeholders -- they
    are rewritten to `%s` for Postgres at execute time."""

    def __init__(self, raw: Any, is_pg: bool) -> None:
        self._raw = raw
        self._is_pg = is_pg

    def execute(self, sql: str, params: Iterable[Any] = ()) -> _Cursor:
        if self._is_pg:
            cur = self._raw.cursor()
            cur.execute(sql.replace("?", "%s"), tuple(params))
            return _Cursor(cur, True)
        cur = self._raw.execute(sql, tuple(params))
        return _Cursor(cur, False)

    def commit(self) -> None:
        self._raw.commit()

    def __enter__(self) -> "_Conn":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                # psycopg2 leaves the connection in error state until rollback;
                # sqlite3 silently rolls back on close but rollback is harmless.
                self._raw.rollback()
        finally:
            self._raw.close()


def get_conn() -> _Conn:
    if USE_PG:
        return _Conn(psycopg2.connect(DATABASE_URL), True)
    raw = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA journal_mode=WAL")
    return _Conn(raw, False)


# --- Schema -----------------------------------------------------------------
# Types are Postgres-friendly. SQLite is loose about types and accepts
# DOUBLE PRECISION / BIGINT as their nearest equivalents.

_DDL_WALLETS = """
CREATE TABLE IF NOT EXISTS wallets (
    address    TEXT PRIMARY KEY,
    label      TEXT,
    added_at   BIGINT NOT NULL
)
"""

_DDL_DAILY_TOTALS = """
CREATE TABLE IF NOT EXISTS daily_totals (
    utc_date        TEXT NOT NULL,
    wallet          TEXT NOT NULL,
    by_hour_json    TEXT NOT NULL,
    total_amount    DOUBLE PRECISION NOT NULL,
    transfer_count  INTEGER NOT NULL,
    last_updated    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (utc_date, wallet)
)
"""

_DDL_ROUNDS_HISTORY = """
CREATE TABLE IF NOT EXISTS rounds_history (
    node_id      INTEGER NOT NULL,
    hour_key     TEXT NOT NULL,
    rounds       INTEGER NOT NULL,
    last_updated DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (node_id, hour_key)
)
"""

# alive is 0/1 (SQLite has no native BOOL; Postgres accepts INTEGER fine).
# One row per node per minute via the background sampler in app.py.
_DDL_UPTIME_SAMPLES = """
CREATE TABLE IF NOT EXISTS uptime_samples (
    node_id INTEGER NOT NULL,
    ts      DOUBLE PRECISION NOT NULL,
    alive   INTEGER NOT NULL,
    PRIMARY KEY (node_id, ts)
)
"""

# Per-round history. PK (node_id, hash) -- round hashes are unique per
# inference request and don't repeat across days. Upsert path uses
# COALESCE so a later push with chain-matched tx_hash/reward_amount can
# fill in fields that an earlier push left NULL, without clobbering them
# back to NULL.
_DDL_ROUNDS = """
CREATE TABLE IF NOT EXISTS rounds (
    node_id        INTEGER NOT NULL,
    hash           TEXT NOT NULL,
    tx_hash        TEXT,
    completed_iso  TEXT NOT NULL,
    duration_s     INTEGER,
    participated   INTEGER NOT NULL,
    reward_amount  DOUBLE PRECISION,
    last_updated   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (node_id, hash)
)
"""

# Per-node daily energy rollup (kWh). The background sampler integrates the
# node's reported GPU power (watts) over each tick into the current UTC day via
# an additive upsert. One row per node per UTC day -> bounded + cheap.
_DDL_ENERGY_DAILY = """
CREATE TABLE IF NOT EXISTS energy_daily (
    node_id      INTEGER NOT NULL,
    utc_date     TEXT NOT NULL,
    kwh          DOUBLE PRECISION NOT NULL,
    last_updated DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (node_id, utc_date)
)
"""


def init_schema() -> None:
    with _lock, get_conn() as conn:
        # daily_totals migration from the pre-v11 single-wallet PK to
        # (utc_date, wallet). SQLite on Render is ephemeral so dropping is
        # safe and avoids a "PK constraint mismatch" on the new schema.
        # On Postgres NEVER drop -- that's the durable backend.
        if not USE_PG:
            conn.execute("DROP TABLE IF EXISTS daily_totals")
        conn.execute(_DDL_WALLETS)
        conn.execute(_DDL_DAILY_TOTALS)
        conn.execute(_DDL_ROUNDS_HISTORY)
        conn.execute(_DDL_UPTIME_SAMPLES)
        conn.execute(_DDL_ROUNDS)
        conn.execute(_DDL_ENERGY_DAILY)


def upsert_daily_total(
    utc_date: str,
    wallet: str,
    by_hour: dict[str, float],
    total_amount: float,
    transfer_count: int,
    ts: float,
) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            """
            INSERT INTO daily_totals (utc_date, wallet, by_hour_json, total_amount, transfer_count, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (utc_date, wallet) DO UPDATE SET
                by_hour_json   = EXCLUDED.by_hour_json,
                total_amount   = EXCLUDED.total_amount,
                transfer_count = EXCLUDED.transfer_count,
                last_updated   = EXCLUDED.last_updated
            """,
            (utc_date, wallet.lower(), json.dumps(by_hour, separators=(",", ":")),
             total_amount, transfer_count, ts),
        )


def load_daily_totals(wallet: str) -> list[dict]:
    """Return list of {utc_date, by_hour, total_amount, transfer_count,
    last_updated} for the given wallet across every persisted day."""
    rows: list[dict] = []
    with _lock, get_conn() as conn:
        for r in conn.execute(
            "SELECT utc_date, by_hour_json, total_amount, transfer_count, last_updated "
            "FROM daily_totals WHERE wallet = ? ORDER BY utc_date",
            (wallet.lower(),),
        ):
            try:
                by_hour = json.loads(r["by_hour_json"]) or {}
            except Exception:
                by_hour = {}
            rows.append({
                "utc_date": r["utc_date"],
                "by_hour": by_hour,
                "total_amount": r["total_amount"],
                "transfer_count": r["transfer_count"],
                "last_updated": r["last_updated"],
            })
    return rows


def upsert_rounds_history(node_id: int, history: dict[str, int]) -> None:
    """Mirror the agent's rounds_history dict for this node. The server
    keeps the MAX per (node_id, hour_key) so a corrupted short push
    cannot clobber an older, higher value.

    `history` is the agent's `{"YYYY-MM-DDTHH": count}` dict from the
    last snapshot. Empty/None input is a no-op."""
    if not history:
        return
    now = time.time()
    with _lock, get_conn() as conn:
        for hour_key, rounds in history.items():
            try:
                r_int = int(rounds)
            except (TypeError, ValueError):
                continue
            if r_int < 0 or not hour_key:
                continue
            conn.execute(
                """
                INSERT INTO rounds_history (node_id, hour_key, rounds, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (node_id, hour_key) DO UPDATE SET
                    rounds = CASE WHEN EXCLUDED.rounds > rounds_history.rounds
                                  THEN EXCLUDED.rounds
                                  ELSE rounds_history.rounds END,
                    last_updated = EXCLUDED.last_updated
                """,
                (node_id, hour_key, r_int, now),
            )


def load_rounds_history(node_id: int) -> dict[str, int]:
    """Return persisted {hour_key: rounds} for the given node."""
    out: dict[str, int] = {}
    with _lock, get_conn() as conn:
        for r in conn.execute(
            "SELECT hour_key, rounds FROM rounds_history WHERE node_id = ?",
            (node_id,),
        ):
            try:
                out[r["hour_key"]] = int(r["rounds"])
            except (TypeError, ValueError):
                continue
    return out


def insert_uptime_sample(node_id: int, ts: float, alive: bool) -> None:
    """Append one (node_id, ts, alive) row. ON CONFLICT keeps the existing
    value so a clock skip that lands a duplicate ts is a no-op rather than
    crashing the sampler."""
    with _lock, get_conn() as conn:
        conn.execute(
            "INSERT INTO uptime_samples (node_id, ts, alive) VALUES (?, ?, ?) "
            "ON CONFLICT (node_id, ts) DO NOTHING",
            (node_id, float(ts), 1 if alive else 0),
        )


def load_uptime_samples_since(node_id: int, since_ts: float) -> list[dict]:
    """Return [{ts, alive}] for node since since_ts, oldest first."""
    rows: list[dict] = []
    with _lock, get_conn() as conn:
        for r in conn.execute(
            "SELECT ts, alive FROM uptime_samples "
            "WHERE node_id = ? AND ts >= ? ORDER BY ts",
            (node_id, float(since_ts)),
        ):
            rows.append({"ts": float(r["ts"]), "alive": bool(r["alive"])})
    return rows


def prune_uptime_samples_older_than(cutoff_ts: float) -> int:
    """Delete rows with ts < cutoff_ts. Returns the row count deleted (best
    effort -- SQLite returns rowcount reliably, Postgres also does for DELETE).
    Cheap to run; the table stays small even without pruning, but unbounded
    growth on a long-lived Postgres deploy is rude."""
    with _lock, get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM uptime_samples WHERE ts < ?",
            (float(cutoff_ts),),
        )
        return cur.rowcount or 0


def add_energy(node_id: int, utc_date: str, kwh_inc: float, ts: float) -> None:
    """Add `kwh_inc` to the node's energy rollup for `utc_date` (additive upsert).
    No-op for non-positive increments."""
    if kwh_inc <= 0:
        return
    with _lock, get_conn() as conn:
        conn.execute(
            """
            INSERT INTO energy_daily (node_id, utc_date, kwh, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (node_id, utc_date) DO UPDATE SET
                kwh          = energy_daily.kwh + EXCLUDED.kwh,
                last_updated = EXCLUDED.last_updated
            """,
            (node_id, utc_date, float(kwh_inc), ts),
        )


def load_energy_since(node_id: int, since_date: str) -> list[dict]:
    """Return [{utc_date, kwh}] for the node on/after `since_date`
    ("YYYY-MM-DD"), ordered by date."""
    out: list[dict] = []
    with _lock, get_conn() as conn:
        for r in conn.execute(
            "SELECT utc_date, kwh FROM energy_daily WHERE node_id = ? AND utc_date >= ? "
            "ORDER BY utc_date",
            (node_id, since_date),
        ):
            out.append({"utc_date": r["utc_date"], "kwh": float(r["kwh"] or 0.0)})
    return out


def prune_energy_daily_older_than(cutoff_date: str) -> int:
    """Delete energy rows with utc_date < cutoff_date ("YYYY-MM-DD")."""
    with _lock, get_conn() as conn:
        cur = conn.execute("DELETE FROM energy_daily WHERE utc_date < ?", (cutoff_date,))
        return cur.rowcount or 0


def upsert_rounds(node_id: int, rounds: list[dict], snap_date: str, now: float) -> int:
    """Persist one row per round into the `rounds` table. `snap_date` is the
    UTC date ("YYYY-MM-DD") used to expand each round's HH:MM:SS into a
    full ISO timestamp. Returns the number of rows attempted (write count is
    not reported separately; insert vs update is opaque from the caller).

    Upsert semantics: tx_hash / reward_amount / duration_s use COALESCE so
    a later push with chain-matched data fills in NULLs an earlier push left
    behind, but never clobbers existing values with NULL. participated uses
    MAX so a True flips never go back to False (handles the v9 retag-from-
    decided_hashes case where observer rounds get reclassified)."""
    if not rounds or not snap_date:
        return 0
    inserted = 0
    with _lock, get_conn() as conn:
        for r in rounds:
            h = r.get("hash")
            iso = r.get("completed_iso")
            if not h or not iso:
                continue
            # HH:MM:SS -> YYYY-MM-DDTHH:MM:SSZ. Skip if already full ISO.
            completed_full = iso if "T" in iso else f"{snap_date}T{iso}Z"
            duration = r.get("duration_s")
            tx_hash = r.get("tx_hash")
            reward_amount = r.get("reward_amount")
            participated = 1 if r.get("participated") else 0
            try:
                conn.execute(
                    """
                    INSERT INTO rounds (node_id, hash, tx_hash, completed_iso,
                                        duration_s, participated, reward_amount,
                                        last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (node_id, hash) DO UPDATE SET
                        tx_hash       = COALESCE(EXCLUDED.tx_hash, rounds.tx_hash),
                        duration_s    = COALESCE(EXCLUDED.duration_s, rounds.duration_s),
                        participated  = CASE WHEN EXCLUDED.participated > rounds.participated
                                             THEN EXCLUDED.participated
                                             ELSE rounds.participated END,
                        reward_amount = COALESCE(EXCLUDED.reward_amount, rounds.reward_amount),
                        last_updated  = EXCLUDED.last_updated
                    """,
                    (node_id, str(h), tx_hash, completed_full, duration,
                     participated, reward_amount, now),
                )
                inserted += 1
            except (TypeError, ValueError):
                continue
    return inserted


def load_rounds(
    node_id: int | None,
    since_iso: str | None,
    until_iso: str | None,
    limit: int,
) -> list[dict]:
    """Query rounds, newest first. node_id=None returns all nodes.
    since_iso/until_iso are full UTC ISO strings ("YYYY-MM-DDTHH:MM:SSZ");
    lexicographic compare works because the format is sortable."""
    sql = [
        "SELECT node_id, hash, tx_hash, completed_iso, duration_s, ",
        "       participated, reward_amount, last_updated ",
        "FROM rounds WHERE 1=1 ",
    ]
    params: list = []
    if node_id is not None:
        sql.append("AND node_id = ? ")
        params.append(node_id)
    if since_iso:
        sql.append("AND completed_iso >= ? ")
        params.append(since_iso)
    if until_iso:
        sql.append("AND completed_iso < ? ")
        params.append(until_iso)
    sql.append("ORDER BY completed_iso DESC LIMIT ?")
    params.append(int(limit))
    out: list[dict] = []
    with _lock, get_conn() as conn:
        for r in conn.execute("".join(sql), tuple(params)):
            out.append({
                "node_id": int(r["node_id"]),
                "hash": r["hash"],
                "tx_hash": r["tx_hash"],
                "completed_iso": r["completed_iso"],
                "duration_s": int(r["duration_s"]) if r["duration_s"] is not None else None,
                "participated": bool(r["participated"]),
                "reward_amount": float(r["reward_amount"]) if r["reward_amount"] is not None else None,
                "last_updated": float(r["last_updated"]),
            })
    return out


def load_round_tx(node_id: int, day_prefix: str) -> dict[str, tuple[str, float | None]]:
    """Return {round hash -> (tx_hash, reward_amount)} for the node's rounds on
    `day_prefix` (a "YYYY-MM-DD" string) that already have a tx_hash persisted.

    Used to seed the matcher with cross-push claims: pre-filling these onto the
    incoming snapshot rounds makes `attach_tx_hashes` skip them AND adds their
    tx to `already_claimed`, so a transfer assigned to one round on an earlier
    push can never be re-attached to a different round on a later push (the
    cross-push duplicate-tx bug). `completed_iso` is the sortable
    "YYYY-MM-DDTHH:MM:SSZ" form, so LIKE 'YYYY-MM-DD%' selects that UTC day."""
    out: dict[str, tuple[str, float | None]] = {}
    with _lock, get_conn() as conn:
        for r in conn.execute(
            "SELECT hash, tx_hash, reward_amount FROM rounds "
            "WHERE node_id = ? AND tx_hash IS NOT NULL AND completed_iso LIKE ?",
            (node_id, day_prefix + "%"),
        ):
            amt = r["reward_amount"]
            out[r["hash"]] = (r["tx_hash"], float(amt) if amt is not None else None)
    return out


def today_round_summary(node_id: int, day_prefix: str) -> dict[str, int]:
    """Authoritative counts for the dashboard "Today" doughnut, from the durable
    rounds table (so the card survives Render cold starts). `day_prefix` is a
    "YYYY-MM-DD" string; completed_iso is the sortable "YYYY-MM-DDTHH:MM:SSZ"
    form, so LIKE 'YYYY-MM-DD%' selects that UTC day.

    Returns {participated, rewarded}, where `rewarded` = distinct on-chain tx
    among participated rounds. COUNT(DISTINCT ...) collapses any duplicate rows,
    so the figure is correct regardless of the dedup state. No FILTER clause --
    CASE keeps it portable across SQLite and Postgres."""
    with _lock, get_conn() as conn:
        row = conn.execute(
            "SELECT sum(CASE WHEN participated=1 THEN 1 ELSE 0 END) AS participated, "
            "       count(DISTINCT CASE WHEN participated=1 THEN tx_hash END) AS rewarded "
            "FROM rounds WHERE node_id = ? AND completed_iso LIKE ?",
            (node_id, day_prefix + "%"),
        ).fetchone()
    return {
        "participated": int(row["participated"] or 0) if row else 0,
        "rewarded": int(row["rewarded"] or 0) if row else 0,
    }
