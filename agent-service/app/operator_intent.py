from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import Settings


logger = logging.getLogger(__name__)


class OperatorIntent(str, Enum):
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    PLAN_REQUEST = "PLAN_REQUEST"
    ACTION_REQUEST = "ACTION_REQUEST"


class OperatorIntentDecision(BaseModel):
    intent: OperatorIntent
    confidence: float = Field(ge=0, le=1)
    requested_action: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=200)


INTENT_CLASSIFIER_PROMPT = """
你负责判断积分激励运营人员当前这句话的主要意图，只分类，不回答业务问题。

分类规则：
1. KNOWLEDGE_QUERY：询问概念、原理、流程、方法、现状或“怎么做”。这类问题是在获取信息，不代表要求立即执行。
2. PLAN_REQUEST：要求分析数据、设计方案、形成规划或生成活动草案。
3. ACTION_REQUEST：明确要求现在执行会改变业务状态的动作，例如立即发布、批准、拒绝、修改线上规则或向用户发送通知。

注意：
- “怎么触达用户”是 KNOWLEDGE_QUERY，不是 ACTION_REQUEST。
- “帮我设计用户触达方案”是 PLAN_REQUEST。
- “现在向这批用户发送通知”是 ACTION_REQUEST。
- 不要因为句子中出现“发布”“触达”等名词就判定为执行，必须存在明确的执行要求。
""".strip()


class OperatorIntentRouter:
    """在运营 Agent 之前输出可记录、可测试的结构化意图。"""

    def __init__(self, runnable: Any) -> None:
        self._runnable = runnable

    @classmethod
    def from_settings(cls, settings: Settings) -> "OperatorIntentRouter":
        model = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.require_llm_api_key(),
            base_url=settings.llm_base_url,
            temperature=0,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )
        # 兼容当前 OpenAI 协议模型服务；默认 json_schema 模式并非所有服务都支持。
        return cls(
            model.with_structured_output(
                OperatorIntentDecision,
                method="function_calling",
            )
        )

    def classify(
        self,
        message: str,
        request_id: str,
    ) -> OperatorIntentDecision:
        started = time.perf_counter()
        fallback = False
        try:
            raw_decision = self._runnable.invoke(
                [
                    SystemMessage(content=INTENT_CLASSIFIER_PROMPT),
                    HumanMessage(content=message),
                ]
            )
            decision = OperatorIntentDecision.model_validate(raw_decision)
        except Exception as exc:
            fallback = True
            decision = fallback_operator_intent(message)
            logger.warning(
                "operator_intent_classifier_failed request_id=%s error_type=%s",
                request_id,
                exc.__class__.__name__,
            )
        logger.info(
            "operator_intent_decision request_id=%s intent=%s confidence=%.2f "
            "fallback=%s elapsed_ms=%.2f",
            request_id,
            decision.intent.value,
            decision.confidence,
            fallback,
            (time.perf_counter() - started) * 1000,
        )
        return decision


def fallback_operator_intent(message: str) -> OperatorIntentDecision:
    """模型分类失败时使用保守规则；该结果绝不直接授权业务写操作。"""

    normalized = "".join(message.lower().split())
    action_markers = ("现在", "立即", "马上", "直接", "立刻")
    write_actions = ("发送", "触达", "发布", "批准", "拒绝", "修改", "删除")
    if any(marker in normalized for marker in action_markers) and any(
        action in normalized for action in write_actions
    ):
        return OperatorIntentDecision(
            intent=OperatorIntent.ACTION_REQUEST,
            confidence=0.55,
            requested_action="业务写操作",
            reason="结构化分类不可用，保守规则识别到立即执行表达",
        )

    planning_markers = ("方案", "规划", "草案", "设计", "分析", "生成")
    if any(marker in normalized for marker in planning_markers):
        return OperatorIntentDecision(
            intent=OperatorIntent.PLAN_REQUEST,
            confidence=0.55,
            reason="结构化分类不可用，保守规则识别到规划表达",
        )

    return OperatorIntentDecision(
        intent=OperatorIntent.KNOWLEDGE_QUERY,
        confidence=0.5,
        reason="结构化分类不可用，默认按只读知识咨询处理",
    )
