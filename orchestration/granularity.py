"""Measured, isolated venue micro-workflows using the same dependency scheduler."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from typing import Any

from agents.planner import PlannerAgent
from config import Config
from models.state import RunState
from models.task import Task, TaskFailure
from orchestration.recovery import RecoveryManager
from orchestration.scheduler import Scheduler
from tools.mock_venue_service import MockVenueService

OPERATIONS = ["open_source", "query", "read_result", "capacity", "budget", "availability", "confirm", "save_result"]
GROUPS = {
    "coarse": [("Handle Venue", OPERATIONS)],
    "normal": [("Search Venue", OPERATIONS[:3]), ("Validate Constraints", OPERATIONS[3:6]),
               ("Confirm Venue", OPERATIONS[6:])],
    "fine": [(operation.replace("_", " ").title(), [operation]) for operation in OPERATIONS],
}


class VenueStepExecutor:
    def __init__(self, service: MockVenueService):
        self.service = service

    async def execute(self, task: Task, state: RunState) -> dict[str, Any]:
        await asyncio.sleep(0)
        # A dependency's output is the next task's input: real handoffs, not invented counts.
        result = deepcopy(state.tasks[task.dependencies[0]].output) if task.dependencies else {}
        for operation in task.input["operations"]:
            state.emit("ACT", operation, task.task_id)
            if operation == "open_source":
                result["source"] = deepcopy(self.service.venues)
            elif operation == "query":
                result["matches"] = [v for v in result.pop("source") if v["name"] == "Venue B"]
            elif operation == "read_result":
                result["venue"] = result.pop("matches")[0]
            elif operation in {"capacity", "budget", "availability"}:
                venue = result["venue"]
                checks = {"capacity": venue["capacity"] >= state.config.attendees,
                          "budget": venue["price"] <= state.config.venue_budget,
                          "availability": venue["available"]}
                if not checks[operation]:
                    raise TaskFailure("validation", f"Granularity lab failed {operation}")
            elif operation == "confirm":
                result["booking_id"] = self.service.book(result["venue"], task.task_id)["booking_id"]
            elif operation == "save_result":
                result["saved"] = True  # Stored in the Task output, not an external booking service.
            state.emit("OBSERVE", operation + " complete", task.task_id)
        return result


async def compare_granularity(config: Config) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for level, groups in GROUPS.items():
        tasks = {}
        for index, (name, operations) in enumerate(groups, start=1):
            tid = f"G{index}"
            tasks[tid] = Task(tid, name, "Validate and book Venue B", {"operations": list(operations)},
                              [f"G{index - 1}"] if index > 1 else [],
                              "Operations completed with validated output", "stop", "venue_step")
        state = RunState(replace(config, failure="none", mode="mock"), tasks, echo=False)
        service = MockVenueService(state)
        scheduler = Scheduler(state, {"venue_step": VenueStepExecutor(service)}, RecoveryManager(PlannerAgent(), service))
        await scheduler.run()
        reports[level] = {
            "number_of_tasks": len(tasks), "scheduler_steps": scheduler.steps,
            "execution_events": len(state.events),
            "dependency_handoffs": sum(len(t.dependencies) for t in tasks.values()),
            "primitive_actions": sum(e["tag"] == "ACT" for e in state.events),
            "task_names": [t.name for t in tasks.values()],
            "output": list(tasks.values())[-1].output,
            "tasks": [t.to_dict() for t in tasks.values()], "events": state.events,
        }
    return {"selected": config.granularity, "scope": "Isolated venue lab; main seminar DAG remains six tasks",
            "comparison": reports}


def show_granularity(state: RunState) -> None:
    report = state.granularity_report
    selected = report["comparison"][report["selected"]]
    state.emit("GRANULARITY", report["scope"])
    state.emit("SELECTED", f"{report['selected']}: " + " -> ".join(selected["task_names"]))
    state.emit("METRICS", "Level   | Number of Tasks | Scheduler Steps | Execution Events | Handoffs")
    for level, values in report["comparison"].items():
        state.emit("METRICS", f"{level:7} | {values['number_of_tasks']:15} | {values['scheduler_steps']:15} | "
                   f"{values['execution_events']:16} | {values['dependency_handoffs']:8}")
    explanation = {
        "coarse": "One task boundary hides intermediate outputs and makes failure localization harder.",
        "normal": "Search, validate, confirm: independently verifiable outputs and clear dependencies.",
        "fine": "More task boundaries require more scheduler rounds and result handoffs for the same work.",
    }
    state.emit("TRADE-OFF", explanation[report["selected"]])
    state.emit("MEASUREMENT", "All levels executed the same 8 primitive actions; counts are measured, not latency benchmarks.")
