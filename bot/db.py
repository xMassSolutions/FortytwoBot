"""SQLite layer for FortytwoBot.

NOTE: On Render's free tier the underlying filesystem is ephemeral.
Data in this DB resets on every redeploy (and on most cold starts).
For persistence across redeploys, mount a persistent disk OR move to
Postgres (e.g. free Neon DB) by reading DATABASE_URL instead.
"""

import os
import sqlite3
import threading

DB_PATH = os.environ.get("DB_PATH", "/tmp/fortytwobot.db")
_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema() -> None:
    with _lock, get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS wallets (
            address    TEXT PRIMARY KEY,
            label      TEXT,
            added_at   INTEGER NOT NULL
        );
        -- Daily reward totals — written by RewardsTracker on midnight
        -- rollover and on each successful refresh. Survives container
        -- restarts (within a single deploy) but NOT Render redeploys
        -- (filesystem is ephemeral on the free tier).
        CREATE TABLE IF NOT EXISTS daily_totals (
            utc_date        TEXT PRIMARY KEY,    -- "YYYY-MM-DD"
            by_hour_json    TEXT NOT NULL,       -- {"YYYY-MM-DDTHH": amount}
            total_amount    REAL NOT NULL,
            transfer_count  INTEGER NOT NULL,
            last_updated    REAL NOT NULL        -- epoch seconds
        );
        """)
        conn.commit()


def upsert_daily_total(
    utc_date: str,
    by_hour: dict[str, float],
    total_amount: float,
    transfer_count: int,
    ts: float,
) -> None:
    import json
    with _lock, get_conn() as conn:
        conn.execute(
            """
            INSERT INTO daily_totals (utc_date, by_hour_json, total_amount, transfer_count, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(utc_date) DO UPDATE SET
                by_hour_json   = excluded.by_hour_json,
                total_amount   = excluded.total_amount,
                transfer_count = excluded.transfer_count,
                last_updated   = excluded.last_updated
            """,
            (utc_date, json.dumps(by_hour, separators=(",", ":")), total_amount, transfer_count, ts),
        )
        conn.commit()


def load_daily_totals() -> list[dict]:
    """Return list of {utc_date, by_hour, total_amount, transfer_count,
    last_updated} for every persisted day. Caller deserializes by_hour
    on demand."""
    import json
    rows: list[dict] = []
    with _lock, get_conn() as conn:
        for r in conn.execute(
            "SELECT utc_date, by_hour_json, total_amount, transfer_count, last_updated "
            "FROM daily_totals ORDER BY utc_date"
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
