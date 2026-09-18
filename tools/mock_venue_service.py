import asyncio
import json
from pathlib import Path
from typing import Any

from models.state import RunState
from models.task import TaskFailure


class FailureInjector:
    """Scenario overlays isolate failure causes; each run starts from clean data."""
    def __init__(self, mode: str):
        self.mode = mode
        self.search_calls = 0

    def overlay(self, venues: list[dict[str, Any]]) -> None:
        # Base data demonstrates replan; other scenarios isolate a different failure.
        venues[0]["available"] = self.mode != "replan"
        if self.mode == "reflexion":
            venues[0]["price"] = 6000

    def before_search(self) -> None:
        self.search_calls += 1
        if self.mode == "retry" and self.search_calls == 1:
            raise TaskFailure("transient", "API Timeout (injected once)")


class MockVenueService:
    def __init__(self, state: RunState):
        self.state = state
        self.injector = FailureInjector(state.config.failure)
        path = Path(__file__).resolve().parents[1] / "data" / "venues.json"
        self.venues = json.loads(path.read_text(encoding="utf-8"))
        self.injector.overlay(self.venues)

    async def search(self, name: str) -> dict[str, Any]:
        await asyncio.sleep(0)  # Cooperative yield models I/O, without random delays.
        self.injector.before_search()
        for venue in self.venues:
            if venue["name"] == name:
                return dict(venue)
        raise TaskFailure("invalid_plan", f"Unknown venue: {name}")

    def book(self, venue: dict[str, Any], task_id: str = "T2") -> dict[str, Any]:
        booking_id = f"BK-{len(self.state.bookings) + 1:03d}"
        booking = {"booking_id": booking_id, "venue": venue["name"],
                   "date": self.state.config.date, "capacity": venue["capacity"],
                   "price": venue["price"], "status": "active"}
        if self.injector.mode == "rollback" and venue["name"] == "Venue A":
            booking["capacity"] = 30  # Service confirms the wrong room after booking.
        self.state.bookings[booking_id] = booking
        self.state.booking = booking
        self.state.emit("BOOKING", f"Created {booking_id} for {venue['name']}", task_id)
        return booking

    def cancel(self, booking_id: str) -> None:
        booking = self.state.bookings[booking_id]
        booking["status"] = "cancelled"
        if self.state.booking and self.state.booking["booking_id"] == booking_id:
            self.state.booking = None
        self.state.emit("ROLLBACK", f"Cancel booking for {booking['venue']} ({booking_id}); booking = None",
                        "T2", failure_type="SIDE_EFFECT_ERROR", recovery_action="ROLLBACK")
