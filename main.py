"""CLI and artifact export. Run: python main.py --failure replan"""
import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents.agenda_executor import AgendaExecutor
from agents.finalizer import Finalizer
from agents.invitation_executor import InvitationExecutor
from agents.planner import PlannerAgent, task_tree
from agents.speaker_executor import SpeakerExecutor
from agents.venue_executor import VenueExecutor
from config import ALIASES, FAILURE_MODE, MOCK_MODE, MODES, Config
from models.state import RunState
from models.task import Status
from llm.base import BasePlanner
from llm.mock import MockPlanner
from llm.optional_llm import LLMPlanner
from orchestration.granularity import compare_granularity, show_granularity
from orchestration.recovery import RecoveryManager
from orchestration.scheduler import Scheduler
from tools.mock_venue_service import MockVenueService


def build_demo(config: Config, echo: bool = True) -> tuple[RunState, Scheduler]:
    if not MOCK_MODE:
        raise ValueError("Only offline mock mode is implemented")
    planner = PlannerAgent()
    state = RunState(config, planner.plan(config), echo=echo)
    service = MockVenueService(state)
    executors = {"venue": VenueExecutor(service), "agenda": AgendaExecutor(),
                 "speaker": SpeakerExecutor(), "invitation": InvitationExecutor(), "coordinator": Finalizer()}
    return state, Scheduler(state, executors, RecoveryManager(planner, service))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def run_demo(config: Config, output_dir: Path, echo: bool = True, show_graph: bool = False,
                   content_planner: BasePlanner | None = None) -> RunState:
    state, scheduler = build_demo(config, echo)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Never leave a previous successful plan looking like the result of a failed run.
    (output_dir / "final_plan.json").unlink(missing_ok=True)
    write_json(output_dir / "task_tree.json", task_tree())
    (output_dir / "task_dag.mmd").write_text(scheduler.graph.mermaid(), encoding="utf-8")
    try:
        state.section("TASK DECOMPOSITION & PLANNING DEMO")
        goal = (f"Organize a one-day AI Agent Seminar for {config.attendees} students on {config.date}, "
                f"total budget CNY {config.total_budget}, venue budget CNY {config.venue_budget}.")
        state.emit("USER GOAL", goal)
        state.emit("CONFIG", f"date={config.date}; total budget=CNY {config.total_budget}; "
                   f"venue cap=CNY {config.venue_budget}; failure={config.failure}; mode={config.mode}; venues=MOCK")
        state.emit("SCENARIO", "Base: A unavailable / CNY 4500; B available / CNY 4800; C too small. "
                   + ("Using base availability." if config.failure == "replan" else
                      "Scenario overlay: A available" + (", price=CNY 6000." if config.failure == "reflexion" else ".")))
        state.section("1. PLANNING")
        provider = content_planner or (LLMPlanner() if config.mode == "llm" else MockPlanner())
        descriptions = {tid: task.goal for tid, task in state.tasks.items()}
        # Providers only return display text. Core goals, constraints and dependencies stay unchanged.
        text_result = provider.describe(goal, descriptions)
        state.planner_mode = text_result.effective_mode
        state.planner_note = text_result.note
        state.emit("PLANNER MODE", f"requested={config.mode}; effective={state.planner_mode}; {state.planner_note}")
        for tid, description in text_result.descriptions.items():
            state.tasks[tid].input["display_description"] = description
        write_json(output_dir / "initial_tasks.json", [t.to_dict() for t in state.tasks.values()])
        state.emit("PLANNER", "Generated 6 structured tasks")
        for task in state.tasks.values():
            state.emit("TASK", f"{task.name} | executor={task.executor}", task.task_id)
            state.emit("DESCRIPTION", task.input["display_description"], task.task_id)
        state.emit("HTN", "Organize Seminar -> Plan Venue -> " + " -> ".join(state.tasks["T2"].input["primitives"]))
        state.section("1b. TASK GRANULARITY LAB")
        state.granularity_report = await compare_granularity(config)
        show_granularity(state)
        state.section("2. TASK GRAPH")
        for line in scheduler.graph.text().splitlines():
            state.emit("DAG", line)
        if show_graph:
            state.emit("MERMAID", "\n" + scheduler.graph.mermaid())
        state.section("3. EXECUTION")
        await scheduler.run()
        plan = state.tasks["T6"].output
        write_json(output_dir / "final_plan.json", plan)
        state.section("4. FINAL RESULT")
        state.emit("RESULT", "Seminar Plan Completed")
        state.emit("VENUE", f"{plan['venue']['name']} | {plan['date']} | {plan['attendees']} students")
        for session in plan["agenda"]:
            state.emit("AGENDA", f"{session['start']}-{session['end']} {session['topic']}")
        state.emit("SPEAKERS", ", ".join(s["name"] for s in plan["speakers"]))
        state.emit("BUDGET", f"CNY {plan['budget']['total']} / {plan['budget']['limit']}")
        state.emit("INVITATION", "Draft prepared using the confirmed venue (local only)")
        state.emit("EXECUTION METRICS", f"6 main tasks; scheduler steps={scheduler.steps}; "
                   f"task attempts={sum(t.attempts for t in state.tasks.values())}")
        state.section("DEMO COMPLETED")
        return state
    except Exception as error:
        state.emit("STOP", str(error))
        raise
    finally:
        write_json(output_dir / "run_state.json", {
            "config": asdict(config), "completed": all(t.status == Status.SUCCESS for t in state.tasks.values()),
            "tasks": [t.to_dict() for t in state.tasks.values()], "bookings": state.bookings,
            "booking": state.booking, "memory": state.memory, "plan_updates": state.plan_updates,
            "planner_mode": state.planner_mode, "planner_note": state.planner_note,
            "scheduler_steps": scheduler.steps})
        write_json(output_dir / "granularity_report.json", state.granularity_report)
        write_json(output_dir / "events.json", state.events)
        (output_dir / "execution_log.txt").write_text("\n".join(state.logs) + "\n", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Offline multi-agent task planning teaching demo")
    parser.add_argument("--failure", choices=(*MODES, *ALIASES), default=FAILURE_MODE)
    parser.add_argument("--mode", choices=("mock", "llm"), default=Config().mode, help="Optional task-description enhancement")
    parser.add_argument("--granularity", choices=("coarse", "normal", "fine"), default="normal",
                        help="Selected view in the separately measured venue granularity lab")
    parser.add_argument("--show-graph", action="store_true", help="Also print Mermaid DAG source")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "outputs")
    args = parser.parse_args()
    try:
        asyncio.run(run_demo(Config(failure=args.failure, mode=args.mode, granularity=args.granularity),
                             args.output_dir, show_graph=args.show_graph))
    except (RuntimeError, ValueError, OSError) as error:
        print(f"DEMO FAILED: {error}")
        return 1
    print(f"Artifacts: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
