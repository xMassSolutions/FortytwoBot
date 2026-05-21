"""Wallet + subscription + poller-state CRUD."""

import re
import time

from db import get_conn

ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalize_addr(addr: str) -> str | None:
    if not addr:
        return None
    addr = addr.strip()
    if not ADDR_RE.match(addr):
        return None
    return addr.lower()


# ---- watched wallets (dashboard-visible) ----

def add_watched(address: str, label: str | None = None) -> str:
    addr = normalize_addr(address)
    if not addr:
        raise ValueError("invalid address")
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO wallets (address, label, added_at) VALUES (?, ?, ?)",
            (addr, label, int(time.time())),
        )
        conn.commit()
    return addr


def list_watched() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT address, label, added_at FROM wallets ORDER BY added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_watched(address: str) -> bool:
    addr = normalize_addr(address)
    if not addr:
        return False
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM wallets WHERE address=?", (addr,))
        conn.commit()
        return cur.rowcount > 0


# ---- subscriptions (telegram chat -> wallet) ----

def subscribe(chat_id: int, address: str) -> str:
    addr = normalize_addr(address)
    if not addr:
        raise ValueError("invalid address")
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscriptions (chat_id, wallet, created_at) VALUES (?, ?, ?)",
            (chat_id, addr, now),
        )
        # also add to watched so dashboard surfaces it
        conn.execute(
            "INSERT OR IGNORE INTO wallets (address, added_at) VALUES (?, ?)",
            (addr, now),
        )
        conn.commit()
    return addr


def unsubscribe(chat_id: int, address: str) -> bool:
    addr = normalize_addr(address)
    if not addr:
        return False
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE chat_id=? AND wallet=?",
            (chat_id, addr),
        )
        conn.commit()
        return cur.rowcount > 0


def list_subscriptions(chat_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT wallet, created_at FROM subscriptions WHERE chat_id=?",
            (chat_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def chats_for_wallet(address: str) -> list[int]:
    addr = normalize_addr(address)
    if not addr:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT chat_id FROM subscriptions WHERE wallet=?",
            (addr,),
        ).fetchall()
    return [r["chat_id"] for r in rows]


# ---- poller state (key/value) ----

def get_state(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM poller_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO poller_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
