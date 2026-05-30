"""Agent telemetry parsing: GPU power summing (multi-GPU + [N/A]) and the
round-hash <-> decided-hash regex agreement that drives participation tagging."""
import push_agent as pa


class _R:
    def __init__(self, rc, out):
        self.returncode = rc
        self.stdout = out


def test_gpu_power_sums_across_gpus(monkeypatch):
    monkeypatch.setattr(pa.subprocess, "run", lambda *a, **k: _R(
        0,
        "RTX 4090, 12000, 24576, 320.5\n"
        "RTX 4090, 11000, 24576, 310.0\n"
        "RTX 4090, 0, 24576, [N/A]",   # unreadable power -> skipped
    ))
    g = pa.get_gpu_info()
    assert g["name"] == "RTX 4090"
    assert g["power_w"] == 630.5


def test_gpu_power_all_na_is_none(monkeypatch):
    monkeypatch.setattr(pa.subprocess, "run", lambda *a, **k: _R(0, "GPU, 1, 2, [N/A]"))
    assert pa.get_gpu_info()["power_w"] is None


def test_round_and_decided_hash_match():
    # Participation tagging relies on these two regexes capturing the IDENTICAL
    # hash token; if a Capsule version changes the format this test fails loud.
    h = "77a789cb200381abe9c25902a428e153850abc3100789f10a41492f29256c153"
    completed = f"UTC 2026-05-29 16:19:32 INFO Inference round {h} completed. Total time: 245s"
    decided = f"UTC 2026-05-29 16:15:27 INFO Capsule has decided to participate in inference request {h}"
    assert pa.ROUND_DETAIL_RE.search(completed).group(4) == h
    assert pa.DECIDED_HASH_RE.search(decided).group(1) == h
