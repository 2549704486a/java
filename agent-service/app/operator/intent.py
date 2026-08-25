from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, model_validator

from app.config import Settings


logger = logging.getLogger(__name__)


class OperatorIntent(str, Enum):
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    PLAN_REQUEST = "PLAN_REQUEST"
    ACTION_REQUEST = "ACTION_REQUEST"


class OperatorCapability(str, Enum):
    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"
    CAMPAIGN_PLANNING = "CAMPAIGN_PLANNING"
    CAMPAIGN_DRAFT = "CAMPAIGN_DRAFT"
    CAMPAIGN_HISTORY = "CAMPAIGN_HISTORY"
    CAMPAIGN_STANDARD_EFFECT = "CAMPAIGN_STANDARD_EFFECT"
    CUSTOM_ANALYTICS = "CUSTOM_ANALYTICS"
    BUSINESS_ACTION = "BUSINESS_ACTION"


class OperatorTaskSpec(BaseModel):
    """模型理解出的任务描述；真正的 Tool 准入由 Harness 决定。"""

    intent: OperatorIntent
    capability: OperatorCapability
    confidence: float = Field(ge=0, le=1)
    requested_action: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def align_intent_with_capability(self) -> "OperatorTaskSpec":
        expected_intent = {
            OperatorCapability.GENERAL_KNOWLEDGE: OperatorIntent.KNOWLEDGE_QUERY,
            OperatorCapability.CAMPAIGN_HISTORY: OperatorIntent.KNOWLEDGE_QUERY,
            OperatorCapability.CAMPAIGN_STANDARD_EFFECT: OperatorIntent.KNOWLEDGE_QUERY,
            OperatorCapability.CAMPAIGN_PLANNING: OperatorIntent.PLAN_REQUEST,
            OperatorCapability.CAMPAIGN_DRAFT: OperatorIntent.PLAN_REQUEST,
            OperatorCapability.CUSTOM_ANALYTICS: OperatorIntent.PLAN_REQUEST,
            OperatorCapability.BUSINESS_ACTION: OperatorIntent.ACTION_REQUEST,
        }[self.capability]
        # capability 决定运行路径，避免模型给出互相矛盾的两套分类。
        self.intent = expected_intent
        return self


# 保留旧名称，避免尚未迁移的调用方因模型升级立即失效。
OperatorIntentDecision = OperatorTaskSpec


INTENT_CLASSIFIER_PROMPT = """
你负责判断积分激励运营人员当前这句话的主要意图，只分类，不回答业务问题。

先选择具体 capability，再按映射填写 intent：

capability：
1. GENERAL_KNOWLEDGE：询问概念、原理、流程、方法或“怎么做”。
2. CAMPAIGN_PLANNING：要求分析现有信息、设计活动方案，但没有要求保存正式草案。
3. CAMPAIGN_DRAFT：明确要求生成并保存一份正式活动草案。
4. CAMPAIGN_HISTORY：查看最近活动、活动列表或历史状态，不要求分析效果。
5. CAMPAIGN_STANDARD_EFFECT：查看某个或最近活动已有的标准漏斗、任务完成率、兑换率或 Lift。
6. CUSTOM_ANALYTICS：要求按自定义时间窗、客群条件、事件先后、用户交集或自定义公式重新统计指标。
7. BUSINESS_ACTION：明确要求现在执行发布、批准、拒绝、修改规则或触达用户等写操作。

intent 映射：
1. KNOWLEDGE_QUERY：询问概念、原理、流程、方法、现状或“怎么做”。这类问题是在获取信息，不代表要求立即执行。
2. PLAN_REQUEST：要求分析数据、设计方案、形成规划或生成活动草案。
3. ACTION_REQUEST：明确要求现在执行会改变业务状态的动作，例如立即发布、批准、拒绝、修改线上规则或向用户发送通知。

注意：
- “怎么触达用户”是 KNOWLEDGE_QUERY，不是 ACTION_REQUEST。
- “帮我设计用户触达方案”是 PLAN_REQUEST。
- “现在向这批用户发送通知”是 ACTION_REQUEST。
- “查看活动历史以及收益”是 CAMPAIGN_STANDARD_EFFECT，不是 CUSTOM_ANALYTICS。
- “计算最近 7 天积分不少于 500 的用户中，阅读后完成兑换的比例”是 CUSTOM_ANALYTICS，因为它包含时间窗、客群条件、用户交集和事件顺序。
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
    ) -> OperatorTaskSpec:
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
        decision = enforce_task_guard(message, decision)
        logger.info(
            "operator_intent_decision request_id=%s intent=%s confidence=%.2f "
            "capability=%s fallback=%s elapsed_ms=%.2f",
            request_id,
            decision.intent.value,
            decision.confidence,
            decision.capability.value,
            fallback,
            (time.perf_counter() - started) * 1000,
        )
        return decision


def fallback_operator_intent(message: str) -> OperatorTaskSpec:
    """模型分类失败时使用保守规则；该结果绝不直接授权业务写操作。"""

    normalized = "".join(message.lower().split())
    action_markers = ("现在", "立即", "马上", "直接", "立刻")
    write_actions = ("发送", "触达", "发布", "批准", "拒绝", "修改", "删除")
    if any(marker in normalized for marker in action_markers) and any(
        action in normalized for action in write_actions
    ):
        return OperatorIntentDecision(
            intent=OperatorIntent.ACTION_REQUEST,
            capability=OperatorCapability.BUSINESS_ACTION,
            confidence=0.55,
            requested_action="业务写操作",
            reason="结构化分类不可用，保守规则识别到立即执行表达",
        )

    if _looks_like_custom_analytics(normalized):
        return OperatorIntentDecision(
            intent=OperatorIntent.PLAN_REQUEST,
            capability=OperatorCapability.CUSTOM_ANALYTICS,
            confidence=0.6,
            requested_action="自定义运营指标计算",
            reason="结构化分类不可用，保守规则识别到自定义统计维度",
        )

    effect_markers = ("活动收益", "活动效果", "漏斗", "lift", "完成率", "兑换率")
    if any(marker in normalized for marker in effect_markers):
        return OperatorIntentDecision(
            intent=OperatorIntent.KNOWLEDGE_QUERY,
            capability=OperatorCapability.CAMPAIGN_STANDARD_EFFECT,
            confidence=0.6,
            reason="结构化分类不可用，保守规则识别到标准活动效果查询",
        )

    history_markers = ("活动历史", "历史活动", "最近活动", "活动列表")
    if any(marker in normalized for marker in history_markers):
        return OperatorIntentDecision(
            intent=OperatorIntent.KNOWLEDGE_QUERY,
            capability=OperatorCapability.CAMPAIGN_HISTORY,
            confidence=0.6,
            reason="结构化分类不可用，保守规则识别到活动历史查询",
        )

    if "草案" in normalized or "生成活动" in normalized:
        return OperatorIntentDecision(
            intent=OperatorIntent.PLAN_REQUEST,
            capability=OperatorCapability.CAMPAIGN_DRAFT,
            confidence=0.55,
            reason="结构化分类不可用，保守规则识别到正式草案请求",
        )

    planning_markers = ("方案", "规划", "设计", "分析", "生成")
    if any(marker in normalized for marker in planning_markers):
        return OperatorIntentDecision(
            intent=OperatorIntent.PLAN_REQUEST,
            capability=OperatorCapability.CAMPAIGN_PLANNING,
            confidence=0.55,
            reason="结构化分类不可用，保守规则识别到规划表达",
        )

    return OperatorIntentDecision(
        intent=OperatorIntent.KNOWLEDGE_QUERY,
        capability=OperatorCapability.GENERAL_KNOWLEDGE,
        confidence=0.5,
        reason="结构化分类不可用，默认按只读知识咨询处理",
    )


def enforce_task_guard(
    message: str,
    decision: OperatorTaskSpec,
) -> OperatorTaskSpec:
    """对高风险误分类做保守覆盖，避免准入结果完全依赖模型自觉。"""

    normalized = "".join(message.lower().split())
    if (
        decision.capability == OperatorCapability.CUSTOM_ANALYTICS
        or not _looks_like_custom_analytics(normalized)
    ):
        return decision
    return OperatorTaskSpec(
        intent=OperatorIntent.PLAN_REQUEST,
        capability=OperatorCapability.CUSTOM_ANALYTICS,
        confidence=max(decision.confidence, 0.8),
        requested_action=decision.requested_action or "自定义运营指标计算",
        reason="确定性任务守卫识别到自定义统计维度",
    )


def _looks_like_custom_analytics(normalized: str) -> bool:
    if "如何计算" in normalized or "怎么计算" in normalized:
        return False
    analytics_markers = ("计算", "统计", "占比", "比例", "转化率")
    custom_dimensions = (
        "最近",
        "过去",
        "不少于",
        "大于",
        "小于",
        "用户中",
        "之后",
        "以后",
        "先",
        "再",
    )
    return any(marker in normalized for marker in analytics_markers) and any(
        dimension in normalized for dimension in custom_dimensions
    )
