from typing import Any

from models.state import RunState
from models.task import Task, TaskFailure
from tools.mock_venue_service import MockVenueService


class VenueExecutor:
    def __init__(self, service: MockVenueService):
        self.service = service

    async def execute(self, task: Task, state: RunState) -> dict[str, Any]:
        venue: dict[str, Any] = {}
        booking: dict[str, Any] = {}
        state.emit("REASON", f"Check {task.input['candidate']} for {state.config.attendees} people; "
                   f"price limit=CNY {state.config.venue_budget}; "
                   f"budget filter={'ON' if task.input['check_budget'] else 'OFF (injected planner omission)' }.", task.task_id)
        # Execute the primitive sequence produced by the HTN method.
        for operation in task.input["primitives"]:
            state.emit("ACT", operation, task.task_id)
            if operation == "search":
                venue = await self.service.search(task.input["candidate"])
                state.emit("OBSERVE", f"{venue['name']}: capacity={venue['capacity']}, "
                           f"price={venue['price']}, available={venue['available']}", task.task_id)
            elif operation == "capacity":
                self.check(venue["capacity"] >= state.config.attendees, "invalid_plan", "Capacity too small")
                state.emit("OBSERVE", f"capacity PASS: {venue['capacity']} >= {state.config.attendees}", task.task_id)
            elif operation == "availability":
                self.check(venue["available"], "invalid_plan", f"{venue['name']} unavailable")
                state.emit("OBSERVE", "availability PASS", task.task_id)
            elif operation == "budget":
                if task.input["check_budget"]:
                    self.check(venue["price"] <= state.config.venue_budget, "invalid_plan", "Venue exceeds budget")
                    state.emit("OBSERVE", f"budget PASS: {venue['price']} <= {state.config.venue_budget}", task.task_id)
                else:
                    state.emit("OBSERVE", "Planner omitted budget filter; independent validator will check it.", task.task_id)
            elif operation == "confirm":
                # Validation remains independent of the deliberately flawed planner.
                self.check(venue["price"] <= state.config.venue_budget, "strategy", "Budget validator rejected an over-budget candidate")
                booking = self.service.book(venue)
                if booking["capacity"] < state.config.attendees:
                    raise TaskFailure("side_effect", "Confirmed booking has only 30 seats", booking["booking_id"])
            else:
                raise ValueError(f"Unknown primitive: {operation}")
            if operation == "confirm":
                state.emit("OBSERVE", "booking confirmation PASS", task.task_id)
        state.emit("REASON", "All constraints verified; return the confirmed venue.", task.task_id)
        return {"venue": venue, "booking_id": booking["booking_id"]}

    @staticmethod
    def check(condition: bool, kind: str, message: str) -> None:
        if not condition:
            raise TaskFailure(kind, message)
