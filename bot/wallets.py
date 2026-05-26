"""Wallet CRUD for the dashboard's multi-wallet watch list."""

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


def add_watched(address: str, label: str | None = None) -> str:
    addr = normalize_addr(address)
    if not addr:
        raise ValueError("invalid address")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO wallets (address, label, added_at) VALUES (?, ?, ?) "
            "ON CONFLICT (address) DO NOTHING",
            (addr, label, int(time.time())),
        )
    return addr


def list_watched() -> list[dict]:
    with get_conn() as conn:
        return list(conn.execute(
            "SELECT address, label, added_at FROM wallets ORDER BY added_at DESC"
        ))


def remove_watched(address: str) -> bool:
    addr = normalize_addr(address)
    if not addr:
        return False
    with get_conn() as conn:
        return conn.execute("DELETE FROM wallets WHERE address = ?", (addr,)).rowcount > 0
