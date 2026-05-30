"""Matcher (rewards.attach_tx_hashes) behavior — the logic we kept breaking.
Pure: no DB, no chain. Builds a tracker with hand-set today_transfers."""
import datetime as dt

from rewards import RewardsTracker, _Transfer

DAY = "2026-05-29"
MID = int(dt.datetime.fromisoformat(DAY).replace(tzinfo=dt.timezone.utc).timestamp())


def at(h, m, s):
    return MID + h * 3600 + m * 60 + s


def match(transfers, rounds):
    """transfers: [(amount, tx, block, ts)]; rounds: list of dicts.
    Returns the tx_hash assigned to each round (in input order)."""
    t = RewardsTracker(wallet="0x")
    t.today_utc_date = DAY
    t.today_midnight_ts = MID
    t.today_transfers = [
        _Transfer(amount=a, tx_hash=tx, block_number=b, log_index=0, ts=ts)
        for (a, tx, b, ts) in transfers
    ]
    out = RewardsTracker.attach_tx_hashes(t, [dict(r) for r in rounds], DAY)
    return [r.get("tx_hash") for r in out]


def R(h, hms, dur=30, participated=True, tx=None):
    return {"hash": h, "completed_iso": hms, "duration_s": dur,
            "participated": participated, "tx_hash": tx}


def test_normal_sequential():
    assert match(
        [(1.0, "txA", 1, at(14, 0, 40)), (2.0, "txB", 2, at(14, 5, 50))],
        [R("A", "14:00:20"), R("B", "14:05:25", dur=40)],
    ) == ["txA", "txB"]


def test_observer_never_matched():
    out = match([(1.0, "tx", 1, at(12, 0, 30))],
                [R("OBS", "12:00:00", participated=False), R("Q", "13:00:00")])
    assert out[0] is None


def test_forward_bias_prefers_post_completion():
    # both transfers fall in the strict window; the one AFTER completion wins.
    assert match(
        [(1.0, "early", 1, at(14, 8, 0)), (2.0, "real", 2, at(14, 11, 0))],
        [R("X", "14:10:00", dur=600)],
    ) == ["real"]


def test_deferred_relaxed_pass():
    # reward +24min lands inside the relaxed (30min) forward window.
    assert match([(1.0, "tx", 1, at(14, 25, 0))], [R("D", "14:01:00", dur=50)]) == ["tx"]


def test_gap_fill_late_reward():
    # reward beyond every +-window but inside the inter-round gap -> Pass 3.
    assert match(
        [(1.0, "late", 1, at(14, 45, 0))],
        [R("A", "14:00:00", dur=60), R("B", "16:00:00", dur=60)],
    ) == ["late", None]


def test_no_runaway_stale_round_stays_unmatched():
    # an early round with no nearby transfer must not grab a far-later one.
    assert match(
        [(1.0, "far", 1, at(14, 0, 0))],
        [R("X", "10:00:00", dur=60), R("Y", "13:59:50", dur=30)],
    ) == [None, "far"]


def test_prefill_blocks_cross_round_dup():
    # X already carries tx T (as if prefilled from the DB) -> T is in
    # already_claimed and can't be re-attached to Y.
    assert match(
        [(1.0, "T", 1, at(14, 0, 30))],
        [R("X", "14:00:00", tx="T"), R("Y", "14:00:10")],
    ) == ["T", None]
