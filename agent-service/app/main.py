from __future__ import annotations

import argparse
import json
import logging
import time
import uuid

from dotenv import load_dotenv

from app.agent import build_agent, run_agent
from app.api_client import BusinessApiClient
from app.config import Settings
from app.logging_config import configure_logging
from app.skills.award_recommendation import AwardRecommendationSkill
from app.skills.points_plan import PointsPlanningSkill
from app.skills.registry import SkillRegistry


logger = logging.getLogger(__name__)


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
    mode.add_argument(
        "--recommend-awards",
        type=int,
        nargs="?",
        const=3,
        metavar="N",
        help="不调用 LLM，直接验证奖品推荐 Skill；默认推荐 3 个",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    log_path = configure_logging()
    args = parse_args()
    settings = Settings.from_env()
    skill_registry = SkillRegistry()
    if args.user_id <= 0:
        raise SystemExit("--user-id 必须是正整数")

    with BusinessApiClient(
        base_url=settings.business_api_base_url,
        timeout_seconds=settings.business_api_timeout_seconds,
        max_retries=settings.business_api_max_retries,
    ) as client:
        if args.plan_award_id is not None:
            started = time.perf_counter()
            active_definition = skill_registry.activate("points-planning")
            plan = PointsPlanningSkill(client).plan(args.user_id, args.plan_award_id)
            logger.info(
                "points_plan_complete skill=%s version=%s user_id=%s award_id=%s "
                "status=%s elapsed_ms=%.2f",
                active_definition.manifest.name,
                active_definition.manifest.version,
                args.user_id,
                args.plan_award_id,
                plan.status,
                (time.perf_counter() - started) * 1000,
            )
            print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return

        if args.recommend_awards is not None:
            started = time.perf_counter()
            active_definition = skill_registry.activate("award-recommendation")
            recommendation = AwardRecommendationSkill(client).recommend(
                args.user_id, args.recommend_awards
            )
            logger.info(
                "award_recommendation_complete skill=%s version=%s user_id=%s "
                "limit=%s status=%s elapsed_ms=%.2f",
                active_definition.manifest.name,
                active_definition.manifest.version,
                args.user_id,
                args.recommend_awards,
                recommendation.status,
                (time.perf_counter() - started) * 1000,
            )
            print(
                json.dumps(
                    recommendation.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        logger.info(
            "agent_start user_id=%s model=%s log_file=%s",
            args.user_id,
            settings.llm_model,
            log_path,
        )
        agent = build_agent(settings, client, args.user_id, skill_registry)
        cli_thread_id = f"user:{args.user_id}:session:cli"
        if args.message:
            print(run_agent(agent, args.message, cli_thread_id, uuid.uuid4().hex))
            return

        print("积分规划顾问已启动，输入 exit 退出。")
        while True:
            message = input("你：").strip()
            if message.lower() in {"exit", "quit"}:
                return
            if message:
                print(
                    f"顾问：{run_agent(agent, message, cli_thread_id, uuid.uuid4().hex)}"
                )


if __name__ == "__main__":
    main()
