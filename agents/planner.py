from typing import Any, Iterator

from config import Config
from models.state import RunState
from models.task import Task, TaskFailure


def task_tree() -> dict[str, Any]:
    """A small HTN method: the venue compound expands to executable primitives."""
    return {"name": "Organize Seminar", "children": [
        {"name": "Requirement Analysis", "task_id": "T1"},
        {"name": "Plan Venue", "task_id": "T2", "children": [
            {"name": name, "operation": operation} for name, operation in [
                ("Search Venue", "search"), ("Check Capacity", "capacity"),
                ("Check Availability", "availability"), ("Check Budget", "budget"),
                ("Confirm Venue", "confirm")]]},
        {"name": "Plan Agenda", "task_id": "T3"},
        {"name": "Plan Speakers", "task_id": "T4"},
        {"name": "Prepare Invitation", "task_id": "T5"},
        {"name": "Integrate Final Plan", "task_id": "T6"},
    ]}


def primitives(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if "children" not in node:
        yield node
    for child in node.get("children", []):
        yield from primitives(child)


class PlannerAgent:
    def plan(self, config: Config, memory: list[dict[str, str]] | None = None) -> dict[str, Task]:
        check_budget = config.failure != "reflexion" or any(
            item.get("rule") == "check_budget" for item in (memory or []))
        definitions = [
            ("T1", "Requirement Analysis", [], "coordinator", "Validate fixed date, headcount and cost allocations", "Valid date and allocated costs <= total budget", "stop"),
            ("T2", "Venue Planning", ["T1"], "venue", "Find and book a suitable venue", "Capacity, availability, date and budget all valid", "retry / rollback / replan / reflexion"),
            ("T3", "Agenda Design", ["T1"], "agenda", "Design a one-day seminar", "Non-overlapping sessions from 09:00 to 17:00", "stop"),
            ("T4", "Speaker Planning", ["T1"], "speaker", "Assign mock speakers to required topics", "All topics covered within speaker allocation", "stop"),
            ("T5", "Invitation Preparation", ["T2", "T3", "T4"], "invitation", "Prepare an accurate invitation draft", "Uses successful venue, agenda and speakers", "stop"),
            ("T6", "Final Plan Integration", ["T5"], "coordinator", "Integrate and validate the final event plan", "All upstream tasks successful; one valid booking; total within budget", "stop"),
        ]
        tasks = {tid: Task(tid, name, goal, {}, deps, criterion, policy, executor)
                 for tid, name, deps, executor, goal, criterion, policy in definitions}
        for task in tasks.values():
            task.input = {"date": config.date, "attendees": config.attendees,
                          "upstream": list(task.dependencies)}
        tasks["T2"].input.update({"candidate": "Venue A", "check_budget": check_budget,
                                   "venue_budget": config.venue_budget,
                                   "primitives": [n["operation"] for n in primitives(task_tree()["children"][1])]})
        return tasks

    def replan(self, task: Task, state: RunState, venues: list[dict[str, Any]]) -> None:
        old = task.input["candidate"]
        candidates = [v for v in venues if v["name"] != old and v["available"]
                      and v["capacity"] >= state.config.attendees
                      and v["price"] <= state.config.venue_budget]
        if not candidates:
            raise TaskFailure("no_alternative", "No feasible alternative venue")
        task.input["candidate"] = candidates[0]["name"]
        task.output = None
        update = {"task_id": task.task_id, "from": old, "to": task.input["candidate"],
                  "check_budget": task.input["check_budget"]}
        state.plan_updates.append(update)
        state.emit("PLAN UPDATE", f"{old} -> {update['to']}; recheck capacity, availability and budget", task.task_id)
