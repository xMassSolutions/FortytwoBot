"""Shared pytest fixtures. Puts server/ + agent/ on the path (the modules
import each other by bare name) and provides an isolated SQLite DB per test."""
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "agent"))

# app/db read these at import; harmless defaults so imports don't blow up.
os.environ.setdefault("AGENT_TOKEN", "test")
os.environ.setdefault("WALLET", "0x" + "0" * 40)
os.environ.setdefault("DB_PATH", "/tmp/fortytwo_pytest_default.db")


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """A clean SQLite schema per test. get_conn() reads the module globals on
    every call, so monkeypatching them swaps the backend for the test."""
    import db
    monkeypatch.setattr(db, "USE_PG", False)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_schema()
    return db
