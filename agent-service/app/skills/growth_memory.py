from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from pydantic import ValidationError

from app.api_client import BusinessApiClient, BusinessApiError
from app.growth_memory_store import (
    ForgetScope,
    GrowthMemoryStoreBackend,
    MemoryChangeResult,
    MemoryType,
    MemoryWriteResult,
)
from app.memory_retrieval import select_memories
from app.models import AwardData, GrowthMemoryData, MemoryItem, ToolEnvelope


class GrowthMemorySkill:
    """保存用户明确表达的稳定目标和偏好，不保存实时业务事实或模型推测。"""

    def __init__(
        self,
        client: BusinessApiClient,
        store: GrowthMemoryStoreBackend,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self.client = client
        self.store = store
        self._today = today_provider

    def get(
        self,
        user_id: int,
        *,
        query: str | None = None,
        memory_types: list[MemoryType] | None = None,
        limit: int = 5,
        include_all: bool = False,
    ) -> ToolEnvelope:
        current = self.store.get(user_id)
        selected = select_memories(
            current.memories,
            query=query,
            memory_types=memory_types,
            limit=limit,
            include_all=include_all,
        )
        data = self._public_memory(
            current=current,
            selected=selected,
            query=query,
            memory_types=memory_types or [],
            limit=limit,
            include_all=include_all,
        )
        found = bool(selected) or (
            include_all and (current.goal is not None or current.preferences is not None)
        )
        return ToolEnvelope(
            success=True,
            code="GROWTH_MEMORY_FOUND" if found else "GROWTH_MEMORY_EMPTY",
            data=data,
            message="已按当前问题读取相关长期记忆" if found else "没有找到与当前问题相关的长期记忆",
        )

    def remember(
        self,
        *,
        user_id: int,
        session_id: str,
        memory_type: MemoryType,
        raw_text: str,
        subject: str | None = None,
        polarity: str | None = None,
        time_expression: str | None = None,
        target_year: int | None = None,
    ) -> ToolEnvelope:
        # 原文是事实来源；结构化字段只帮助检索和冲突识别，缺失时照样可以保存。
        normalized_data = {
            "subject": subject,
            "polarity": polarity,
            "timeExpression": time_expression,
            "targetYear": target_year,
        }
        result = self.store.remember(
            user_id=user_id,
            source_session=session_id,
            memory_type=memory_type,
            raw_text=raw_text,
            normalized_data=normalized_data,
        )
        return self._written(result)

    def save_goal(
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

        result = self.store.save_goal(
            user_id=user_id,
            source_session=session_id,
            target_award_id=award_id,
            target_award_name=award.name,
            target_date=target_date,
        )
        return self._changed(result)

    def save_preferences(
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
                message="同一类别不能同时设为喜欢和不喜欢，请先澄清偏好",
            )

        result = self.store.replace_preferences(
            user_id=user_id,
            source_session=session_id,
            preferred_categories=preferred,
            disliked_categories=disliked,
            task_preferences=tasks,
        )
        return self._changed(result)

    def forget(
        self,
        *,
        user_id: int,
        scope: ForgetScope,
    ) -> ToolEnvelope:
        # 只有用户明确说出遗忘意图时模型才可调用；工具按明确范围直接执行。
        result = self.store.forget(user_id=user_id, scope=scope)
        return self._changed(result)

    def _public_memory(
        self,
        *,
        current: GrowthMemoryData,
        selected: list[MemoryItem],
        query: str | None,
        memory_types: list[MemoryType],
        limit: int,
        include_all: bool,
    ) -> dict:
        data = current.model_dump(mode="json", by_alias=True)
        data["memories"] = [
            item.model_dump(mode="json", by_alias=True) for item in selected
        ]
        # 旧聚合视图可能包含未命中的其他偏好，只在用户明确查看全部记忆时返回。
        if not include_all:
            data["goal"] = None
            data["preferences"] = None
        data["retrieval"] = {
            "mode": "ALL" if include_all else ("FILTERED" if query or memory_types else "RECENT"),
            "queryApplied": bool(query and query.strip()),
            "memoryTypes": memory_types,
            "totalActive": len(current.memories),
            "returned": len(selected),
            "limit": None if include_all else limit,
        }
        # 来源会话用于服务端追踪，不交给模型，也不应出现在用户回答中。
        for value in data.values():
            if isinstance(value, dict):
                value.pop("sourceSession", None)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item.pop("sourceSession", None)
                        item.pop("sourceMessageId", None)
        return data

    def _written(self, result: MemoryWriteResult) -> ToolEnvelope:
        memory = result.memory.model_dump(mode="json", by_alias=True)
        memory.pop("sourceSession", None)
        memory.pop("sourceMessageId", None)
        return ToolEnvelope(
            success=True,
            code=result.code,
            data={"action": result.action, "memory": memory},
            message=result.message,
        )

    def _changed(self, result: MemoryChangeResult) -> ToolEnvelope:
        data = result.memory.model_dump(mode="json", by_alias=True)
        for value in data.values():
            if isinstance(value, dict):
                value.pop("sourceSession", None)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item.pop("sourceSession", None)
                        item.pop("sourceMessageId", None)
        return ToolEnvelope(
            # 幂等遗忘没有命中记录也属于成功处理，而不是系统失败。
            success=result.applied or result.code == "NOTHING_TO_FORGET",
            code=result.code,
            data=data,
            message=result.message,
        )

    @staticmethod
    def _normalize_values(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = re.sub(r"\s+", " ", value.strip())[:30]
            if normalized and normalized not in result:
                result.append(normalized)
        return result[:10]
