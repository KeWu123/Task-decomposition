from models.task import Status, Task


class DependencyGraph:
    def __init__(self, tasks: dict[str, Task]):
        self.tasks = tasks
        for task_id, task in tasks.items():
            if task_id != task.task_id:
                raise ValueError("Task dictionary key must equal task_id")
            if any(dep not in tasks for dep in task.dependencies):
                raise ValueError(f"Unknown dependency for {task.task_id}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("Dependency graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dep in tasks[task_id].dependencies:
                visit(dep)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in tasks:
            visit(task_id)

    def satisfied(self, task: Task) -> bool:
        return all(self.tasks[dep].status == Status.SUCCESS for dep in task.dependencies)

    def descendants(self, task_id: str) -> list[Task]:
        found: set[str] = set()
        frontier = [task_id]
        while frontier:
            parent = frontier.pop()
            for task in self.tasks.values():
                if parent in task.dependencies and task.task_id not in found:
                    found.add(task.task_id)
                    frontier.append(task.task_id)
        return [task for tid, task in self.tasks.items() if tid in found]

    def text(self) -> str:
        return "\n".join(f"{t.task_id} {t.name} <- {', '.join(t.dependencies) or '(root)'}"
                         for t in self.tasks.values())

    def mermaid(self) -> str:
        lines = ["flowchart TD"]
        for task in self.tasks.values():
            lines.append(f'    {task.task_id}["{task.task_id} {task.name}"]')
            lines.extend(f"    {dep} --> {task.task_id}" for dep in task.dependencies)
        return "\n".join(lines) + "\n"
