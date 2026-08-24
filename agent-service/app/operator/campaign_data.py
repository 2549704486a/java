from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.models import CampaignPlanningSnapshot
from app.api_client import BusinessApiClient, BusinessApiError


class CampaignDataUnavailable(RuntimeError):
    """运营草案依赖的只读事实暂时不可用。"""

    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class CampaignDataProvider(Protocol):
    """隔离活动规划与具体数据库、报表或分析平台。"""

    def get_planning_snapshot(self, target_segment_key: str) -> CampaignPlanningSnapshot:
        ...


class StaticCampaignDataProvider:
    """仅用于测试和本地演示；生产环境应替换为真实只读数据适配器。"""

    def __init__(self, snapshots: Mapping[str, CampaignPlanningSnapshot]) -> None:
        self._snapshots = dict(snapshots)

    def get_planning_snapshot(self, target_segment_key: str) -> CampaignPlanningSnapshot:
        try:
            return self._snapshots[target_segment_key].model_copy(deep=True)
        except KeyError as exc:
            raise CampaignDataUnavailable(
                "CAMPAIGN_SEGMENT_NOT_FOUND",
                f"找不到客群 {target_segment_key!r} 的规划快照",
                False,
            ) from exc


class HttpCampaignDataProvider:
    """通过 Java 只读接口取得事实快照，不允许 Agent 直连业务数据库。"""

    def __init__(self, client: BusinessApiClient) -> None:
        self._client = client

    def get_planning_snapshot(self, target_segment_key: str) -> CampaignPlanningSnapshot:
        try:
            envelope = self._client.get_campaign_planning_snapshot(target_segment_key)
        except BusinessApiError as exc:
            raise CampaignDataUnavailable(
                exc.code,
                exc.message,
                exc.retryable,
            ) from exc
        if not envelope.success:
            raise CampaignDataUnavailable(
                envelope.code,
                envelope.message,
                envelope.retryable,
            )
        try:
            return CampaignPlanningSnapshot.model_validate(envelope.data)
        except (TypeError, ValueError) as exc:
            raise CampaignDataUnavailable(
                "INVALID_CAMPAIGN_SNAPSHOT",
                "运营规划快照格式异常",
                False,
            ) from exc
