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
