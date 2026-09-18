from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import Config
from models.task import Status, Task
from orchestration.reflection import ReflectionMemory


@dataclass
class RunState:
    config: Config
    tasks: dict[str, Task]
    echo: bool = True
    logs: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    bookings: dict[str, dict[str, Any]] = field(default_factory=dict)
    booking: dict[str, Any] | None = None
    reflection_memory: ReflectionMemory = field(default_factory=ReflectionMemory)
    plan_updates: list[dict[str, Any]] = field(default_factory=list)
    planner_mode: str = "mock"
    planner_note: str = "Deterministic mock descriptions"
    granularity_report: dict[str, Any] = field(default_factory=dict)

    @property
    def memory(self) -> list[dict[str, str]]:
        return self.reflection_memory.entries

    def emit(self, tag: str, message: str, task_id: str = "", *,
             old_status: str | None = None, new_status: str | None = None,
             failure_type: str | None = None, recovery_action: str | None = None) -> None:
        line = f"[{tag}] {task_id + ' ' if task_id else ''}{message}"
        task = self.tasks.get(task_id)
        event = {"sequence": len(self.events) + 1,
                 "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "task_id": task_id, "task_name": task.name if task else None,
                 "old_status": old_status, "new_status": new_status,
                 "executor": task.executor if task else None, "event": tag, "tag": tag,
                 "failure_type": failure_type, "recovery_action": recovery_action,
                 "message": message}
        self.events.append(event)
        self.logs.append(" | ".join(f"{key}={value if value is not None else '-'}" for key, value in event.items() if key != "tag"))
        if self.echo:
            print(line)

    def section(self, title: str) -> None:
        line = f"\n{'=' * 64}\n{title}\n{'=' * 64}"
        self.logs.append(line)
        if self.echo:
            print(line)

    def transition(self, task: Task, status: Status, reason: str = "") -> None:
        if task.status == status:
            return
        previous = task.status
        allowed = {
            Status.PENDING: {Status.BLOCKED, Status.READY},
            Status.BLOCKED: {Status.READY},
            Status.READY: {Status.RUNNING},
            Status.RUNNING: {Status.SUCCESS, Status.FAILED},
            Status.FAILED: {Status.BLOCKED},
            Status.SUCCESS: set(),
        }
        if status not in allowed[previous]:
            raise RuntimeError(f"Illegal transition: {previous} -> {status}")
        task.status = status
        task.history.append({"from": previous.value, "to": status.value,
                             "attempt": task.attempts, "reason": reason})
        self.emit("STATUS", f"{previous.value} -> {status.value}" + (f" ({reason})" if reason else ""),
                  task.task_id, old_status=previous.value, new_status=status.value)
