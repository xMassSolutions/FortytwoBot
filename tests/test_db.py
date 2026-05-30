"""Persistence layer: upsert COALESCE/MAX semantics, the cross-push tx lookup,
the today summary's DISTINCT, and the additive energy rollup."""


def _round(h, hms, participated=True, tx=None, amt=None, dur=5):
    return {"hash": h, "completed_iso": hms, "duration_s": dur,
            "participated": participated, "tx_hash": tx, "reward_amount": amt}


def test_load_round_tx_returns_only_tx_rows(fresh_db):
    db = fresh_db
    db.upsert_rounds(1, [
        _round("a", "10:00:00", tx="0xA", amt=10),
        _round("b", "11:00:00", tx=None, amt=None),
    ], "2026-05-29", 1.0)
    assert db.load_round_tx(1, "2026-05-29") == {"a": ("0xA", 10.0)}


def test_upsert_coalesce_and_participated_max(fresh_db):
    db = fresh_db
    db.upsert_rounds(1, [_round("a", "10:00:00", participated=False, tx="0xA", amt=7)],
                     "2026-05-29", 1.0)
    # later push: no tx, participated True -> tx/amount kept, participated flips up
    db.upsert_rounds(1, [_round("a", "10:00:00", participated=True, tx=None, amt=None)],
                     "2026-05-29", 2.0)
    row = db.load_rounds(1, None, None, 10)[0]
    assert row["tx_hash"] == "0xA"
    assert row["reward_amount"] == 7.0
    assert row["participated"] is True


def test_today_summary_distinct_collapses_dup_tx(fresh_db):
    db = fresh_db
    db.upsert_rounds(1, [
        _round("a", "10:00:00", tx="0xA", amt=10),
        _round("b", "11:00:00", tx="0xA", amt=10),   # same tx on a second round
        _round("c", "12:00:00", tx=None, amt=None),
    ], "2026-05-29", 1.0)
    assert db.today_round_summary(1, "2026-05-29") == {"participated": 3, "rewarded": 1}


def test_energy_additive_and_windows(fresh_db):
    db = fresh_db
    db.add_energy(1, "2026-05-29", 0.5, 1.0)
    db.add_energy(1, "2026-05-29", 1.5, 2.0)        # additive -> 2.0
    db.add_energy(1, "2026-05-28", 3.0, 1.0)
    db.add_energy(1, "2026-05-29", 0.0, 3.0)        # non-positive: no-op
    rows = {r["utc_date"]: r["kwh"] for r in db.load_energy_since(1, "2026-05-28")}
    assert rows == {"2026-05-29": 2.0, "2026-05-28": 3.0}
