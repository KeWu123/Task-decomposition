from agents.planner import PlannerAgent
from models.state import RunState
from models.task import Status, Task, TaskFailure
from orchestration.dependency_graph import DependencyGraph
from tools.mock_venue_service import MockVenueService


class RecoveryManager:
    def __init__(self, planner: PlannerAgent, service: MockVenueService):
        self.planner = planner
        self.service = service

    def recover(self, task: Task, error: TaskFailure, state: RunState) -> bool:
        state.emit("FAILURE DETECTED", f"Type: {error.failure_type}; {error}", task.task_id,
                   failure_type=error.failure_type)

        def decide(action: str, detail: str = "") -> None:
            state.emit("RECOVERY DECISION", action + (f": {detail}" if detail else ""), task.task_id,
                       failure_type=error.failure_type, recovery_action=action)

        if task.task_id != "T2":
            decide("STOP", "no policy for this task")
            return False
        # Compensate an existing side effect even if the attempt budget is exhausted.
        if error.kind == "side_effect":
            decide("ROLLBACK")
            if not error.booking_id:
                return False
            self.service.cancel(error.booking_id)
        if task.attempts >= state.config.max_attempts:
            decide("STOP", "attempt limit reached")
            return False
        if error.kind == "transient":
            decide("RETRY", "same candidate, same constraints")
        elif error.kind in {"invalid_plan", "side_effect", "strategy"}:
            if error.kind == "strategy":
                decide("REFLEXION")
                memory = state.reflection_memory.learn_budget_rule()
                state.emit("REFLECTION", memory["reflection"], task.task_id)
                state.emit("MEMORY UPDATE", memory["lesson"], task.task_id)
                # Consume structured memory to update the executable plan, not just the log.
                learned = self.planner.plan(state.config, state.memory)
                task.input["check_budget"] = learned["T2"].input["check_budget"]
                state.emit("STRATEGY UPDATE", "check_budget: False -> True", task.task_id)
            decide("REPLAN")
            try:
                self.planner.replan(task, state, self.service.venues)
            except TaskFailure as exhausted:
                decide("STOP", str(exhausted))
                return False
        else:
            decide("STOP", "unsupported failure")
            return False
        for downstream in DependencyGraph(state.tasks).descendants(task.task_id):
            if downstream.status != Status.BLOCKED:
                raise RuntimeError("Recovery expected unexecuted, blocked descendants")
            state.emit("DEPENDENCY", "remains BLOCKED while venue is recovered", downstream.task_id)
        state.transition(task, Status.BLOCKED, "recovery scheduled")
        return True
