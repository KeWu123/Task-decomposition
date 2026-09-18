"""Deterministic classroom settings; no credentials or network required."""
from dataclasses import dataclass

MOCK_MODE = True
LLM_MODE = False
FAILURE_MODE = "venue_unavailable"
ALIASES = {"transient_error": "retry", "venue_unavailable": "replan", "bad_booking": "rollback"}
MODES = ("none", "retry", "replan", "rollback", "reflexion")


@dataclass(frozen=True)
class Config:
    failure: str = FAILURE_MODE
    mode: str = "llm" if LLM_MODE else "mock"
    granularity: str = "normal"
    date: str = "2026-11-20"
    attendees: int = 50
    total_budget: int = 8000
    venue_budget: int = 5000
    speaker_cost: int = 1500
    catering_cost: int = 1000
    max_attempts: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure", ALIASES.get(self.failure, self.failure))
        if self.failure not in MODES:
            raise ValueError(f"Unknown failure mode: {self.failure}")
        if self.mode not in {"mock", "llm"}:
            raise ValueError(f"Unknown planner mode: {self.mode}")
        if self.granularity not in {"coarse", "normal", "fine"}:
            raise ValueError(f"Unknown granularity: {self.granularity}")
        if self.max_attempts < 1 or self.attendees < 1:
            raise ValueError("Attempts and attendees must be positive")
        if min(self.venue_budget, self.speaker_cost, self.catering_cost) < 0:
            raise ValueError("Costs cannot be negative")
        if self.venue_budget + self.speaker_cost + self.catering_cost > self.total_budget:
            raise ValueError("Budget allocations exceed total budget")
