from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Literal

from pydantic import ValidationError

from app.api_client import BusinessApiClient, BusinessApiError
from app.growth_memory_store import (
    GrowthMemoryStoreBackend,
    MemoryChangeResult,
    MemoryChangeType,
)
from app.models import AwardData, ToolEnvelope


MemoryAction = Literal["CONFIRM", "CANCEL"]
ForgetScope = Literal["goal", "preferences", "all"]

_CONFIRM_PHRASES = {
    "确认保存",
    "确认记住",
    "确认修改",
    "确认遗忘",
    "确认删除",
    "就按这个保存",
}
_CANCEL_PHRASES = {
    "取消保存",
    "不保存了",
    "取消记忆修改",
    "取消遗忘",
}


def explicit_memory_action(message: str) -> MemoryAction | None:
    """记忆写入使用专用口令，避免与兑换确认或普通肯定句混淆。"""
    normalized = re.sub(r"[\s，。！？!?、]+", "", message).casefold()
    if normalized in _CONFIRM_PHRASES:
        return "CONFIRM"
    if normalized in _CANCEL_PHRASES:
        return "CANCEL"
    return None


class GrowthMemorySkill:
    """管理用户确认过的兑换目标与稳定偏好，不保存实时业务事实。"""

    def __init__(
        self,
        client: BusinessApiClient,
        store: GrowthMemoryStoreBackend,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self.client = client
        self.store = store
        self._today = today_provider

    def get(self, user_id: int) -> ToolEnvelope:
        data = self.store.get(user_id).model_dump(mode="json", by_alias=True)
        # 来源会话用于服务端审计，不交给模型，也不应出现在用户回答中。
        for value in data.values():
            if isinstance(value, dict):
                value.pop("sourceSession", None)
        return ToolEnvelope(
            success=True,
            code="GROWTH_MEMORY_FOUND" if any(data.values()) else "GROWTH_MEMORY_EMPTY",
            data=data,
            message="已读取用户确认过的长期目标与偏好" if any(data.values()) else "当前还没有已确认的长期目标或偏好",
        )

    def prepare_goal(
        self,
        *,
        user_id: int,
        session_id: str,
        award_id: int,
        target_date: date,
    ) -> ToolEnvelope:
        if target_date < self._today():
            return ToolEnvelope(
                success=False,
                code="GOAL_DATE_IN_PAST",
                data=None,
                message="目标日期已经过去，请选择今天或之后的日期",
            )
        try:
            award_envelope = self.client.get_award_detail(award_id)
            if not award_envelope.success:
                return award_envelope
            award = AwardData.model_validate(award_envelope.data)
        except BusinessApiError as exc:
            return exc.as_envelope()
        except (TypeError, ValidationError, ValueError):
            return ToolEnvelope(
                success=False,
                code="INVALID_BUSINESS_RESPONSE",
                data=None,
                message="奖品数据格式异常，当前无法保存兑换目标",
            )

        if award.end_time is not None and target_date > award.end_time.date():
            return ToolEnvelope(
                success=False,
                code="GOAL_AFTER_AWARD_END",
                data=None,
                message=f"目标日期晚于{award.name}的活动结束日期，请调整目标日期",
            )

        summary = f"将{award.name}（奖品 {award_id}）设为兑换目标，计划在 {target_date.isoformat()} 前完成"
        pending = self.store.prepare(
            user_id=user_id,
            session_id=session_id,
            change_type=MemoryChangeType.UPSERT_GOAL,
            payload={
                "target_award_id": award_id,
                "target_award_name": award.name,
                "target_date": target_date.isoformat(),
            },
            summary=summary,
        )
        return self._prepared(pending.change_type, pending.summary, pending.expires_at)

    def prepare_preferences(
        self,
        *,
        user_id: int,
        session_id: str,
        preferred_categories: list[str],
        disliked_categories: list[str],
        task_preferences: list[str],
    ) -> ToolEnvelope:
        preferred = self._normalize_values(preferred_categories)
        disliked = self._normalize_values(disliked_categories)
        tasks = self._normalize_values(task_preferences)
        if not preferred and not disliked and not tasks:
            return ToolEnvelope(
                success=False,
                code="EMPTY_PREFERENCES",
                data=None,
                message="没有可保存的稳定偏好；如需清除已有偏好，请使用遗忘功能",
            )
        conflicts = sorted(set(preferred) & set(disliked))
        if conflicts:
            return ToolEnvelope(
                success=False,
                code="CONFLICTING_PREFERENCES",
                data={"conflicts": conflicts},
                message="同一类别不能同时设为喜欢和不喜欢，请先确认偏好",
            )

        parts = []
        if preferred:
            parts.append(f"偏好奖品：{'、'.join(preferred)}")
        if disliked:
            parts.append(f"不喜欢奖品：{'、'.join(disliked)}")
        if tasks:
            parts.append(f"偏好任务：{'、'.join(tasks)}")
        pending = self.store.prepare(
            user_id=user_id,
            session_id=session_id,
            change_type=MemoryChangeType.REPLACE_PREFERENCES,
            payload={
                "preferred_categories": preferred,
                "disliked_categories": disliked,
                "task_preferences": tasks,
            },
            summary="；".join(parts),
        )
        return self._prepared(pending.change_type, pending.summary, pending.expires_at)

    def prepare_forget(
        self,
        *,
        user_id: int,
        session_id: str,
        scope: ForgetScope,
    ) -> ToolEnvelope:
        memory = self.store.get(user_id)
        change_type = {
            "goal": MemoryChangeType.FORGET_GOAL,
            "preferences": MemoryChangeType.FORGET_PREFERENCES,
            "all": MemoryChangeType.FORGET_ALL,
        }[scope]
        has_target = (
            memory.goal is not None
            if scope == "goal"
            else memory.preferences is not None
            if scope == "preferences"
            else memory.goal is not None or memory.preferences is not None
        )
        if not has_target:
            return ToolEnvelope(
                success=True,
                code="NOTHING_TO_FORGET",
                data=None,
                message="对应范围内没有已保存的长期记忆",
            )
        summary = {
            "goal": "删除已保存的兑换目标",
            "preferences": "删除已保存的奖品与任务偏好",
            "all": "删除全部兑换目标和偏好",
        }[scope]
        pending = self.store.prepare(
            user_id=user_id,
            session_id=session_id,
            change_type=change_type,
            payload={},
            summary=summary,
        )
        return self._prepared(pending.change_type, pending.summary, pending.expires_at)

    def confirm(self, *, user_id: int, session_id: str) -> MemoryChangeResult:
        return self.store.confirm(user_id=user_id, session_id=session_id)

    def cancel(self, *, user_id: int, session_id: str) -> ToolEnvelope:
        cancelled = self.store.cancel_pending(user_id=user_id, session_id=session_id)
        return ToolEnvelope(
            success=True,
            code="MEMORY_CHANGE_CANCELLED" if cancelled else "NO_PENDING_MEMORY_CHANGE",
            data={"cancelledCount": cancelled},
            message="已取消待确认的记忆变更" if cancelled else "当前没有待确认的记忆变更",
        )

    @staticmethod
    def _prepared(change_type: MemoryChangeType, summary: str, expires_at) -> ToolEnvelope:
        return ToolEnvelope(
            success=True,
            code="MEMORY_CONFIRMATION_REQUIRED",
            data={
                "status": "AWAITING_MEMORY_CONFIRMATION",
                "changeType": change_type.value,
                "summary": summary,
                "expiresAt": expires_at,
            },
            message="请核对将保存或删除的内容；确认无误后回复“确认保存”或“确认遗忘”",
        )

    @staticmethod
    def _normalize_values(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = re.sub(r"\s+", " ", value.strip())[:30]
            if normalized and normalized not in result:
                result.append(normalized)
        return result[:10]
