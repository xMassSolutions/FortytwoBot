from dataclasses import dataclass, field
from typing import Any


@dataclass
class Snapshot:
    received_at: float
    ts: str = ""
    model: str | None = None
    model_short: str | None = None
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
