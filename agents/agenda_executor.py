import asyncio
from typing import Any

from models.state import RunState
from models.task import Task


class AgendaExecutor:
    async def execute(self, task: Task, state: RunState) -> dict[str, Any]:
        await asyncio.sleep(0)
        sessions = [
            {"start": "09:00", "end": "10:30", "topic": "Agent Foundations"},
            {"start": "10:30", "end": "12:00", "topic": "Task Decomposition and Planning"},
            {"start": "12:00", "end": "13:00", "topic": "Lunch"},
            {"start": "13:00", "end": "15:00", "topic": "Multi-Agent Workshop"},
            {"start": "15:00", "end": "17:00", "topic": "Failure Recovery Lab"},
        ]
        state.emit("OBSERVE", "One-day agenda ready: 09:00-17:00", task.task_id)
        return {"sessions": sessions}
