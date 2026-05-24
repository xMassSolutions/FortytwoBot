#!/usr/bin/env python3
"""
FortytwoBot Mac/Linux workstation agent.

Functional parity with push-agent.ps1. Stdlib only — no pip install needed.

Usage:
    python3 push_agent.py \\
        --bot-url https://<service>.onrender.com \\
        --agent-token <token> \\
        --scripts-root ~/FortytwoCLI/fortytwo-p2p-inference-scripts-main \\
        [--once] [--dry-run]

Env vars used as fallback if flags omitted:
    FORTYTWO_BOT_URL
    FORTYTWO_AGENT_TOKEN
    FORTYTWO_SCRIPTS_ROOT

The agent:
  * polls extended_log.txt for new inference events (5s tick)
  * pushes a snapshot on each event, plus a 10-minute heartbeat
  * persists a 30-day rolling hourly-rounds buffer to rounds-history.json
    (next to this script)
  * tails the last 100 lines of each log on every push
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
LINE_TRUNCATE = 500

# Repo root for auto-update: this script lives in <repo>/agent/, parent is the repo.
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_agent_version() -> str | None:
    """Short SHA of HEAD. Returns None if git fails or this isn't a checkout."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def auto_update_check(stamp: str) -> None:
    """Compare local HEAD to origin/main; if different, ff-only pull + exit 0
    so launchd / scheduled task respawns us on the new code. Failures are
    logged and ignored — never crashes the agent.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-remote", "origin", "main"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0 or not r.stdout.strip():
            print(f"[{stamp}] auto-update: ls-remote failed (skipping this cycle)", flush=True)
            return
        remote_sha = r.stdout.split()[0]
        r2 = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        local_sha = r2.stdout.strip() if r2.returncode == 0 else ""
        if not remote_sha or not local_sha or remote_sha == local_sha:
            return
        print(f"[{stamp}] auto-update: remote {remote_sha[:7]} differs from local, pulling…", flush=True)
        pull = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30,
        )
        if pull.returncode == 0:
            print(f"[{stamp}] auto-update: pulled, exiting to restart with new code", flush=True)
            sys.exit(0)   # launchd KeepAlive / scheduled-task restart respawns with new code
        else:
            out = (pull.stdout + " " + pull.stderr).strip()
            print(f"[{stamp}] auto-update: git pull --ff-only failed (probably local divergence) — staying on current code. Output: {out}", flush=True)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[{stamp}] auto-update: exception {type(e).__name__}: {e} (skipping this cycle)", flush=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_today_str() -> str:
    return utc_now().strftime("%Y-%m-%d")


def utc_now_iso() -> str:
    # Round-trippable ISO-8601 with offset, matching the PS agent's "o" format.
    return utc_now().isoformat().replace("+00:00", "Z")


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def truncate(s: str, n: int = LINE_TRUNCATE) -> str:
    return s if len(s) <= n else s[:n]


# ---------- rounds-history.json (30-day rolling hourly buffer) ----------


def read_rounds_history(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            return {}
        return {str(k): int(v) for k, v in obj.items()}
    except Exception:
        return {}


def write_rounds_history(history: dict[str, int], path: Path) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # Silent — buffer rebuilds next tick
        pass


def update_rounds_history(
    all_today: list[dict[str, Any]], today_utc: str, path: Path
) -> dict[str, int]:
    history = read_rounds_history(path)

    # Idempotency: zero today's keys before recounting
    today_prefix = f"{today_utc}T"
    for k in [k for k in history.keys() if k.startswith(today_prefix)]:
        del history[k]

    for r in all_today:
        hour = r.get("hour")
        if hour is None:
            continue
        key = f"{today_utc}T{int(hour):02d}"
        history[key] = history.get(key, 0) + 1

    # Prune > 30 days
    cutoff = (utc_now().date() - __import__("datetime").timedelta(days=30)).isoformat()
    for k in [k for k in history.keys() if len(k) >= 10 and k[:10] < cutoff]:
        del history[k]

    write_rounds_history(history, path)
    return history


# ---------- log tails ----------


def get_log_tail(path: Path, n: int = 100) -> list[str]:
    if not path.exists():
        return []
    try:
        # Read whole file (small enough for typical log sizes); split → keep last n.
        # For very large files this could be optimized with a reverse-byte read,
        # but bandwidth-wise we cap at ~100 lines so the simple approach is fine.
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = [strip_ansi(ln.rstrip("\n")) for ln in lines[-n:]]
        return [truncate(ln) for ln in tail]
    except Exception:
        return []


# ---------- GPU info ----------


def get_gpu_info() -> dict[str, Any]:
    """Primary path: nvidia-smi (FortyTwo node = LLM inference = typically NVIDIA).

    Returns {"name": str|None, "used": int|None, "total": int|None} in MB.
    macOS fallback: system_profiler gives the chipset name only (no VRAM usage
    CLI without paid tools).
    """
    out: dict[str, Any] = {"name": None, "used": None, "total": None}
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            first = r.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            if len(parts) >= 3:
                out["name"] = parts[0]
                out["used"] = int(parts[1])
                out["total"] = int(parts[2])
    except Exception:
        pass
    if not out["name"]:
        try:
            r = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("Chipset Model:"):
                    out["name"] = line.split(":", 1)[1].strip()
                    break
        except Exception:
            pass
    return out


# ---------- parsing helpers ----------

# Matches today's "UTC YYYY-MM-DD ..." line prefix; we accept a flexible date.
def filter_today_lines(content: str, today_utc: str) -> list[str]:
    needle = f"UTC {today_utc}"
    return [ln for ln in content.splitlines() if ln.startswith(needle)]


PARTICIPATION_RE = re.compile(r"Completed inference participation")
# Per-round participation marker — "Participating in inference request <hash>"
# precedes the round-completed line for any round the node was a participant in.
# Used to tag round dicts with `participated: bool` so the bot can avoid
# attaching tx_hashes to observer rounds (which never get on-chain rewards).
PARTICIPATE_HASH_RE = re.compile(r"Participating in inference request (\w{40,})")
ROUND_LINE_RE = re.compile(r"Inference round.*Total time")
ROUND_DETAIL_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}).*Inference round (\w+) completed.*Total time: (\d+)s"
)
ERROR_RE = re.compile(r" ERROR ")
KAD_NOISE_RE = re.compile(r"Kademlia bootstrap is timeout")
IDENTIFY_NOISE_RE = re.compile(r"Identify: error with peer")
TIME_HMS_RE = re.compile(r"(\d{2}:\d{2}:\d{2})")
UTC_PREFIX_RE = re.compile(r"^UTC \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s*")
DURATION_RE = re.compile(r"(\d{2}:\d{2}:\d{2}).*Total time: (\d+)s")

BALANCE_LINE_RE = re.compile(r"FOR balance (before|after) reward")
BAL_BEFORE_RE = re.compile(r"balance before reward:\s*(\d+\.?\d*)")
BAL_AFTER_RE = re.compile(r"balance after reward:\s*(\d+\.?\d*)")
BAL_DATETIME_RE = re.compile(r"UTC (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})")

CAPABILITY_LINE_RE = re.compile(
    r"has max tokens per second:\s*(\d+),?\s*max symbols per second:\s*(\d+)"
)
MODEL_LOCAL_RE = re.compile(r"Using local LLM model: (.+)$")
MODEL_HF_RE = re.compile(r"--llm-hf-model-name\s+(\S+)")
CAPSULE_VERSION_RE = re.compile(r"Fortytwo Capsule current version: (\S+)")
PROTOCOL_VERSION_RE = re.compile(
    r"(?:Protocol version|protocol.+version)[:\s]+v?(\d+\.\d+\.\d+)"
)
RECEIPT_HASH_RE = re.compile(r"receipt hash (0x[0-9a-fA-F]+)")

EVENT_PATTERN_RE = re.compile(
    r"Completed inference participation|Inference round \w+ completed.*Total time"
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# ---------- process detection (macOS + Linux) ----------


def find_pid(name: str) -> int | None:
    try:
        result = subprocess.run(
            ["pgrep", "-x", name], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            return int(line) if line else None
    except Exception:
        pass
    return None


def process_uptime_seconds(pid: int) -> int | None:
    if pid is None:
        return None
    try:
        # `ps -o etimes=` returns seconds since process start (BSD/Linux).
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etimes="],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except Exception:
        pass
    return None


# ---------- Docker process detection ----------


def get_docker_process_info(container: str | None) -> dict[str, Any]:
    """Resolve Capsule/Protocol PIDs + container uptime via Docker.

    Returns {"capsule_pid", "protocol_pid", "protocol_alive", "uptime_seconds"}.
    All values are None / False if container is unset or not running. Used when
    the FortyTwo node runs in a Docker container instead of native host processes.
    """
    out: dict[str, Any] = {
        "capsule_pid": None,
        "protocol_pid": None,
        "protocol_alive": False,
        "uptime_seconds": None,
    }
    if not container:
        return out
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode != 0 or r.stdout.strip() != "true":
            return out

        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.StartedAt}}", container],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            from datetime import datetime as _dt
            try:
                started = _dt.fromisoformat(r.stdout.strip().replace("Z", "+00:00"))
                out["uptime_seconds"] = int((utc_now() - started).total_seconds())
            except Exception:
                pass

        r = subprocess.run(
            ["docker", "top", container],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.splitlines():
                if "FortytwoCapsule" in line:
                    for tok in line.split():
                        if tok.isdigit():
                            out["capsule_pid"] = int(tok)
                            break
                if "FortytwoProtocol" in line:
                    for tok in line.split():
                        if tok.isdigit():
                            out["protocol_pid"] = int(tok)
                            out["protocol_alive"] = True
                            break
    except Exception:
        pass
    return out


# ---------- ready probe ----------


def capsule_ready(url: str = "http://localhost:42442/ready") -> bool:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------- snapshot construction ----------


def get_node_snapshot(
    scripts_root: Path,
    history_file: Path,
    docker_container: str | None = None,
) -> dict[str, Any]:
    ext_log = scripts_root / "extended_log.txt"
    capsule_log = scripts_root / "FortytwoNode" / "debug" / "FortytwoCapsule.log"
    today_utc = utc_today_str()

    ext_content = read_text(ext_log)
    today_lines = filter_today_lines(ext_content, today_utc)

    participations = sum(1 for ln in today_lines if PARTICIPATION_RE.search(ln))
    round_lines = [ln for ln in today_lines if ROUND_LINE_RE.search(ln)]
    observed = len(round_lines)

    error_lines = [
        ln
        for ln in today_lines
        if ERROR_RE.search(ln)
        and not KAD_NOISE_RE.search(ln)
        and not IDENTIFY_NOISE_RE.search(ln)
    ]
    errors = len(error_lines)

    first_round = last_round = last_duration = None
    if round_lines:
        m0 = TIME_HMS_RE.search(round_lines[0])
        if m0:
            first_round = m0.group(1)
        m_last = DURATION_RE.search(round_lines[-1])
        if m_last:
            last_round = m_last.group(1)
            last_duration = int(m_last.group(2))

    # Collect the set of round hashes the node actually PARTICIPATED in
    # ("Participating in inference request <hash>"). Observer rounds appear
    # in the log as completed but never have a participate-marker, and
    # therefore should NOT be paired with on-chain transfers (they didn't
    # get any reward).
    participated_hashes: set[str] = set()
    for ln in today_lines:
        m_p = PARTICIPATE_HASH_RE.search(ln)
        if m_p:
            participated_hashes.add(m_p.group(1))

    # Build all_today by walking all today_lines in order — tracking the
    # most-recent "receipt hash 0x…" line (the on-chain Monad tx that paid
    # the round's reward, when present in older Capsule log formats).
    # Pair it with the next "Inference round X completed" line, then reset
    # so the next round doesn't inherit it.
    all_today: list[dict[str, Any]] = []
    last_receipt_hash: str | None = None
    for ln in today_lines:
        m_r = RECEIPT_HASH_RE.search(ln)
        if m_r:
            last_receipt_hash = m_r.group(1)
            continue
        m = ROUND_DETAIL_RE.search(ln)
        if m:
            round_hash = m.group(4)
            all_today.append(
                {
                    "completed_iso": f"{m.group(1)}:{m.group(2)}:{m.group(3)}",
                    "hour": int(m.group(1)),
                    "hash": round_hash,
                    "duration_s": int(m.group(5)),
                    "tx_hash": last_receipt_hash,
                    "participated": round_hash in participated_hashes,
                }
            )
            last_receipt_hash = None  # consumed

    # Newest-first last 5 for /recent command parity (kept at 5)
    recent = list(reversed(all_today[-5:])) if all_today else []

    # Last 3 errors, newest-first
    recent_errors: list[dict[str, Any]] = []
    for ln in error_lines[-3:]:
        m_iso = TIME_HMS_RE.search(ln)
        iso = m_iso.group(1) if m_iso else None
        msg = UTC_PREFIX_RE.sub("", ln)
        msg = strip_ansi(msg)
        msg = truncate(msg)
        recent_errors.append({"iso": iso, "message": msg})
    recent_errors.reverse()

    # Capability lines emitted throughout the day:
    #   ... has max tokens per second: N, max symbols per second: N, max tokens size: N, max symbols size: N
    # LATEST line = current capability. HIGHEST value across all lines = all-time max.
    max_tps: int | None = None
    max_symbols: float | None = None
    tps_current: float | None = None
    symbols_current: float | None = None
    cap_matches = list(CAPABILITY_LINE_RE.finditer(ext_content))
    for m in cap_matches:
        tps = int(m.group(1))
        sym = int(m.group(2))
        if max_tps is None or tps > max_tps:
            max_tps = tps
        if max_symbols is None or sym > max_symbols:
            max_symbols = float(sym)
    if cap_matches:
        last = cap_matches[-1]
        tps_current = float(last.group(1))
        symbols_current = float(last.group(2))

    # Reward parser — full-file scan + windowed pairing.
    # Why: the old filter on today_lines (lines starting with ^UTC YYYY-MM-DD)
    # dropped any balance line that didn't have that prefix, and the strict
    # consecutive-pair loop desynced permanently the moment ONE line was lost.
    # Both undercounted wins_today / rewards_today_total.
    # New approach:
    #   - Scan the whole file for ALL balance lines (no prefix filter).
    #   - For each, extract date + time from `UTC YYYY-MM-DD HH:MM:SS`
    #     anywhere in the line (lines without that pattern are skipped).
    #   - Pair each `after` with the nearest preceding `before` within
    #     a 5-line window.
    #   - Sum positive deltas where the after-line's date == today_utc.
    last_reward: float | None = None
    last_reward_time: str | None = None
    rewards_today_total: float | None = None
    # rewards_logged_today = positive-delta pairs (rewards captured inside the
    # Capsule's ~7-second balance-before/after snapshot window). This is a
    # subset of participations — rewards that land on-chain outside the
    # snapshot window aren't counted here (but are visible via chain_rewards
    # on the bot).
    rewards_logged_today = 0

    parsed: list[dict[str, Any]] = []
    for ln in ext_content.splitlines():
        m_bef = BAL_BEFORE_RE.search(ln)
        m_aft = BAL_AFTER_RE.search(ln)
        if m_bef:
            kind, value = "before", float(m_bef.group(1))
        elif m_aft:
            kind, value = "after", float(m_aft.group(1))
        else:
            continue
        m_dt = BAL_DATETIME_RE.search(ln)
        date = m_dt.group(1) if m_dt else None
        time_str = m_dt.group(2) if m_dt else None
        parsed.append({"kind": kind, "value": value, "date": date, "time": time_str})

    total_sum = 0.0
    for i in range(len(parsed)):
        if parsed[i]["kind"] != "after":
            continue
        after_val = parsed[i]["value"]
        before_val: float | None = None
        lookback = max(0, i - 5)
        for j in range(i - 1, lookback - 1, -1):
            if parsed[j]["kind"] == "before":
                before_val = parsed[j]["value"]
                break
        if before_val is None or after_val <= before_val:
            continue
        delta = after_val - before_val
        # Only trust deltas with a parseable date — otherwise the line may be
        # a stray fragment and would pollute last_reward.
        if not parsed[i]["date"]:
            continue
        # Last reward — most recent dated positive delta (across all dates).
        last_reward = round(delta, 6)
        last_reward_time = parsed[i]["time"]
        # Today's totals
        if parsed[i]["date"] == today_utc:
            total_sum += delta
            rewards_logged_today += 1
    if total_sum > 0:
        rewards_today_total = round(total_sum, 6)

    # wins_today now mirrors participations — every round the node participated
    # in counts as a win (rewards land on-chain async, often outside the
    # Capsule's snapshot window, so a positive-delta count under-reports wins).
    wins_today = participations

    # Model
    model: str | None = None
    model_short: str | None = None
    model_size_gb: float | None = None
    capsule_content = read_text(capsule_log)
    last_model_match = None
    for m in MODEL_LOCAL_RE.finditer(capsule_content):
        last_model_match = m
    if last_model_match:
        model = strip_ansi(last_model_match.group(1).strip())
        model_short = Path(model).name
    else:
        last_hf = None
        for m in MODEL_HF_RE.finditer(capsule_content):
            last_hf = m
        if last_hf:
            model_short = last_hf.group(1)
            model = model_short

    # Model file size on disk (GB).
    # The Capsule's "Using local LLM model: <path>" line may give a bare
    # filename or a full path. On a typical install the GGUF lives in an
    # HF cache layout like
    # <scripts_root>/FortytwoNode/model_cache/models--<org>--<repo>/snapshots/<sha>/<file>.gguf
    # The <sha> changes between model updates so we can't hardcode it.
    # Strategy: try direct paths first, then fall back to rglob from
    # scripts_root for any file matching the basename. First non-empty
    # match wins.
    if model:
        candidates: list[Path] = []
        for cand in (Path(model), scripts_root / model):
            if cand.exists() and cand.is_file():
                candidates.append(cand)
        if not candidates and model_short:
            try:
                # rglob walks the whole tree. GGUF basenames are unique
                # enough in practice that this is fast on typical installs.
                for p in scripts_root.rglob(model_short):
                    if p.is_file():
                        candidates.append(p)
                        break  # first match is enough
            except Exception:
                pass
        for p in candidates:
            try:
                size = p.stat().st_size
                if size > 0:
                    model_size_gb = round(size / (1024 ** 3), 2)
                    break
            except Exception:
                continue

    # Process detection: Docker container if configured, else native host processes.
    if docker_container:
        di = get_docker_process_info(docker_container)
        cap_pid = di["capsule_pid"]
        proto_pid = di["protocol_pid"]
        cap_uptime = di["uptime_seconds"]   # container uptime as proxy for capsule uptime
        proto_alive_override = di["protocol_alive"]
    else:
        cap_pid = find_pid("FortytwoCapsule")
        proto_pid = find_pid("FortytwoProtocol")
        cap_uptime = process_uptime_seconds(cap_pid) if cap_pid else None
        proto_alive_override = None

    # Versions
    capsule_version: str | None = None
    last_v = None
    for m in CAPSULE_VERSION_RE.finditer(capsule_content):
        last_v = m
    if last_v:
        capsule_version = last_v.group(1).strip()

    protocol_version: str | None = None
    last_pv = None
    for m in PROTOCOL_VERSION_RE.finditer(ext_content):
        last_pv = m
    if last_pv:
        protocol_version = last_pv.group(1)

    capsule_alive = capsule_ready()
    protocol_alive = (
        proto_alive_override if proto_alive_override is not None
        else proto_pid is not None
    )

    gpu = get_gpu_info()

    rounds_history = update_rounds_history(all_today, today_utc, history_file)
    log_extended = get_log_tail(ext_log, 500)
    log_capsule = get_log_tail(capsule_log, 500)

    return {
        "ts": utc_now_iso(),
        "agent_version": get_agent_version(),
        "model": model,
        "model_short": model_short,
        "model_size_gb": model_size_gb,
        "capsule_max_tps": max_tps,
        "capsule_version": capsule_version,
        "protocol_version": protocol_version,
        "capsule_uptime_seconds": cap_uptime,
        "rounds_participated_today": participations,
        "rounds_observed_today": observed,
        "errors_today": errors,
        "first_round_today_iso": first_round,
        "last_round_today_iso": last_round,
        "last_round_duration_s": last_duration,
        "last_reward_amount": last_reward,
        "last_reward_iso": last_reward_time,
        "rewards_today_total": rewards_today_total,
        "wins_today": wins_today,
        "rewards_logged_today": rewards_logged_today,
        "tps_current": tps_current,
        "symbols_current": symbols_current,
        "max_symbols": max_symbols,
        "gpu_name": gpu["name"],
        "gpu_vram_used_mb": gpu["used"],
        "gpu_vram_total_mb": gpu["total"],
        "capsule_pid": cap_pid,
        "protocol_pid": proto_pid,
        "capsule_alive": capsule_alive,
        "protocol_alive": protocol_alive,
        "recent_rounds": recent,
        "all_rounds_today": all_today,
        "rounds_history": rounds_history,
        "recent_errors": recent_errors,
        "log_extended": log_extended,
        "log_capsule": log_capsule,
    }


# ---------- HTTP push ----------


def post_snapshot(bot_url: str, agent_token: str, snap: dict[str, Any]) -> None:
    body = json.dumps(snap).encode("utf-8")
    url = bot_url.rstrip("/") + "/v1/status"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {agent_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    stamp = utc_now().strftime("%H:%M:%S")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            tag = "ok" if resp.status == 200 else f"HTTP {resp.status}"
            print(
                f"[{stamp}] push {tag}: participations={snap['rounds_participated_today']} "
                f"model={snap.get('model_short')} "
                f"alive={snap['capsule_alive']}/{snap['protocol_alive']}",
                flush=True,
            )
    except urllib.error.HTTPError as e:
        print(f"[{stamp}] push HTTP {e.code}: {e.reason}", flush=True)
    except Exception as e:
        print(f"[{stamp}] push exception: {e}", flush=True)


# ---------- event loop ----------


def event_loop(args: argparse.Namespace, scripts_root: Path, history_file: Path) -> None:
    ext_log = scripts_root / "extended_log.txt"
    # 1 min heartbeat floor. Inference-event pushes still fire immediately
    # on each round completion / participation, so this only matters when
    # the node is idle between events.
    heartbeat_seconds = 60
    poll_interval = 5

    # Auto-update cadence (minutes between git ls-remote checks). 0 disables.
    # Explicit --no-auto-update wins; otherwise FORTYTWO_AUTOUPDATE_MINUTES env;
    # otherwise default 30.
    if args.no_auto_update:
        auto_update_minutes = 0
    else:
        try:
            auto_update_minutes = int(os.environ.get("FORTYTWO_AUTOUPDATE_MINUTES", "30"))
        except ValueError:
            auto_update_minutes = 30
    auto_update_banner = (
        f"auto-update every {auto_update_minutes}m" if auto_update_minutes > 0 else "auto-update disabled"
    )

    print(
        f"Fortytwo agent starting. Mode: event-driven + {heartbeat_seconds}s heartbeat, "
        f"{auto_update_banner}. Bot URL: {args.bot_url}",
        flush=True,
    )

    # Bootstrap push
    last_push = 0.0
    try:
        post_snapshot(args.bot_url, args.agent_token, get_node_snapshot(scripts_root, history_file, args.docker_container))
        last_push = time.time()
    except Exception as e:
        print(f"[bootstrap] {e}", flush=True)

    last_pos = ext_log.stat().st_size if ext_log.exists() else 0
    last_update_check = time.time()  # don't auto-update on the first cycle — wait one interval

    while True:
        time.sleep(poll_interval)

        now = time.time()
        # Auto-update check — exits the process on a successful pull so launchd
        # KeepAlive respawns us on the new code. Failures are logged and ignored.
        if auto_update_minutes > 0 and (now - last_update_check) / 60.0 >= auto_update_minutes:
            stamp = utc_now().strftime("%H:%M:%S")
            auto_update_check(stamp)
            last_update_check = time.time()

        if now - last_push >= heartbeat_seconds:
            stamp = utc_now().strftime("%H:%M:%S")
            print(f"[{stamp}] heartbeat push", flush=True)
            try:
                post_snapshot(
                    args.bot_url, args.agent_token, get_node_snapshot(scripts_root, history_file, args.docker_container)
                )
                last_push = time.time()
            except Exception as e:
                print(f"[heartbeat] {e}", flush=True)

        if not ext_log.exists():
            continue

        current_size = ext_log.stat().st_size
        if current_size < last_pos:
            last_pos = 0
        if current_size <= last_pos:
            continue

        try:
            with ext_log.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                new_content = f.read()
                last_pos = f.tell()
        except Exception as e:
            print(f"[read] {e}", flush=True)
            continue

        for line in new_content.split("\n"):
            if EVENT_PATTERN_RE.search(line):
                stamp = utc_now().strftime("%H:%M:%S")
                print(f"[{stamp}] inference event - pushing snapshot", flush=True)
                try:
                    post_snapshot(
                        args.bot_url,
                        args.agent_token,
                        get_node_snapshot(scripts_root, history_file, args.docker_container),
                    )
                    last_push = time.time()
                except Exception as e:
                    print(f"[event push] {e}", flush=True)


# ---------- CLI ----------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FortytwoBot Mac/Linux workstation agent")
    p.add_argument(
        "--bot-url",
        default=os.environ.get("FORTYTWO_BOT_URL"),
        help="Bot URL (e.g. https://<service>.onrender.com). Defaults to FORTYTWO_BOT_URL env.",
    )
    p.add_argument(
        "--agent-token",
        default=os.environ.get("FORTYTWO_AGENT_TOKEN"),
        help="Shared secret. Defaults to FORTYTWO_AGENT_TOKEN env.",
    )
    p.add_argument(
        "--scripts-root",
        default=os.environ.get("FORTYTWO_SCRIPTS_ROOT"),
        help="Path to fortytwo-p2p-inference-scripts. Required (or FORTYTWO_SCRIPTS_ROOT env).",
    )
    p.add_argument(
        "--docker-container",
        default=os.environ.get("FORTYTWO_DOCKER_CONTAINER"),
        help=(
            "Name (or ID) of the Docker container running the FortyTwo node. When set, "
            "process detection uses `docker top` / `docker inspect` instead of pgrep. "
            "Defaults to FORTYTWO_DOCKER_CONTAINER env. Leave unset for native (non-Docker) installs."
        ),
    )
    p.add_argument("--once", action="store_true", help="Push one snapshot and exit.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the snapshot JSON instead of POSTing. Skips token + URL checks.",
    )
    p.add_argument(
        "--no-auto-update",
        action="store_true",
        help=(
            "Disable the periodic `git pull` cycle. Equivalent to setting "
            "FORTYTWO_AUTOUPDATE_MINUTES=0. Default cadence is 30 min; override "
            "with FORTYTWO_AUTOUPDATE_MINUTES=N (integer minutes; 0 disables)."
        ),
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not args.scripts_root:
        print("ERROR: --scripts-root or FORTYTWO_SCRIPTS_ROOT required", file=sys.stderr)
        return 2

    scripts_root = Path(os.path.expanduser(args.scripts_root)).resolve()
    if not scripts_root.exists():
        print(f"ERROR: scripts root not found: {scripts_root}", file=sys.stderr)
        return 2

    history_file = Path(__file__).parent / "rounds-history.json"

    if not args.dry_run:
        if not args.bot_url:
            print("ERROR: --bot-url or FORTYTWO_BOT_URL required", file=sys.stderr)
            return 2
        if not args.agent_token:
            print("ERROR: --agent-token or FORTYTWO_AGENT_TOKEN required", file=sys.stderr)
            return 2

    if args.dry_run:
        snap = get_node_snapshot(scripts_root, history_file, args.docker_container)
        print(json.dumps(snap, indent=2, default=str))
        return 0

    if args.once:
        post_snapshot(args.bot_url, args.agent_token, get_node_snapshot(scripts_root, history_file, args.docker_container))
        return 0

    try:
        event_loop(args, scripts_root, history_file)
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
