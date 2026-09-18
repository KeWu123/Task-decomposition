from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass
class Task:
    task_id: str
    name: str
    goal: str
    input: dict[str, Any]
    dependencies: list[str]
    success_criteria: str
    recovery_policy: str
    assigned_executor: str
    output: dict[str, Any] | None = None
    status: Status = Status.PENDING
    attempts: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def executor(self) -> str:
        return self.assigned_executor

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskFailure(Exception):
    def __init__(self, kind: str, message: str, booking_id: str | None = None):
        super().__init__(message)
        self.kind = kind
        self.booking_id = booking_id

    @property
    def failure_type(self) -> str:
        return {"transient": "TRANSIENT_ERROR", "side_effect": "SIDE_EFFECT_ERROR",
                "invalid_plan": "INVALID_PLAN", "strategy": "STRATEGY_ERROR"}.get(self.kind, self.kind.upper())
