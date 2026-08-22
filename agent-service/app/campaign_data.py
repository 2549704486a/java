from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.models import CampaignPlanningSnapshot


class CampaignDataUnavailable(RuntimeError):
    """运营草案依赖的只读事实暂时不可用。"""


class CampaignDataProvider(Protocol):
    """隔离活动规划与具体数据库、报表或分析平台。"""

    def get_planning_snapshot(self, target_segment: str) -> CampaignPlanningSnapshot:
        ...


class StaticCampaignDataProvider:
    """仅用于测试和本地演示；生产环境应替换为真实只读数据适配器。"""

    def __init__(self, snapshots: Mapping[str, CampaignPlanningSnapshot]) -> None:
        self._snapshots = dict(snapshots)

    def get_planning_snapshot(self, target_segment: str) -> CampaignPlanningSnapshot:
        try:
            return self._snapshots[target_segment].model_copy(deep=True)
        except KeyError as exc:
            raise CampaignDataUnavailable(
                f"找不到用户群 {target_segment!r} 的规划快照"
            ) from exc
