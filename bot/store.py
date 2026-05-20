from dataclasses import dataclass, field
from typing import Any


@dataclass
class Snapshot:
    received_at: float
    ts: str = ""
    model: str | None = None
    model_short: str | None = None
    capsule_max_tps: int | None = None
    rounds_participated_today: int = 0
    rounds_observed_today: int = 0
    errors_today: int = 0
    first_round_today_iso: str | None = None
    last_round_today_iso: str | None = None
    last_round_duration_s: int | None = None
    last_reward_amount: float | None = None
    last_reward_iso: str | None = None
    capsule_pid: int | None = None
    protocol_pid: int | None = None
    capsule_alive: bool = False
    protocol_alive: bool = False
    recent_rounds: list[dict[str, Any]] = field(default_factory=list)


class Store:
    def __init__(self) -> None:
        self._latest: Snapshot | None = None

    @property
    def latest(self) -> Snapshot | None:
        return self._latest

    def set(self, snap: Snapshot) -> None:
        self._latest = snap


store = Store()
