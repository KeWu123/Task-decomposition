import asyncio
from datetime import date
from typing import Any

from models.state import RunState
from models.task import Status, Task, TaskFailure


class Finalizer:
    """Coordinator validates initial requirements and the final integrated plan."""
    async def execute(self, task: Task, state: RunState) -> dict[str, Any]:
        await asyncio.sleep(0)
        if not all(state.tasks[dep].status == Status.SUCCESS for dep in task.dependencies):
            raise TaskFailure("dependency", "Coordinator invoked before dependencies succeeded")
        c = state.config
        if task.task_id == "T1":
            date.fromisoformat(c.date)
            return {"date": c.date, "attendees": c.attendees, "total_budget": c.total_budget,
                    "venue_budget": c.venue_budget, "topic": "AI Agent Seminar"}
        if task.task_id != "T6":
            raise ValueError(f"Unsupported coordinator task: {task.task_id}")
        # Check transitive upstream states too, even when called outside the scheduler.
        if any(state.tasks[tid].status != Status.SUCCESS for tid in ("T1", "T2", "T3", "T4", "T5")):
            raise TaskFailure("dependency", "Finalizer requires every upstream task to succeed")
        venue = state.tasks["T2"].output["venue"]
        agenda = state.tasks["T3"].output["sessions"]
        speakers = state.tasks["T4"].output["speakers"]
        invitation = state.tasks["T5"].output
        active = [b for b in state.bookings.values() if b["status"] == "active"]
        total = venue["price"] + state.tasks["T4"].output["cost"] + c.catering_cost
        covered = {topic for speaker in speakers for topic in speaker["topics"]}
        checks = [
            len(active) == 1,
            bool(state.booking) and state.booking.get("status") == "active",
            venue["capacity"] >= c.attendees and venue["available"],
            venue["price"] <= c.venue_budget and total <= c.total_budget,
            state.tasks["T4"].output["cost"] <= c.speaker_cost,
            invitation["venue"] == venue["name"] and invitation["date"] == c.date,
            bool(agenda) and agenda[0]["start"] == "09:00" and agenda[-1]["end"] == "17:00",
            all(s["start"] < s["end"] for s in agenda),
            all(a["end"] <= b["start"] for a, b in zip(agenda, agenda[1:])),
            all(s["topic"] in covered for s in agenda if s["topic"] != "Lunch"),
        ]
        if active:
            checks.append(active[0]["booking_id"] == state.tasks["T2"].output["booking_id"]
                          and active[0]["venue"] == venue["name"]
                          and active[0]["date"] == c.date
                          and active[0]["capacity"] >= c.attendees
                          and active[0]["price"] == venue["price"])
        if not all(checks):
            raise TaskFailure("validation", "Final plan failed cross-task consistency checks")
        return {"title": "AI Agent Seminar", "date": c.date, "attendees": c.attendees,
                "venue": venue, "booking": dict(active[0]), "agenda": agenda,
                "speakers": speakers, "invitation": invitation,
                "budget": {"limit": c.total_budget, "venue": venue["price"],
                           "speakers": state.tasks["T4"].output["cost"], "catering": c.catering_cost,
                           "total": total, "remaining": c.total_budget - total},
                "mock_mode": True, "planner_mode": state.planner_mode}
