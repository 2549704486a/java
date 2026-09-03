from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence

from app.observability.models import (
    AgentObservationSummary,
    AgentRequestDetail,
    AgentRequestPage,
    AgentRequestRecord,
    AgentRunStatus,
    AgentToolObservation,
    AgentType,
    LatencyMetric,
    ModelUsageMetric,
    ObservationTrendPoint,
    ObservationWindow,
    RatioMetric,
    RequestMetric,
    ToolMetric,
)


WINDOW_DURATIONS: dict[ObservationWindow, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class AgentObservationReader(Protocol):
    def scan_requests(
        self, started_at: datetime, ended_at: datetime
    ) -> list[AgentRequestRecord]: ...

    def scan_tools(self, request_ids: Sequence[str]) -> list[AgentToolObservation]: ...

    def list_requests(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        page: int,
        page_size: int,
        agent_type: AgentType | None = None,
        status: AgentRunStatus | None = None,
    ) -> AgentRequestPage: ...

    def get_request(self, request_id: str) -> AgentRequestDetail | None: ...


class AgentObservabilityService:
    """集中定义看板指标口径，调用方不再重复计算。"""

    def __init__(self, store: AgentObservationReader) -> None:
        self._store = store

    def summarize(
        self,
        window: ObservationWindow,
        *,
        now: datetime | None = None,
    ) -> AgentObservationSummary:
        ended_at = _aware_utc(now or datetime.now(timezone.utc))
        started_at = ended_at - WINDOW_DURATIONS[window]
        requests = self._store.scan_requests(started_at, ended_at)
        tools = self._store.scan_tools([item.request_id for item in requests])

        by_type = {
            agent_type: _request_metric(
                [item for item in requests if item.agent_type == agent_type]
            )
            for agent_type in ("USER", "OPERATOR")
        }
        grouped_tools: dict[str, list[AgentToolObservation]] = defaultdict(list)
        for item in tools:
            grouped_tools[item.tool_name].append(item)

        return AgentObservationSummary(
            window=window,
            started_at=started_at,
            ended_at=ended_at,
            requests=_request_metric(requests),
            requests_by_agent_type=by_type,
            model_usage=_model_usage_metric(requests),
            tools=_tool_metric(tools),
            tools_by_name=tuple(
                _tool_metric(items, tool_name=name)
                for name, items in sorted(grouped_tools.items())
            ),
            trend=_trend(requests, window, started_at, ended_at),
        )

    def list_requests(
        self,
        *,
        window: ObservationWindow,
        page: int = 1,
        page_size: int = 20,
        agent_type: AgentType | None = None,
        status: AgentRunStatus | None = None,
        now: datetime | None = None,
    ) -> AgentRequestPage:
        if page < 1:
            raise ValueError("page 必须大于等于 1")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size 必须在 1 到 100 之间")
        ended_at = _aware_utc(now or datetime.now(timezone.utc))
        return self._store.list_requests(
            started_at=ended_at - WINDOW_DURATIONS[window],
            ended_at=ended_at,
            page=page,
            page_size=page_size,
            agent_type=agent_type,
            status=status,
        )

    def get_request(self, request_id: str) -> AgentRequestDetail | None:
        return self._store.get_request(request_id)


def _request_metric(items: Sequence[AgentRequestRecord]) -> RequestMetric:
    completed = sum(item.status == "COMPLETED" for item in items)
    failed = sum(item.status == "FAILED" for item in items)
    return RequestMetric(
        total=len(items),
        completed=completed,
        failed=failed,
        completion=_ratio(completed, len(items)),
        latency=_latency([item.elapsed_ms for item in items]),
    )


def _model_usage_metric(items: Sequence[AgentRequestRecord]) -> ModelUsageMetric:
    covered = [
        item
        for item in items
        if item.input_tokens is not None and item.output_tokens is not None
    ]
    return ModelUsageMetric(
        model_call_count=sum(item.model_call_count for item in items),
        covered_requests=len(covered),
        coverage=_ratio(len(covered), len(items)),
        input_tokens=(sum(item.input_tokens or 0 for item in covered) if covered else None),
        output_tokens=(
            sum(item.output_tokens or 0 for item in covered) if covered else None
        ),
    )


def _tool_metric(
    items: Sequence[AgentToolObservation],
    *,
    tool_name: str | None = None,
) -> ToolMetric:
    completed = [item for item in items if item.completed]
    business_known = [
        item for item in completed if item.business_success is not None
    ]
    business_successful = sum(item.business_success is True for item in business_known)
    return ToolMetric(
        tool_name=tool_name,
        total_calls=len(items),
        completed_calls=len(completed),
        business_result_known_calls=len(business_known),
        business_successful_calls=business_successful,
        execution_completion=_ratio(len(completed), len(items)),
        business_success=_ratio(business_successful, len(business_known)),
        latency=_latency([item.elapsed_ms for item in items]),
    )


def _ratio(numerator: int, denominator: int) -> RatioMetric:
    return RatioMetric(
        numerator=numerator,
        denominator=denominator,
        value=(round(numerator / denominator, 4) if denominator else None),
    )


def _latency(values: Sequence[int]) -> LatencyMetric:
    if not values:
        return LatencyMetric(average_ms=None, p95_ms=None)
    ordered = sorted(values)
    # 最近秩口径：向上取整 95% 位置，再转换为从 0 开始的下标。
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return LatencyMetric(
        average_ms=round(sum(ordered) / len(ordered), 2),
        p95_ms=ordered[p95_index],
    )


def _trend(
    requests: Sequence[AgentRequestRecord],
    window: ObservationWindow,
    started_at: datetime,
    ended_at: datetime,
) -> tuple[ObservationTrendPoint, ...]:
    bucket_count = 24 if window == "24h" else (7 if window == "7d" else 30)
    bucket_size = (ended_at - started_at) / bucket_count
    buckets: list[list[AgentRequestRecord]] = [[] for _ in range(bucket_count)]
    for item in requests:
        offset = int((item.started_at - started_at) / bucket_size)
        buckets[min(max(offset, 0), bucket_count - 1)].append(item)

    return tuple(
        ObservationTrendPoint(
            started_at=started_at + bucket_size * index,
            ended_at=started_at + bucket_size * (index + 1),
            total=len(items),
            completed=sum(item.status == "COMPLETED" for item in items),
            failed=sum(item.status == "FAILED" for item in items),
        )
        for index, items in enumerate(buckets)
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now 必须包含时区")
    return value.astimezone(timezone.utc)
