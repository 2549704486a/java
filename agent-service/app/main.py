from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid

from dotenv import load_dotenv

from app.agent import build_agent, run_agent
from app.api_client import BusinessApiClient
from app.config import Settings
from app.logging_config import configure_logging
from app.knowledge.search import open_knowledge_search
from app.mcp_award_tool import discover_award_detail_mcp_tool
from app.services.award_recommendation import AwardRecommendationService
from app.services.points_planning import PointsPlanningService
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
        help="不调用 LLM，直接验证指定奖品的积分规划服务",
    )
    mode.add_argument(
        "--recommend-awards",
        type=int,
        nargs="?",
        const=3,
        metavar="N",
        help="不调用 LLM，直接验证奖品推荐服务；默认推荐 3 个",
    )
    return parser.parse_args()


async def run_agent_cli(
    args: argparse.Namespace,
    settings: Settings,
    skill_registry: SkillRegistry,
    client: BusinessApiClient,
    log_path,
) -> None:
    logger.info(
        "agent_start user_id=%s model=%s log_file=%s",
        args.user_id,
        settings.llm_model,
        log_path,
    )
    knowledge_search = (
        open_knowledge_search(settings) if settings.rag_enabled else None
    )
    try:
        award_detail_tool = None
        if settings.award_detail_transport == "mcp":
            binding = await discover_award_detail_mcp_tool(settings)
            award_detail_tool = binding.tool
        agent = build_agent(
            settings,
            client,
            args.user_id,
            skill_registry,
            knowledge_search=knowledge_search,
            award_detail_tool=award_detail_tool,
        )
        cli_thread_id = f"user:{args.user_id}:session:cli"
        if args.message:
            print(
                await run_agent(
                    agent,
                    args.message,
                    cli_thread_id,
                    uuid.uuid4().hex,
                )
            )
            return

        print("积分规划顾问已启动，输入 exit 退出。")
        while True:
            message = (await asyncio.to_thread(input, "你：")).strip()
            if message.lower() in {"exit", "quit"}:
                return
            if message:
                answer = await run_agent(
                    agent,
                    message,
                    cli_thread_id,
                    uuid.uuid4().hex,
                )
                print(f"顾问：{answer}")
    finally:
        if knowledge_search is not None:
            knowledge_search.close()


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
            plan = PointsPlanningService(client).plan(args.user_id, args.plan_award_id)
            logger.info(
                "points_plan_service_complete user_id=%s award_id=%s "
                "status=%s elapsed_ms=%.2f",
                args.user_id,
                args.plan_award_id,
                plan.status,
                (time.perf_counter() - started) * 1000,
            )
            print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return

        if args.recommend_awards is not None:
            started = time.perf_counter()
            recommendation = AwardRecommendationService(client).recommend(
                args.user_id, args.recommend_awards
            )
            logger.info(
                "award_recommendation_service_complete user_id=%s "
                "limit=%s status=%s elapsed_ms=%.2f",
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

        # CLI 只在进程入口创建一次事件循环；Tool 内部不会隐藏桥接同步/异步。
        asyncio.run(run_agent_cli(args, settings, skill_registry, client, log_path))


if __name__ == "__main__":
    main()
