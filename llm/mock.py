from llm.base import BasePlanner, PlannerText


class MockPlanner(BasePlanner):
    def describe(self, goal: str, descriptions: dict[str, str]) -> PlannerText:
        return PlannerText(dict(descriptions), "mock", "Deterministic local descriptions; no network calls")
