import asyncio
from typing import Any, Protocol

from models.state import RunState
from models.task import Status, Task, TaskFailure
from orchestration.dependency_graph import DependencyGraph
from orchestration.recovery import RecoveryManager


class Executor(Protocol):
    async def execute(self, task: Task, state: RunState) -> dict[str, Any]: ...


class Scheduler:
    """Run dependency-ready waves concurrently; recover only at the wave barrier."""
    def __init__(self, state: RunState, executors: dict[str, Executor], recovery: RecoveryManager):
        self.state = state
        self.graph = DependencyGraph(state.tasks)
        self.executors = executors
        self.recovery = recovery
        self.steps = 0

    def ready_tasks(self) -> list[Task]:
        for task in self.state.tasks.values():
            if task.status in {Status.PENDING, Status.BLOCKED}:
                if self.graph.satisfied(task):
                    self.state.transition(task, Status.READY, "all dependencies SUCCESS")
                else:
                    self.state.transition(task, Status.BLOCKED, "waiting for dependencies")
        return [t for t in self.state.tasks.values() if t.status == Status.READY]

    async def execute_one(self, task: Task) -> TaskFailure | None:
        if task.status != Status.READY or not self.graph.satisfied(task):
            raise RuntimeError(f"Cannot execute blocked task {task.task_id}")
        task.attempts += 1
        self.state.transition(task, Status.RUNNING, f"Attempt {task.attempts}")
        try:
            task.output = await self.executors[task.executor].execute(task, self.state)
        except TaskFailure as error:
            self.state.emit("OBSERVE", str(error), task.task_id)
            self.state.transition(task, Status.FAILED, str(error))
            return error
        except Exception as error:
            self.state.transition(task, Status.FAILED, f"Unexpected {type(error).__name__}: {error}")
            raise
        self.state.transition(task, Status.SUCCESS)
        return None

    async def run(self) -> None:
        while not all(t.status == Status.SUCCESS for t in self.state.tasks.values()):
            ready = self.ready_tasks()
            if not ready:
                raise RuntimeError("No runnable tasks; failed dependency or deadlock")
            self.steps += 1
            self.state.emit("SCHEDULER", "Ready wave: " + ", ".join(t.task_id for t in ready)
                            + (" (concurrent asyncio tasks)" if len(ready) > 1 else ""))
            results = await asyncio.gather(*(self.execute_one(t) for t in ready), return_exceptions=True)
            fatal: list[str] = []
            for task, result in zip(ready, results):
                if isinstance(result, TaskFailure):
                    if not self.recovery.recover(task, result, self.state):
                        fatal.append(f"{task.task_id}: {result}")
                elif isinstance(result, BaseException):
                    fatal.append(f"{task.task_id}: {type(result).__name__}: {result}")
            if fatal:
                raise RuntimeError("Execution stopped: " + "; ".join(fatal))
