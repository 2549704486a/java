from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from app.agent import build_agent, run_agent
from app.api_client import BusinessApiClient
from app.config import Settings
from app.skills.points_plan import PointsPlanningSkill


logger = logging.getLogger(__name__)


def configure_logging() -> Path:
    service_root = Path(__file__).resolve().parents[1]
    default_log_path = service_root / "logs" / "agent-service.log"
    log_path = Path(os.getenv("AGENT_LOG_FILE") or default_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level_name = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[file_handler], force=True)
    return log_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="积分规划与奖品兑换顾问")
    parser.add_argument("--user-id", type=int, required=True, help="当前用户 ID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--message", help="发送给 Agent 的自然语言问题")
    mode.add_argument(
        "--plan-award-id",
        type=int,
        help="不调用 LLM，直接验证指定奖品的积分规划 Skill",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    log_path = configure_logging()
    args = parse_args()
    settings = Settings.from_env()
    if args.user_id <= 0:
        raise SystemExit("--user-id 必须是正整数")

    with BusinessApiClient(
        base_url=settings.business_api_base_url,
        timeout_seconds=settings.business_api_timeout_seconds,
        max_retries=settings.business_api_max_retries,
    ) as client:
        if args.plan_award_id is not None:
            started = time.perf_counter()
            plan = PointsPlanningSkill(client).plan(args.user_id, args.plan_award_id)
            logger.info(
                "points_plan_complete user_id=%s award_id=%s status=%s elapsed_ms=%.2f",
                args.user_id,
                args.plan_award_id,
                plan.status,
                (time.perf_counter() - started) * 1000,
            )
            print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return

        logger.info(
            "agent_start user_id=%s model=%s log_file=%s",
            args.user_id,
            settings.llm_model,
            log_path,
        )
        agent = build_agent(settings, client, args.user_id)
        if args.message:
            print(run_agent(agent, args.message))
            return

        print("积分规划顾问已启动，输入 exit 退出。")
        while True:
            message = input("你：").strip()
            if message.lower() in {"exit", "quit"}:
                return
            if message:
                print(f"顾问：{run_agent(agent, message)}")


if __name__ == "__main__":
    main()
