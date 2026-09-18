from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerText:
    descriptions: dict[str, str]
    effective_mode: str
    note: str


class BasePlanner(ABC):
    """Content-only interface; receives no Task objects or mutable runtime state."""
    @abstractmethod
    def describe(self, goal: str, descriptions: dict[str, str]) -> PlannerText:
        raise NotImplementedError
