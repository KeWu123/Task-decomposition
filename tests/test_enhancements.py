import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from agents.finalizer import Finalizer
from agents.invitation_executor import InvitationExecutor
from config import Config
from llm.mock import MockPlanner
from llm.optional_llm import LLMPlanner, request_response
from main import build_demo, run_demo
from models.task import Status, TaskFailure
from orchestration.granularity import compare_granularity


def response_with(descriptions):
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(descriptions)}]}]}


class EnhancementTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependencies_release_ready_tasks(self):
        state, scheduler = build_demo(Config(), echo=False)
        first = scheduler.ready_tasks()
        await scheduler.execute_one(first[0])
        self.assertEqual([t.task_id for t in scheduler.ready_tasks()], ["T2", "T3", "T4"])
        self.assertEqual(state.tasks["T5"].status, Status.BLOCKED)

    async def test_invitation_executor_dependency_guard(self):
        state, _ = build_demo(Config(), echo=False)
        with self.assertRaises(TaskFailure):
            await InvitationExecutor().execute(state.tasks["T5"], state)

    async def test_finalizer_checks_transitive_dependencies(self):
        state, scheduler = build_demo(Config(), echo=False)
        await scheduler.run()
        self.assertEqual(state.tasks["T6"].dependencies, ["T5"])
        state.tasks["T2"].status = Status.FAILED
        with self.assertRaises(TaskFailure):
            await Finalizer().execute(state.tasks["T6"], state)

    def test_cancel_clears_current_booking_immediately(self):
        state, scheduler = build_demo(Config(failure="rollback"), echo=False)
        service = scheduler.recovery.service
        booking = service.book(service.venues[0])
        self.assertIsNotNone(state.booking)
        service.cancel(booking["booking_id"])
        self.assertIsNone(state.booking)
        self.assertEqual(state.bookings[booking["booking_id"]]["status"], "cancelled")

    async def test_granularity_counts_come_from_real_execution(self):
        report = await compare_granularity(Config(granularity="fine"))
        self.assertEqual(report["selected"], "fine")
        outputs = []
        events = []
        for level, count in (("coarse", 1), ("normal", 3), ("fine", 8)):
            run = report["comparison"][level]
            self.assertEqual(run["number_of_tasks"], count)
            self.assertEqual(run["scheduler_steps"], count)
            self.assertEqual(run["execution_events"], len(run["events"]))
            self.assertEqual(run["primitive_actions"], 8)
            self.assertEqual(run["dependency_handoffs"], count - 1)
            self.assertTrue(all(t["status"] == "SUCCESS" for t in run["tasks"]))
            outputs.append(run["output"])
            events.append(run["execution_events"])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        self.assertLess(events[0], events[1])
        self.assertLess(events[1], events[2])

    async def test_lifecycle_log_and_failure_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            state = await run_demo(Config(failure="rollback"), Path(directory), echo=False)
            required = {"timestamp", "task_id", "task_name", "old_status", "new_status",
                        "executor", "event", "failure_type", "recovery_action"}
            for event in state.events:
                self.assertTrue(required <= set(event))
                self.assertIsNotNone(datetime.fromisoformat(event["timestamp"]).tzinfo)
                if event["event"] == "STATUS":
                    self.assertIsNotNone(event["old_status"])
                    self.assertIsNotNone(event["new_status"])
            decisions = [e for e in state.events if e["event"] == "RECOVERY DECISION"]
            self.assertEqual([e["recovery_action"] for e in decisions], ["ROLLBACK", "REPLAN"])
            self.assertTrue(all(e["failure_type"] == "SIDE_EFFECT_ERROR" for e in decisions))
            log = (Path(directory) / "execution_log.txt").read_text(encoding="utf-8")
            self.assertIn("old_status=RUNNING | new_status=FAILED", log)
            self.assertIn("recovery_action=ROLLBACK", log)
            self.assertIn("assigned_executor", state.tasks["T2"].to_dict())

    async def test_llm_without_key_completes_via_mock(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_MODEL": ""}), \
                tempfile.TemporaryDirectory() as directory, \
                patch("llm.optional_llm.urlopen", side_effect=AssertionError("Network must not be used")):
            state = await run_demo(Config(mode="llm"), Path(directory), echo=False)
        self.assertEqual(state.planner_mode, "mock")
        self.assertIn("OPENAI_API_KEY is not set", state.planner_note)
        self.assertEqual(state.tasks["T6"].status, Status.SUCCESS)

    async def test_llm_success_changes_only_display_text(self):
        observed = {}

        def transport(payload, key, timeout):
            observed.update(payload)
            source = json.loads(payload["input"])["task_descriptions"]
            return response_with({tid: f"Enhanced description for {tid}" for tid in source})

        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-only", "OPENAI_MODEL": "test-model"}), \
                tempfile.TemporaryDirectory() as directory:
            state = await run_demo(Config(mode="llm"), Path(directory), echo=False,
                                   content_planner=LLMPlanner(transport))
        baseline, _ = build_demo(Config(), echo=False)
        for tid, task in state.tasks.items():
            self.assertEqual(task.dependencies, baseline.tasks[tid].dependencies)
            self.assertEqual(task.success_criteria, baseline.tasks[tid].success_criteria)
            self.assertEqual(task.goal, baseline.tasks[tid].goal)
            self.assertEqual(task.recovery_policy, baseline.tasks[tid].recovery_policy)
            self.assertEqual(task.executor, baseline.tasks[tid].executor)
            self.assertEqual(task.input["display_description"], f"Enhanced description for {tid}")
        self.assertEqual(state.planner_mode, "llm")
        self.assertFalse(observed["store"])
        self.assertNotIn("tools", observed)

    def test_mock_mode_never_uses_network_even_with_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-only"}), \
                patch("llm.optional_llm.urlopen", side_effect=AssertionError("Network forbidden")):
            result = MockPlanner().describe("goal", {"T1": "baseline"})
        self.assertEqual(result.effective_mode, "mock")


class LLMValidationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-only", "OPENAI_MODEL": "test-model"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.descriptions = {f"T{i}": f"Task {i}" for i in range(1, 7)}

    def test_missing_model_falls_back_without_request(self):
        with patch.dict(os.environ, {"OPENAI_MODEL": ""}):
            result = LLMPlanner(lambda *_: self.fail("Should not call transport")).describe("goal", self.descriptions)
        self.assertEqual(result.effective_mode, "mock")

    def test_http_timeout_and_invalid_json_fall_back(self):
        for error in (TimeoutError("private data"), OSError("unit-test-only"), ValueError("private data")):
            def transport(*_):
                raise error
            result = LLMPlanner(transport).describe("goal", self.descriptions)
            self.assertEqual(result.descriptions, self.descriptions)
            self.assertEqual(result.effective_mode, "mock")
            self.assertNotIn("private data", result.note)
            self.assertNotIn("unit-test-only", result.note)

    def test_invalid_and_control_bearing_outputs_are_rejected(self):
        extra = dict(self.descriptions, dependencies=["T6"])
        missing = dict(self.descriptions)
        del missing["T6"]
        bad_text = dict(self.descriptions, T1="\x1b[2Jfake log")
        for parsed in (extra, missing, bad_text, {}, dict(self.descriptions, T1="x" * 241)):
            result = LLMPlanner(lambda *_: response_with(parsed)).describe("goal", self.descriptions)
            self.assertEqual(result.effective_mode, "mock")
            self.assertEqual(result.descriptions, self.descriptions)

    def test_refusal_incomplete_and_malformed_responses_fall_back(self):
        for response in ({"status": "incomplete"}, {"status": "completed", "output": []},
                         {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
                         {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not JSON"}]}]}):
            result = LLMPlanner(lambda *_: response).describe("goal", self.descriptions)
            self.assertEqual(result.effective_mode, "mock")

    def test_unresponsive_transport_cannot_block_completion(self):
        def slow_transport(*_):
            time.sleep(0.2)
            return response_with(self.descriptions)
        start = time.monotonic()
        result = LLMPlanner(slow_transport, deadline=0.01).describe("goal", self.descriptions)
        self.assertLess(time.monotonic() - start, 0.15)
        self.assertEqual(result.effective_mode, "mock")
        self.assertIn("TimeoutError", result.note)

    def test_request_uses_expected_endpoint_auth_and_timeout(self):
        class FakeResponse:
            def __enter__(inner):
                return inner
            def __exit__(inner, *_):
                return None
            def read(inner, size):
                self.assertEqual(size, 65537)
                return b'{"status":"completed","output":[]}'
        with patch("llm.optional_llm.urlopen", return_value=FakeResponse()) as opener:
            request_response({"model": "test-model"}, "unit-test-only", 5.0)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer unit-test-only")
        self.assertEqual(opener.call_args.kwargs["timeout"], 5.0)


if __name__ == "__main__":
    unittest.main()
