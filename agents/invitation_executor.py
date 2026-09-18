import asyncio
from typing import Any

from models.state import RunState
from models.task import Status, Task, TaskFailure


class InvitationExecutor:
    """Build a local draft exclusively from confirmed upstream outputs."""
    async def execute(self, task: Task, state: RunState) -> dict[str, Any]:
        await asyncio.sleep(0)
        if any(state.tasks[dep].status != Status.SUCCESS for dep in ("T1", "T2", "T3", "T4")):
            raise TaskFailure("dependency", "Invitation requires confirmed requirements, venue, agenda and speakers")
        requirements = state.tasks["T1"].output
        venue = state.tasks["T2"].output["venue"]
        agenda = state.tasks["T3"].output["sessions"]
        speakers = state.tasks["T4"].output["speakers"]
        names = ", ".join(s["name"] for s in speakers)
        state.emit("INVITATION", f"Prepared local draft using confirmed {venue['name']}", task.task_id)
        return {"date": requirements["date"], "venue": venue["name"], "status": "draft_only",
                "text": f"Join our AI Agent Seminar on {requirements['date']}, 09:00-17:00 at {venue['name']}. "
                        f"For {requirements['attendees']} students. Speakers: {names}. "
                        + "Agenda: " + "; ".join(s["topic"] for s in agenda)}
