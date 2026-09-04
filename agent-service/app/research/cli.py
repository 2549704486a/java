from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.config import Settings
from app.research.agents import (
    EvidenceReviewRunner,
    ResearchPlanningRunner,
    ResearchToolSession,
    SingleResearchRunner,
    build_evidence_review_agent,
    build_research_planning_agent,
    build_single_research_agents,
)
from app.research.artifacts import ResearchRunStore
from app.research.gates import evaluate_candidate_bundle
from app.research.models import ExperimentArm, load_research_brief
from app.research.web import PublicWebClient
from app.research.workflow import IndependentResearcherRunner, MultiResearchWorkflow


AGENT_SERVICE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = AGENT_SERVICE_ROOT / "research-data" / "runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="公网资料研究与对照工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="执行一份研究简报")
    run_parser.add_argument(
        "--arm",
        required=True,
        choices=[
            ExperimentArm.PROJECT_SINGLE.value,
            ExperimentArm.PROJECT_MULTI.value,
        ],
    )
    run_parser.add_argument("--brief", required=True, type=Path)
    run_parser.add_argument(
        "--experiment-id",
        default="public-research-pilot",
    )
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_research(args)
    raise RuntimeError(f"未知命令：{args.command}")


def run_research(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=AGENT_SERVICE_ROOT / ".env")
    brief = load_research_brief(args.brief)
    arm = ExperimentArm(args.arm)
    run_id = args.run_id or _new_run_id(arm)
    store = ResearchRunStore(args.runs_root)
    run_directory = store.create_run_directory(
        experiment_id=args.experiment_id,
        arm=arm.value,
        run_id=run_id,
    )
    store.write_json_once(run_directory, "brief.json", brief)

    started_at = datetime.now(timezone.utc)
    trace_runner = None
    try:
        settings = Settings.from_env()
        if arm == ExperimentArm.PROJECT_SINGLE:
            with PublicWebClient() as web_client:
                session = ResearchToolSession(brief, web_client)
                collector, finalizer = build_single_research_agents(
                    settings,
                    session,
                )
                trace_runner = SingleResearchRunner(
                    collector,
                    session,
                    finalizer=finalizer,
                )
                run = trace_runner.run(
                    brief,
                    experiment_id=args.experiment_id,
                    run_id=run_id,
                )
            gate_report = evaluate_candidate_bundle(brief, run.bundle)
        else:
            planner = ResearchPlanningRunner(
                build_research_planning_agent(settings)
            )
            researcher = IndependentResearcherRunner(settings)
            reviewer = EvidenceReviewRunner(build_evidence_review_agent(settings))
            run = MultiResearchWorkflow(
                planner,
                researcher,
                reviewer,
            ).run(
                brief,
                experiment_id=args.experiment_id,
                run_id=run_id,
            )
            gate_report = run.gate_report
            store.write_json_once(run_directory, "plan.json", run.plan)
            if run.review is not None:
                store.write_json_once(run_directory, "review.json", run.review)
        store.write_json_once(run_directory, "bundle.json", run.bundle)
        store.write_json_once(run_directory, "summary.json", run.summary)
        store.write_json_once(run_directory, "gate-report.json", gate_report)
    except Exception as exc:
        if trace_runner is not None and trace_runner.trace_events:
            store.write_json_once(
                run_directory,
                "execution-trace.json",
                trace_runner.trace_events,
            )
        failure = {
            "experiment_id": args.experiment_id,
            "run_id": run_id,
            "brief_id": brief.brief_id,
            "brief_version": brief.version,
            "arm": arm.value,
            "status": "FAILED",
            "failure_stage": f"{arm.value}_RUN",
            "error_category": exc.__class__.__name__,
            "message": str(exc),
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        store.write_json_once(run_directory, "failure.json", failure)
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "run_directory": str(run_directory),
                    "error_category": exc.__class__.__name__,
                },
                ensure_ascii=False,
            )
        )
        return 1

    if trace_runner is not None and trace_runner.trace_events:
        store.write_json_once(
            run_directory,
            "execution-trace.json",
            trace_runner.trace_events,
        )
    status = run.summary.status.value
    print(
        json.dumps(
            {
                "status": status,
                "run_directory": str(run_directory),
                "candidate_count": len(run.bundle.candidates),
                "approvable_count": len(gate_report.approvable_candidate_ids),
                "rejected_count": len(gate_report.rejected_candidate_ids),
            },
            ensure_ascii=False,
        )
    )
    return 0 if status == "COMPLETED" else 2


def _new_run_id(arm: ExperimentArm) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{timestamp}-{arm.value.lower().replace('_', '-')}"


if __name__ == "__main__":
    sys.exit(main())
