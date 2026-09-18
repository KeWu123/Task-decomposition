import asyncio
from typing import Any

from models.state import RunState
from models.task import Task


class SpeakerExecutor:
    async def execute(self, task: Task, state: RunState) -> dict[str, Any]:
        await asyncio.sleep(0)
        state.emit("OBSERVE", "Two fictional speakers confirmed in local mock data", task.task_id)
        return {"cost": state.config.speaker_cost, "speakers": [
            {"name": "Dr. Lin (mock)", "topics": ["Agent Foundations", "Task Decomposition and Planning"]},
            {"name": "Dr. Chen (mock)", "topics": ["Multi-Agent Workshop", "Failure Recovery Lab"]},
        ]}
