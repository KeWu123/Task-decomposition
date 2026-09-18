import json
import tempfile
import unittest
from pathlib import Path

from agents.finalizer import Finalizer
from agents.planner import PlannerAgent, primitives, task_tree
from config import Config
from main import build_demo, run_demo
from models.task import Status, TaskFailure
from orchestration.dependency_graph import DependencyGraph


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def completed(self, mode: str):
        state, scheduler = build_demo(Config(failure=mode), echo=False)
        await scheduler.run()
        self.assertTrue(all(t.status == Status.SUCCESS for t in state.tasks.values()))
        return state

    async def test_all_five_modes_and_dependency_order(self):
        for mode in ("none", "retry", "replan", "rollback", "reflexion"):
            with self.subTest(mode=mode):
                state = await self.completed(mode)
                observed = {tid: Status.PENDING.value for tid in state.tasks}
                for event in state.events:
                    if event["tag"] != "STATUS":
                        continue
                    target = event["message"].split(" -> ")[1].split()[0]
                    task = state.tasks[event["task_id"]]
                    if target in {"READY", "RUNNING"}:
                        self.assertTrue(all(observed[d] == "SUCCESS" for d in task.dependencies))
                    observed[task.task_id] = target
                self.assertLessEqual(state.tasks["T6"].output["budget"]["total"], 8000)

    async def test_blocked_tasks_cannot_run(self):
        state, scheduler = build_demo(Config(), echo=False)
        self.assertEqual([t.task_id for t in scheduler.ready_tasks()], ["T1"])
        for tid in ("T2", "T3", "T4", "T5", "T6"):
            self.assertEqual(state.tasks[tid].status, Status.BLOCKED)
            with self.assertRaises(RuntimeError):
                await scheduler.execute_one(state.tasks[tid])
            self.assertEqual(state.tasks[tid].attempts, 0)

    async def test_ready_wave_really_overlaps(self):
        state = await self.completed("none")
        branches = {"T2", "T3", "T4"}
        starts = [e["sequence"] for e in state.events if e["task_id"] in branches
                  and e["tag"] == "STATUS" and "-> RUNNING" in e["message"]]
        ends = [e["sequence"] for e in state.events if e["task_id"] in branches
                and e["tag"] == "STATUS" and "-> SUCCESS" in e["message"]]
        self.assertEqual(len(starts), 3)
        self.assertLess(max(starts), min(ends))

    async def test_retry_preserves_strategy(self):
        state = await self.completed("retry")
        self.assertEqual(state.tasks["T2"].attempts, 2)
        self.assertEqual(state.tasks["T2"].output["venue"]["name"], "Venue A")
        self.assertEqual(state.tasks["T2"].input, PlannerAgent().plan(Config(failure="retry"))["T2"].input)
        self.assertEqual(state.plan_updates, [])
        self.assertEqual(state.memory, [])

    async def test_replan_changes_venue_and_invitation(self):
        state = await self.completed("replan")
        self.assertEqual(state.plan_updates[0]["from"], "Venue A")
        self.assertEqual(state.plan_updates[0]["to"], "Venue B")
        self.assertEqual(state.tasks["T5"].output["venue"], "Venue B")
        self.assertNotIn("Venue A", state.tasks["T5"].output["text"])
        self.assertEqual(state.tasks["T3"].attempts, 1)
        self.assertEqual(state.tasks["T4"].attempts, 1)
        self.assertEqual(len(state.bookings), 1)

    async def test_rollback_cancels_real_local_state(self):
        state = await self.completed("rollback")
        self.assertEqual(state.bookings["BK-001"]["status"], "cancelled")
        self.assertEqual(state.bookings["BK-001"]["venue"], "Venue A")
        self.assertEqual(state.bookings["BK-002"]["status"], "active")
        self.assertEqual(state.tasks["T6"].output["booking"]["booking_id"], "BK-002")
        cancellation = next(e["sequence"] for e in state.events if e["tag"] == "ROLLBACK")
        replan = next(e["sequence"] for e in state.events if e["tag"] == "PLAN UPDATE")
        self.assertLess(cancellation, replan)

    async def test_reflexion_changes_executable_strategy(self):
        config = Config(failure="reflexion")
        self.assertFalse(PlannerAgent().plan(config)["T2"].input["check_budget"])
        state = await self.completed("reflexion")
        self.assertEqual(state.memory[0]["rule"], "check_budget")
        self.assertTrue(state.tasks["T2"].input["check_budget"])
        self.assertTrue(PlannerAgent().plan(config, state.memory)["T2"].input["check_budget"])
        self.assertEqual(state.tasks["T2"].output["venue"]["name"], "Venue B")
        self.assertEqual(len(state.bookings), 1)  # Over-budget candidate never booked.

    async def test_finalizer_refuses_incomplete_dependencies(self):
        state, _ = build_demo(Config(), echo=False)
        with self.assertRaises(TaskFailure):
            await Finalizer().execute(state.tasks["T6"], state)

    async def test_finalizer_rejects_stale_invitation(self):
        state = await self.completed("replan")
        state.tasks["T5"].output["venue"] = "Venue A"
        with self.assertRaises(TaskFailure):
            await Finalizer().execute(state.tasks["T6"], state)

    async def test_attempt_limit_stops_and_blocks_downstream(self):
        state, scheduler = build_demo(Config(failure="retry", max_attempts=1), echo=False)
        with self.assertRaisesRegex(RuntimeError, "Execution stopped"):
            await scheduler.run()
        self.assertEqual(state.tasks["T2"].attempts, 1)
        for tid in ("T5", "T6"):
            self.assertEqual(state.tasks[tid].status, Status.BLOCKED)
            self.assertIsNone(state.tasks[tid].output)

    async def test_rollback_even_when_attempt_limit_reached(self):
        state, scheduler = build_demo(Config(failure="rollback", max_attempts=1), echo=False)
        with self.assertRaises(RuntimeError):
            await scheduler.run()
        self.assertFalse(any(b["status"] == "active" for b in state.bookings.values()))
        self.assertIsNone(state.booking)

    async def test_no_feasible_alternative_stops(self):
        state, scheduler = build_demo(Config(failure="replan"), echo=False)
        scheduler.recovery.service.venues[1]["available"] = False
        with self.assertRaises(RuntimeError):
            await scheduler.run()
        self.assertEqual(state.tasks["T6"].attempts, 0)
        self.assertTrue(any("No feasible alternative" in e["message"] for e in state.events))

    async def test_artifacts_and_failed_run_clear_stale_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            await run_demo(Config(failure="none"), path, echo=False)
            self.assertEqual(json.loads((path / "final_plan.json").read_text(encoding="utf-8"))["attendees"], 50)
            with self.assertRaises(RuntimeError):
                await run_demo(Config(failure="retry", max_attempts=1), path, echo=False)
            self.assertFalse((path / "final_plan.json").exists())
            self.assertFalse(json.loads((path / "run_state.json").read_text(encoding="utf-8"))["completed"])

    async def test_deterministic_repeated_runs(self):
        first = await self.completed("rollback")
        second = await self.completed("rollback")
        # Real wall-clock timestamps vary; business decisions and event order must not.
        normalize = lambda events: [{k: v for k, v in e.items() if k != "timestamp"} for e in events]
        self.assertEqual(normalize(first.events), normalize(second.events))
        self.assertEqual(first.tasks["T6"].output, second.tasks["T6"].output)

    def test_cycle_and_missing_dependency_rejected(self):
        for dependencies in (["missing"], ["T6"]):
            tasks = PlannerAgent().plan(Config())
            tasks["T1"].dependencies = dependencies
            with self.assertRaises(ValueError):
                DependencyGraph(tasks)

    def test_htn_drives_venue_operations(self):
        operations = [leaf["operation"] for leaf in primitives(task_tree()["children"][1])]
        self.assertEqual(operations, ["search", "capacity", "availability", "budget", "confirm"])
        self.assertEqual(PlannerAgent().plan(Config())["T2"].input["primitives"], operations)

    def test_failure_aliases(self):
        for alias, mode in (("transient_error", "retry"), ("venue_unavailable", "replan"), ("bad_booking", "rollback")):
            self.assertEqual(Config(failure=alias).failure, mode)


if __name__ == "__main__":
    unittest.main()
