from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AssetType(str, Enum):
    AWARD_CANDIDATE = "AWARD_CANDIDATE"
    CAMPAIGN_PATTERN = "CAMPAIGN_PATTERN"
    SEGMENT_RULE_TEMPLATE = "SEGMENT_RULE_TEMPLATE"


class RunKind(str, Enum):
    PILOT = "PILOT"
    OFFICIAL = "OFFICIAL"


class ExperimentArm(str, Enum):
    PROJECT_SINGLE = "PROJECT_SINGLE"
    PROJECT_MULTI = "PROJECT_MULTI"
    CODEX_DIRECT = "CODEX_DIRECT"
    CODEX_DELEGATED = "CODEX_DELEGATED"


class SourceDiscoveryMethod(str, Enum):
    AGENT_SEARCH = "AGENT_SEARCH"
    BRIEF_URL = "BRIEF_URL"


class SourceReadStatus(str, Enum):
    READABLE = "READABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    INVALID_CONTENT_TYPE = "INVALID_CONTENT_TYPE"
    NETWORK_ERROR = "NETWORK_ERROR"
    POLICY_REJECTED = "POLICY_REJECTED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    TIMEOUT = "TIMEOUT"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONFLICTING = "CONFLICTING"
    UNSUPPORTED = "UNSUPPORTED"


class RunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


class RetentionRecommendation(str, Enum):
    KEEP_MULTI_AGENT = "KEEP_MULTI_AGENT"
    KEEP_SINGLE_AGENT = "KEEP_SINGLE_AGENT"
    INCONCLUSIVE = "INCONCLUSIVE"


class StageStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ResearchTarget(StrictModel):
    asset_type: AssetType
    target_count: int = Field(ge=1, le=10)
    research_questions: list[str] = Field(min_length=1, max_length=8)


class ResearchBudget(StrictModel):
    max_search_queries: int = Field(ge=1, le=20)
    max_search_results_per_query: int = Field(ge=1, le=10)
    max_pages_to_read: int = Field(ge=1, le=30)
    max_parallel_tasks: int = Field(default=3, ge=1, le=3)
    max_revision_rounds: int = Field(default=1, ge=0, le=1)


class ResearchBrief(StrictModel):
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    run_kind: RunKind
    title: str = Field(min_length=2, max_length=120)
    objective: str = Field(min_length=10, max_length=1000)
    language: Literal["zh-CN", "en-US"]
    targets: list[ResearchTarget] = Field(min_length=1, max_length=3)
    source_requirements: list[str] = Field(min_length=1, max_length=10)
    forbidden_outputs: list[str] = Field(min_length=1, max_length=20)
    explicit_source_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    budget: ResearchBudget
    output_label: str = Field(min_length=2, max_length=80)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> "ResearchBrief":
        asset_types = [target.asset_type for target in self.targets]
        if len(asset_types) != len(set(asset_types)):
            raise ValueError("同一简报不能重复声明资产类型")
        return self

    @property
    def identity(self) -> str:
        return f"{self.brief_id}:{self.version}"


class ResearchTask(StrictModel):
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    focus_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    objective: str = Field(min_length=10, max_length=500)
    asset_types: list[AssetType] = Field(min_length=1, max_length=1)
    target_count: int = Field(ge=1, le=10)
    search_queries: list[str] = Field(min_length=1, max_length=4)
    source_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)
    excluded_focuses: list[str] = Field(default_factory=list, max_length=6)
    max_pages: int = Field(ge=1, le=10)


class ResearchPlan(StrictModel):
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    tasks: list[ResearchTask] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_distinct_tasks(self) -> "ResearchPlan":
        task_ids = [task.task_id for task in self.tasks]
        focus_keys = [task.focus_key for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("研究任务 ID 必须唯一")
        if len(focus_keys) != len(set(focus_keys)):
            raise ValueError("并行研究任务的关注方向不能重复")
        return self


class SourceEvidence(StrictModel):
    source_id: str = Field(pattern=r"^source-[a-z0-9-]{3,95}$")
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=200)
    published_at: datetime | None = None
    retrieved_at: AwareDatetime
    discovered_by: SourceDiscoveryMethod
    excerpt: str | None = Field(default=None, max_length=5000)
    excerpt_ids: list[str] = Field(default_factory=list, max_length=4)
    read_status: SourceReadStatus
    error_category: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_read_result(self) -> "SourceEvidence":
        if self.read_status == SourceReadStatus.READABLE:
            if not self.title or not self.publisher or not self.excerpt:
                raise ValueError("可读来源必须包含标题、发布者和证据摘录")
            if self.error_category is not None:
                raise ValueError("可读来源不能包含错误类别")
        elif self.excerpt is not None or self.excerpt_ids:
            raise ValueError("读取失败的来源不能携带事实证据摘录或片段 ID")
        if len(self.excerpt_ids) != len(set(self.excerpt_ids)):
            raise ValueError("来源证据片段 ID 不能重复")
        if any(
            not excerpt_id.startswith(f"{self.source_id}-excerpt-")
            for excerpt_id in self.excerpt_ids
        ):
            raise ValueError("证据片段 ID 必须属于当前来源")
        return self


class EvidenceClaim(StrictModel):
    text: str = Field(min_length=5, max_length=1000)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    support_status: SupportStatus
    review_note: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def validate_support_sources(self) -> "EvidenceClaim":
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("同一结论不能重复引用来源")
        if self.support_status in {
            SupportStatus.SUPPORTED,
            SupportStatus.PARTIALLY_SUPPORTED,
        } and not self.source_ids:
            raise ValueError("有证据支持的结论必须引用来源")
        if self.support_status == SupportStatus.CONFLICTING and len(self.source_ids) < 2:
            raise ValueError("冲突结论必须引用至少两个来源")
        return self


class CandidateAsset(StrictModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    asset_type: AssetType
    name: str = Field(min_length=2, max_length=200)
    summary: str = Field(min_length=10, max_length=1000)
    project_fit: str = Field(min_length=10, max_length=1200)
    data_origin: Literal["PUBLIC_RESEARCH"] = "PUBLIC_RESEARCH"
    claims: list[EvidenceClaim] = Field(min_length=1, max_length=20)


class CandidateBundle(StrictModel):
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    sources: list[SourceEvidence] = Field(default_factory=list, max_length=30)
    candidates: list[CandidateAsset] = Field(default_factory=list, max_length=30)


class SourceExcerptSelection(StrictModel):
    source_id: str = Field(pattern=r"^source-[a-z0-9-]{3,95}$")
    excerpt_id: str = Field(
        pattern=r"^source-[a-z0-9-]{3,95}-excerpt-[0-9]{3}$"
    )

    @model_validator(mode="after")
    def validate_excerpt_source(self) -> "SourceExcerptSelection":
        if not self.excerpt_id.startswith(f"{self.source_id}-excerpt-"):
            raise ValueError("证据片段 ID 必须属于所选来源")
        return self


class ResearchAgentOutput(StrictModel):
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    source_selections: list[SourceExcerptSelection] = Field(max_length=30)
    candidates: list[CandidateAsset] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_unique_source_selections(self) -> "ResearchAgentOutput":
        selection_keys = [
            (selection.source_id, selection.excerpt_id)
            for selection in self.source_selections
        ]
        if len(selection_keys) != len(set(selection_keys)):
            raise ValueError("同一证据片段只能选择一次")
        source_ids = [selection.source_id for selection in self.source_selections]
        if any(source_ids.count(source_id) > 4 for source_id in set(source_ids)):
            raise ValueError("同一来源最多选择四段短证据")
        referenced_source_ids = {
            source_id
            for candidate in self.candidates
            for claim in candidate.claims
            for source_id in claim.source_ids
        }
        selected_source_ids = set(source_ids)
        if not referenced_source_ids.issubset(selected_source_ids):
            missing = sorted(referenced_source_ids - selected_source_ids)
            raise ValueError(
                "所有结论引用都必须提供来源摘录；缺少摘录："
                + ", ".join(missing)
            )
        return self


class ClaimEvidenceReview(StrictModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")
    claim_index: int = Field(ge=0, le=19)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    support_status: SupportStatus
    review_note: str = Field(min_length=2, max_length=500)


class EvidenceReviewOutput(StrictModel):
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    reviews: list[ClaimEvidenceReview] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_unique_claim_reviews(self) -> "EvidenceReviewOutput":
        keys = [(item.candidate_id, item.claim_index) for item in self.reviews]
        if len(keys) != len(set(keys)):
            raise ValueError("同一候选结论只能审核一次")
        return self


class StageObservation(StrictModel):
    stage: str = Field(min_length=2, max_length=80)
    status: StageStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    model_call_count: int | None = Field(default=None, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0, le=1)
    output_candidate_ids: list[str] = Field(default_factory=list)
    error_category: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_stage_timing_and_usage(self) -> "StageObservation":
        if self.completed_at < self.started_at:
            raise ValueError("阶段结束时间不能早于开始时间")
        if (self.input_tokens is None) != (self.output_tokens is None):
            raise ValueError("输入和输出 Token 必须同时已知或同时未知")
        return self


class RunSummary(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    run_kind: RunKind
    arm: ExperimentArm
    status: RunStatus
    started_at: AwareDatetime
    completed_at: AwareDatetime
    stages: list[StageObservation] = Field(default_factory=list, max_length=20)
    failure_stage: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_run_timing(self) -> "RunSummary":
        if self.completed_at < self.started_at:
            raise ValueError("运行结束时间不能早于开始时间")
        if self.status == RunStatus.COMPLETED and self.failure_stage is not None:
            raise ValueError("完成的运行不能设置失败阶段")
        return self


class ApprovedCandidateSnapshot(StrictModel):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")
    candidate: CandidateAsset

    @model_validator(mode="after")
    def validate_candidate_id(self) -> "ApprovedCandidateSnapshot":
        if self.candidate_id != self.candidate.candidate_id:
            raise ValueError("批准记录的候选 ID 与快照不一致")
        return self


class ApprovalList(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")
    approver: str = Field(min_length=2, max_length=80)
    approved_at: AwareDatetime
    approved_candidates: list[ApprovedCandidateSnapshot] = Field(
        min_length=1,
        max_length=30,
    )

    @model_validator(mode="after")
    def validate_unique_candidates(self) -> "ApprovalList":
        candidate_ids = [item.candidate_id for item in self.approved_candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("批准清单不能重复包含同一候选")
        return self


class QualityScore(StrictModel):
    project_relevance: int = Field(ge=1, le=5)
    factual_support: int = Field(ge=1, le=5)
    adaptation_usability: int = Field(ge=1, le=5)
    conflict_handling: int = Field(ge=1, le=5)
    notes: str = Field(min_length=2, max_length=1000)

    @property
    def total(self) -> int:
        return (
            self.project_relevance
            + self.factual_support
            + self.adaptation_usability
            + self.conflict_handling
        )


class BlindScoreRecord(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    blind_label: str = Field(pattern=r"^[A-Z]$")
    scorer: str = Field(min_length=2, max_length=80)
    scored_at: AwareDatetime
    score: QualityScore


class BlindScoreSubmissionItem(StrictModel):
    blind_label: str = Field(pattern=r"^[A-Z]$")
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    project_relevance: int = Field(ge=1, le=5)
    factual_support: int = Field(ge=1, le=5)
    adaptation_usability: int = Field(ge=1, le=5)
    conflict_handling: int = Field(ge=1, le=5)
    notes: str = Field(min_length=2, max_length=1000)

    def to_quality_score(self) -> QualityScore:
        return QualityScore(
            project_relevance=self.project_relevance,
            factual_support=self.factual_support,
            adaptation_usability=self.adaptation_usability,
            conflict_handling=self.conflict_handling,
            notes=self.notes,
        )


class BlindScoreSubmission(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    policy_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    scorer: str = Field(min_length=2, max_length=80)
    records: list[BlindScoreSubmissionItem] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def validate_unique_material_scores(self) -> "BlindScoreSubmission":
        keys = [(item.blind_label, item.brief_id) for item in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("同一匿名材料只能提交一次评分")
        return self


class GateIssue(StrictModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,79}$")
    message: str = Field(min_length=2, max_length=500)
    candidate_id: str | None = None


class CandidateGateDecision(StrictModel):
    candidate_id: str
    approvable: bool
    issues: list[GateIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision(self) -> "CandidateGateDecision":
        if self.approvable == bool(self.issues):
            raise ValueError("可批准状态必须与门禁问题是否为空一致")
        return self


class GateReport(StrictModel):
    brief_id: str
    brief_version: str
    run_issues: list[GateIssue] = Field(default_factory=list)
    decisions: list[CandidateGateDecision] = Field(default_factory=list)
    approvable_candidate_ids: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)


class ExternalRunPayload(StrictModel):
    brief: ResearchBrief
    bundle: CandidateBundle
    summary: RunSummary


class FailedRunArtifact(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    arm: ExperimentArm
    status: Literal["FAILED"]
    failure_stage: str = Field(min_length=2, max_length=80)
    error_category: str = Field(min_length=2, max_length=80)
    message: str = Field(min_length=1, max_length=5000)
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_failure_timing(self) -> "FailedRunArtifact":
        if self.completed_at < self.started_at:
            raise ValueError("失败运行的结束时间不能早于开始时间")
        return self


class EvaluationRunRecord(StrictModel):
    brief: ResearchBrief
    bundle: CandidateBundle
    summary: RunSummary
    gate_report: GateReport

    @model_validator(mode="after")
    def validate_consistent_run(self) -> "EvaluationRunRecord":
        brief_identity = (self.brief.brief_id, self.brief.version)
        if self.brief.run_kind != RunKind.OFFICIAL:
            raise ValueError("正式对照不能导入 PILOT 简报")
        if (self.bundle.brief_id, self.bundle.brief_version) != brief_identity:
            raise ValueError("候选包与简报版本不一致")
        if (self.summary.brief_id, self.summary.brief_version) != brief_identity:
            raise ValueError("运行摘要与简报版本不一致")
        if (
            self.gate_report.brief_id,
            self.gate_report.brief_version,
        ) != brief_identity:
            raise ValueError("门禁报告与简报版本不一致")
        return self


class RunEvaluationMetrics(StrictModel):
    brief_id: str
    brief_version: str
    arm: ExperimentArm
    status: RunStatus
    schema_pass_rate: Literal[1.0] = 1.0
    target_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    target_completion: float = Field(ge=0, le=1)
    readable_source_count: int = Field(ge=0)
    traceable_claim_rate: float | None = Field(default=None, ge=0, le=1)
    evidence_supported_candidate_count: int = Field(ge=0)
    approvable_candidate_count: int = Field(ge=0)
    explicit_conflict_claim_rate: float | None = Field(default=None, ge=0, le=1)
    unsupported_claim_count: int = Field(ge=0)
    duplicate_candidate_count: int = Field(ge=0)
    run_issue_count: int = Field(ge=0)
    gate_failed_candidate_count: int = Field(ge=0)
    elapsed_seconds: float | None = Field(default=None, ge=0)
    model_call_count: int | None = Field(default=None, ge=0)
    tool_call_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retry_count: int = Field(ge=0)
    failure_stage: str | None = None


class BlindMappingEntry(StrictModel):
    blind_label: str = Field(pattern=r"^[A-Z]$")
    arm: ExperimentArm


class BlindMapping(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    policy_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    created_at: AwareDatetime
    entries: list[BlindMappingEntry] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_one_to_one_mapping(self) -> "BlindMapping":
        labels = [entry.blind_label for entry in self.entries]
        arms = [entry.arm for entry in self.entries]
        if len(set(labels)) != len(labels):
            raise ValueError("匿名标签不能重复")
        if set(arms) != set(ExperimentArm) or len(set(arms)) != len(ExperimentArm):
            raise ValueError("匿名映射必须完整覆盖四个执行臂")
        return self


class EvaluationRunReference(StrictModel):
    arm: ExperimentArm
    brief_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    brief_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,95}$")


class EvaluationInputManifest(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    policy_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    created_at: AwareDatetime
    runs: list[EvaluationRunReference] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def validate_unique_runs(self) -> "EvaluationInputManifest":
        keys = [(item.arm, item.brief_id) for item in self.runs]
        run_ids = [item.run_id for item in self.runs]
        if len(keys) != len(set(keys)):
            raise ValueError("同一执行臂和简报只能选择一个正式运行")
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("同一个运行不能重复进入正式评估")
        if any(keys.count((arm, brief_id)) > 1 for arm, brief_id in keys):
            raise ValueError("正式评估运行存在重复")
        return self


class BlindQualityMetrics(StrictModel):
    schema_pass_rate: Literal[1.0] = 1.0
    target_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    target_completion: float = Field(ge=0, le=1)
    readable_source_count: int = Field(ge=0)
    traceable_claim_rate: float | None = Field(default=None, ge=0, le=1)
    evidence_supported_candidate_count: int = Field(ge=0)
    approvable_candidate_count: int = Field(ge=0)
    explicit_conflict_claim_rate: float | None = Field(default=None, ge=0, le=1)
    unsupported_claim_count: int = Field(ge=0)
    duplicate_candidate_count: int = Field(ge=0)
    run_issue_count: int = Field(ge=0)
    gate_failed_candidate_count: int = Field(ge=0)


class BlindMaterial(StrictModel):
    blind_label: str = Field(pattern=r"^[A-Z]$")
    brief_id: str
    brief_version: str
    status: RunStatus
    bundle: CandidateBundle
    gate_report: GateReport
    quality_metrics: BlindQualityMetrics


class BlindPackage(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    policy_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    created_at: AwareDatetime
    materials: list[BlindMaterial] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_unique_materials(self) -> "BlindPackage":
        keys = [(item.blind_label, item.brief_id) for item in self.materials]
        if len(keys) != len(set(keys)):
            raise ValueError("同一匿名执行臂和简报只能有一份评分材料")
        return self


class LockedScoreSet(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    policy_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    locked_at: AwareDatetime
    records: list[BlindScoreRecord] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_unique_scores(self) -> "LockedScoreSet":
        keys = [(item.blind_label, item.brief_id) for item in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("同一匿名材料只能评分一次")
        if any(item.experiment_id != self.experiment_id for item in self.records):
            raise ValueError("评分记录与实验不一致")
        return self


class RevealedRunResult(StrictModel):
    arm: ExperimentArm
    brief_id: str
    metrics: RunEvaluationMetrics
    score: QualityScore


class ComparisonReport(StrictModel):
    experiment_id: str
    policy_version: str
    generated_at: AwareDatetime
    complete_four_arm_comparison: bool
    missing_results: list[str] = Field(default_factory=list)
    results: list[RevealedRunResult] = Field(default_factory=list, max_length=12)
    project_multi_brief_wins: int = Field(ge=0, le=3)
    project_multi_extra_approvable_candidates: int
    project_multi_added_gate_failures: int
    recommendation: RetentionRecommendation
    interpretation_notes: list[str] = Field(min_length=2, max_length=6)


class RetentionRule(StrictModel):
    require_no_added_gate_failures: Literal[True] = True
    required_brief_wins: int = Field(ge=1, le=3)
    required_extra_approvable_candidates: int = Field(ge=1, le=10)


class ExperimentPolicy(StrictModel):
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    frozen: Literal[True] = True
    frozen_at: AwareDatetime
    official_brief_files: list[str] = Field(min_length=3, max_length=3)
    arms: list[ExperimentArm] = Field(min_length=4, max_length=4)
    source_budget: ResearchBudget
    quality_dimensions: list[
        Literal[
            "project_relevance",
            "factual_support",
            "adaptation_usability",
            "conflict_handling",
        ]
    ] = Field(min_length=4, max_length=4)
    score_min: Literal[1] = 1
    score_max: Literal[5] = 5
    retention_rule: RetentionRule

    @model_validator(mode="after")
    def validate_complete_experiment(self) -> "ExperimentPolicy":
        required_arms = set(ExperimentArm)
        if set(self.arms) != required_arms or len(self.arms) != len(required_arms):
            raise ValueError("实验必须且只能包含四个预声明执行臂")
        if len(set(self.official_brief_files)) != 3:
            raise ValueError("三份正式简报文件不能重复")
        required_dimensions = {
            "project_relevance",
            "factual_support",
            "adaptation_usability",
            "conflict_handling",
        }
        if set(self.quality_dimensions) != required_dimensions:
            raise ValueError("人工评分必须包含四个预声明维度")
        return self


def load_research_brief(path: str | Path) -> ResearchBrief:
    brief_path = Path(path)
    with brief_path.open("r", encoding="utf-8") as file:
        return ResearchBrief.model_validate(json.load(file))


def load_experiment_policy(path: str | Path) -> ExperimentPolicy:
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8") as file:
        return ExperimentPolicy.model_validate(json.load(file))
