from __future__ import annotations

import re
from collections import Counter

from app.research.models import (
    CandidateAsset,
    CandidateBundle,
    CandidateGateDecision,
    GateIssue,
    GateReport,
    ResearchBrief,
    SourceReadStatus,
    SupportStatus,
)


_PROJECT_FACT_PATTERNS = (
    re.compile(
        r"(?:本项目|当前项目|本平台).{0,16}"
        r"(?:真实用户|客群人数|库存|兑换积分|采购成本|内部成本|活动预算|"
        r"转化率|收益).{0,12}(?:为|是|=|约|达到|共有)\s*[¥￥$]?\s*\d",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:award_id|required_points|unit_cost(?:_cents)?|inventory|"
        r"segment_size|conversion_rate|campaign_revenue)\s*[:=]\s*[\d\"']",
        re.IGNORECASE,
    ),
)


def evaluate_candidate_bundle(
    brief: ResearchBrief,
    bundle: CandidateBundle,
) -> GateReport:
    run_issues: list[GateIssue] = []
    if (bundle.brief_id, bundle.brief_version) != (brief.brief_id, brief.version):
        run_issues.append(
            GateIssue(
                code="BRIEF_MISMATCH",
                message="候选结果与研究简报版本不一致",
            )
        )

    source_counts = Counter(source.source_id for source in bundle.sources)
    duplicate_source_ids = {
        source_id for source_id, count in source_counts.items() if count > 1
    }
    if duplicate_source_ids:
        run_issues.append(
            GateIssue(
                code="DUPLICATE_SOURCE_ID",
                message="来源 ID 重复：" + ", ".join(sorted(duplicate_source_ids)),
            )
        )

    sources_by_id = {source.source_id: source for source in bundle.sources}
    readable_source_ids = {
        source.source_id
        for source in bundle.sources
        if source.read_status == SourceReadStatus.READABLE
    }
    if not readable_source_ids:
        run_issues.append(
            GateIssue(
                code="NO_READABLE_SOURCE",
                message="本次运行没有实际读取成功的公网来源",
            )
        )

    candidate_id_counts = Counter(
        candidate.candidate_id for candidate in bundle.candidates
    )
    duplicate_candidate_ids = {
        candidate_id
        for candidate_id, count in candidate_id_counts.items()
        if count > 1
    }
    if duplicate_candidate_ids:
        run_issues.append(
            GateIssue(
                code="DUPLICATE_CANDIDATE_ID",
                message="候选 ID 重复：" + ", ".join(sorted(duplicate_candidate_ids)),
            )
        )

    target_counts = {
        target.asset_type: target.target_count for target in brief.targets
    }
    seen_names: set[tuple[str, str]] = set()
    seen_by_type: Counter = Counter()
    decisions: list[CandidateGateDecision] = []
    approvable_ids: list[str] = []
    rejected_ids: list[str] = []

    for candidate in bundle.candidates:
        issues = _evaluate_candidate(
            brief=brief,
            candidate=candidate,
            sources_by_id=sources_by_id,
            readable_source_ids=readable_source_ids,
        )
        if candidate.candidate_id in duplicate_candidate_ids:
            issues.append(
                _candidate_issue(
                    candidate,
                    "DUPLICATE_CANDIDATE_ID",
                    "候选 ID 在同一运行中不唯一",
                )
            )

        normalized_name = "".join(candidate.name.casefold().split())
        name_key = (candidate.asset_type.value, normalized_name)
        if name_key in seen_names:
            issues.append(
                _candidate_issue(
                    candidate,
                    "DUPLICATE_CANDIDATE",
                    "同一资产类型中已经存在同名候选",
                )
            )
        seen_names.add(name_key)

        seen_by_type[candidate.asset_type] += 1
        allowed_count = target_counts.get(candidate.asset_type)
        if allowed_count is None:
            issues.append(
                _candidate_issue(
                    candidate,
                    "ASSET_TYPE_OUT_OF_SCOPE",
                    "候选资产类型不在当前简报范围内",
                )
            )
        elif seen_by_type[candidate.asset_type] > allowed_count:
            issues.append(
                _candidate_issue(
                    candidate,
                    "TARGET_COUNT_EXCEEDED",
                    "候选数量超过简报为该资产类型声明的上限",
                )
            )

        if run_issues and any(
            issue.code in {"BRIEF_MISMATCH", "DUPLICATE_SOURCE_ID"}
            for issue in run_issues
        ):
            issues.append(
                _candidate_issue(
                    candidate,
                    "RUN_LEVEL_GATE_FAILED",
                    "运行级契约或来源唯一性检查失败",
                )
            )

        decision = CandidateGateDecision(
            candidate_id=candidate.candidate_id,
            approvable=not issues,
            issues=issues,
        )
        decisions.append(decision)
        if decision.approvable:
            approvable_ids.append(candidate.candidate_id)
        else:
            rejected_ids.append(candidate.candidate_id)

    return GateReport(
        brief_id=brief.brief_id,
        brief_version=brief.version,
        run_issues=run_issues,
        decisions=decisions,
        approvable_candidate_ids=approvable_ids,
        rejected_candidate_ids=rejected_ids,
    )


def _evaluate_candidate(
    *,
    brief: ResearchBrief,
    candidate: CandidateAsset,
    sources_by_id: dict,
    readable_source_ids: set[str],
) -> list[GateIssue]:
    issues: list[GateIssue] = []
    if (candidate.brief_id, candidate.brief_version) != (
        brief.brief_id,
        brief.version,
    ):
        issues.append(
            _candidate_issue(
                candidate,
                "CANDIDATE_BRIEF_MISMATCH",
                "候选引用的简报版本不一致",
            )
        )

    referenced_source_ids: set[str] = set()
    for claim in candidate.claims:
        referenced_source_ids.update(claim.source_ids)
        if claim.support_status != SupportStatus.SUPPORTED:
            issues.append(
                _candidate_issue(
                    candidate,
                    "CLAIM_NOT_FULLY_SUPPORTED",
                    f"结论状态为 {claim.support_status.value}，不能进入可批准集合",
                )
            )
    unknown_source_ids = referenced_source_ids - sources_by_id.keys()
    if unknown_source_ids:
        issues.append(
            _candidate_issue(
                candidate,
                "UNKNOWN_SOURCE_REFERENCE",
                "引用了不存在的来源：" + ", ".join(sorted(unknown_source_ids)),
            )
        )
    unreadable_source_ids = referenced_source_ids - readable_source_ids
    if unreadable_source_ids:
        issues.append(
            _candidate_issue(
                candidate,
                "SOURCE_NOT_READABLE",
                "引用了未成功读取的来源："
                + ", ".join(sorted(unreadable_source_ids)),
            )
        )

    candidate_text = "\n".join(
        [
            candidate.name,
            candidate.summary,
            candidate.project_fit,
            *(claim.text for claim in candidate.claims),
        ]
    )
    if any(pattern.search(candidate_text) for pattern in _PROJECT_FACT_PATTERNS):
        issues.append(
            _candidate_issue(
                candidate,
                "FORBIDDEN_PROJECT_FACT",
                "候选包含由公网资料生成的项目内部具体业务事实",
            )
        )
    return _deduplicate_issues(issues)


def _candidate_issue(
    candidate: CandidateAsset,
    code: str,
    message: str,
) -> GateIssue:
    return GateIssue(
        code=code,
        message=message,
        candidate_id=candidate.candidate_id,
    )


def _deduplicate_issues(issues: list[GateIssue]) -> list[GateIssue]:
    unique: list[GateIssue] = []
    seen: set[tuple[str, str | None]] = set()
    for issue in issues:
        key = (issue.code, issue.candidate_id)
        if key not in seen:
            unique.append(issue)
            seen.add(key)
    return unique
