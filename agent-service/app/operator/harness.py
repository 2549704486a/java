from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.operator.intent import OperatorCapability, OperatorTaskSpec
from app.trace import ToolExecutionTrace, ToolResultEvidence


class ParameterSource(str, Enum):
    USER_INPUT = "USER_INPUT"
    TRUSTED_CONTEXT = "TRUSTED_CONTEXT"
    SYSTEM_LOOKUP = "SYSTEM_LOOKUP"
    TOOL_RESULT = "TOOL_RESULT"


class CapabilityContract(BaseModel):
    """声明一个能力能做什么；这里不承载具体业务实现。"""

    model_config = ConfigDict(frozen=True)

    capability: OperatorCapability
    supported: bool = True
    allowed_tools: frozenset[str] = Field(default_factory=frozenset)
    required_evidence_tools: frozenset[str] = Field(default_factory=frozenset)
    parameter_sources: dict[str, ParameterSource] = Field(default_factory=dict)
    blocked_message: str | None = None


class HarnessPreflight(BaseModel):
    allowed: bool
    code: str
    capability: OperatorCapability
    allowed_tools: frozenset[str]
    parameter_sources: dict[str, ParameterSource]
    user_message: str | None = None


class EvidenceValidation(BaseModel):
    passed: bool
    code: str
    capability: OperatorCapability
    required_tools: frozenset[str]
    successful_tools: frozenset[str]
    missing_tools: frozenset[str]
    provenance_errors: tuple[str, ...] = ()
    user_message: str | None = None


CUSTOM_ANALYTICS_BLOCKED_MESSAGE = (
    "当前还不能可靠计算这个自定义指标。现有能力只能读取活动级标准漏斗，"
    "不能证明同一批用户同时满足指定客群、时间窗以及事件先后关系，因此我不会"
    "把几个独立聚合数直接拼成比例。要支持该指标，需要新增按用户事件明细执行"
    "过滤、交集和顺序判断的确定性统计能力。"
)

BUSINESS_ACTION_BLOCKED_MESSAGE = (
    "当前运营 Agent 不直接执行发布、审批、修改规则或用户触达等写操作。"
    "请先生成或查看方案，再到运营工作台完成受控操作。"
)

EVIDENCE_MISSING_MESSAGE = (
    "本次没有取得回答所需的完整实时证据，因此暂时不能给出活动结论。"
    "请稍后重试；系统不会用缺失的数据自行估算。"
)


CAPABILITY_CONTRACTS: dict[OperatorCapability, CapabilityContract] = {
    OperatorCapability.GENERAL_KNOWLEDGE: CapabilityContract(
        capability=OperatorCapability.GENERAL_KNOWLEDGE,
        allowed_tools=frozenset({"search_operator_knowledge"}),
    ),
    OperatorCapability.CAMPAIGN_PLANNING: CapabilityContract(
        capability=OperatorCapability.CAMPAIGN_PLANNING,
        allowed_tools=frozenset(
            {
                "get_campaign_planning_snapshot",
                "list_campaign_activities",
                "get_campaign_funnel",
                "search_operator_knowledge",
            }
        ),
        parameter_sources={
            "target_segment_key": ParameterSource.USER_INPUT,
            "operator_id": ParameterSource.TRUSTED_CONTEXT,
        },
    ),
    OperatorCapability.CAMPAIGN_DRAFT: CapabilityContract(
        capability=OperatorCapability.CAMPAIGN_DRAFT,
        allowed_tools=frozenset(
            {
                "get_campaign_planning_snapshot",
                "list_campaign_activities",
                "get_campaign_funnel",
                "search_operator_knowledge",
                "draft_campaign_plan",
            }
        ),
        parameter_sources={
            "objective": ParameterSource.USER_INPUT,
            "target_segment_key": ParameterSource.USER_INPUT,
            "budget_amount_cents": ParameterSource.USER_INPUT,
            "points_issuance_cap": ParameterSource.USER_INPUT,
            "start_at": ParameterSource.USER_INPUT,
            "end_at": ParameterSource.USER_INPUT,
            "operator_id": ParameterSource.TRUSTED_CONTEXT,
        },
    ),
    OperatorCapability.CAMPAIGN_HISTORY: CapabilityContract(
        capability=OperatorCapability.CAMPAIGN_HISTORY,
        allowed_tools=frozenset({"list_campaign_activities"}),
        required_evidence_tools=frozenset({"list_campaign_activities"}),
        parameter_sources={"operator_id": ParameterSource.TRUSTED_CONTEXT},
    ),
    OperatorCapability.CAMPAIGN_STANDARD_EFFECT: CapabilityContract(
        capability=OperatorCapability.CAMPAIGN_STANDARD_EFFECT,
        allowed_tools=frozenset(
            {"list_campaign_activities", "get_campaign_funnel"}
        ),
        required_evidence_tools=frozenset(
            {"list_campaign_activities", "get_campaign_funnel"}
        ),
        parameter_sources={
            "operator_id": ParameterSource.TRUSTED_CONTEXT,
            "activity_id": ParameterSource.SYSTEM_LOOKUP,
            "funnel_metrics": ParameterSource.TOOL_RESULT,
        },
    ),
    OperatorCapability.CUSTOM_ANALYTICS: CapabilityContract(
        capability=OperatorCapability.CUSTOM_ANALYTICS,
        supported=False,
        blocked_message=CUSTOM_ANALYTICS_BLOCKED_MESSAGE,
    ),
    OperatorCapability.BUSINESS_ACTION: CapabilityContract(
        capability=OperatorCapability.BUSINESS_ACTION,
        supported=False,
        blocked_message=BUSINESS_ACTION_BLOCKED_MESSAGE,
    ),
}


class OperatorHarness:
    """在模型执行前后实施能力准入和最低证据约束。"""

    def contract_for(self, capability: OperatorCapability) -> CapabilityContract:
        return CAPABILITY_CONTRACTS[capability]

    def preflight(self, task: OperatorTaskSpec) -> HarnessPreflight:
        contract = self.contract_for(task.capability)
        return HarnessPreflight(
            allowed=contract.supported,
            code="HARNESS_ALLOWED" if contract.supported else "CAPABILITY_UNSUPPORTED",
            capability=task.capability,
            allowed_tools=contract.allowed_tools,
            parameter_sources=contract.parameter_sources,
            user_message=None if contract.supported else contract.blocked_message,
        )

    def validate_evidence(
        self,
        task: OperatorTaskSpec,
        traces: list[ToolExecutionTrace],
        results: list[ToolResultEvidence] | None = None,
    ) -> EvidenceValidation:
        contract = self.contract_for(task.capability)
        successful_tools = frozenset(
            event.tool_name
            for event in traces
            if event.completed and event.business_success is True
        )
        missing_tools = contract.required_evidence_tools - successful_tools
        provenance_errors = self._validate_parameter_provenance(
            task,
            traces,
            results or [],
        )
        passed = not missing_tools and not provenance_errors
        return EvidenceValidation(
            passed=passed,
            code="EVIDENCE_SUFFICIENT" if passed else "EVIDENCE_INSUFFICIENT",
            capability=task.capability,
            required_tools=contract.required_evidence_tools,
            successful_tools=successful_tools,
            missing_tools=missing_tools,
            provenance_errors=provenance_errors,
            user_message=None if passed else EVIDENCE_MISSING_MESSAGE,
        )

    def _validate_parameter_provenance(
        self,
        task: OperatorTaskSpec,
        traces: list[ToolExecutionTrace],
        results: list[ToolResultEvidence],
    ) -> tuple[str, ...]:
        if task.capability != OperatorCapability.CAMPAIGN_STANDARD_EFFECT:
            return ()

        listed_activity_ids: set[int] = set()
        for evidence in results:
            if evidence.tool_name != "list_campaign_activities":
                continue
            payload = _as_dict(evidence.result)
            data = payload.get("data")
            if payload.get("success") is True and isinstance(data, list):
                listed_activity_ids.update(
                    activity_id
                    for item in data
                    if isinstance(item, dict)
                    and isinstance((activity_id := item.get("id")), int)
                )

        funnel_activity_ids = {
            activity_id
            for event in traces
            if event.tool_name == "get_campaign_funnel"
            and event.completed
            and event.business_success is True
            and isinstance((activity_id := event.arguments.get("activity_id")), int)
        }
        unresolved_ids = funnel_activity_ids - listed_activity_ids
        if unresolved_ids:
            return (
                "activity_id_not_resolved_by_list_campaign_activities:"
                + ",".join(str(item) for item in sorted(unresolved_ids)),
            )
        return ()


def _as_dict(result: object) -> dict:
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        result = model_dump(mode="json")
    return result if isinstance(result, dict) else {}
