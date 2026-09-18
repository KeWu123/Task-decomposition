from dataclasses import dataclass, field


@dataclass
class ReflectionMemory:
    """Small, explicit within-run memory; the planner consumes the structured rule."""
    entries: list[dict[str, str]] = field(default_factory=list)

    def learn_budget_rule(self) -> dict[str, str]:
        entry = {
            "reflection": "Previous strategy failed because budget was not included as a hard constraint.",
            "lesson": "Future venue searches must validate capacity, availability and budget.",
            "rule": "check_budget",
        }
        if entry not in self.entries:
            self.entries.append(entry)
        return entry
