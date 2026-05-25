from dataclasses import dataclass, field
from typing import Any


@dataclass
class Snapshot:
    received_at: float
    ts: str = ""
    # Short git SHA of the agent's checked-out code — surfaces in dashboard
    # so operators can see which version each node is running.
    agent_version: str | None = None
    model: str | None = None
    model_short: str | None = None
    model_size_gb: float | None = None
    # v9.1 diagnostic — model-search breadcrumbs from the PS agent (None on
    # macOS/Linux). Surfaced raw in /v1/dashboard-data for debugging only.
    model_debug: dict[str, Any] | None = None
    capsule_max_tps: int | None = None
    capsule_version: str | None = None
    protocol_version: str | None = None
    capsule_uptime_seconds: int | None = None
    rounds_participated_today: int = 0
    rounds_observed_today: int = 0
    errors_today: int = 0
    first_round_today_iso: str | None = None
    last_round_today_iso: str | None = None
    last_round_duration_s: int | None = None
    last_reward_amount: float | None = None
    last_reward_iso: str | None = None
    rewards_today_total: float | None = None
    wins_today: int = 0
    # Count of `Participant's FOR balance before/after reward` pairs today
    # where after > before — i.e., rewards that landed inside the Capsule's
    # ~7-second snapshot window. wins_today now mirrors participations; this
    # field is the diagnostic for how many rewards were captured in-window.
    rewards_logged_today: int = 0
    tps_current: float | None = None
    symbols_current: float | None = None
    max_symbols: float | None = None
    gpu_name: str | None = None
    gpu_vram_used_mb: int | None = None
    gpu_vram_total_mb: int | None = None
    capsule_pid: int | None = None
    protocol_pid: int | None = None
    capsule_alive: bool = False
    protocol_alive: bool = False
    recent_rounds: list[dict[str, Any]] = field(default_factory=list)
    all_rounds_today: list[dict[str, Any]] = field(default_factory=list)
    rounds_history: dict[str, int] = field(default_factory=dict)
    recent_errors: list[dict[str, Any]] = field(default_factory=list)
    log_extended: list[str] = field(default_factory=list)
    log_capsule: list[str] = field(default_factory=list)


class Store:
    def __init__(self) -> None:
        self._latest: Snapshot | None = None

    @property
    def latest(self) -> Snapshot | None:
        return self._latest

    def set(self, snap: Snapshot) -> None:
        self._latest = snap


store = Store()
