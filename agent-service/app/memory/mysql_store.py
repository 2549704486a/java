from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from app.memory.store import (
    ForgetScope,
    GrowthMemoryStoreBackend,
    MemoryChangeResult,
    MemoryType,
    MemoryWriteResult,
    _clean_normalized_data,
    _clean_text,
    _same_memory,
    _scope_memory_types,
    build_memory_key,
    business_date,
)
from app.models import GrowthMemoryData, MemoryItem, RedemptionGoalData, UserPreferenceData


class MysqlGrowthMemoryStore(GrowthMemoryStoreBackend):
    """以 MySQL 作为长期记忆事实来源，每次操作使用独立短连接。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        table_name: str = "agent_long_term_memory",
        connect_timeout: int = 3,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]+", table_name):
            raise ValueError("长期记忆表名只能包含字母、数字和下划线")
        self._connection_options = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "charset": "utf8mb4",
            "connect_timeout": connect_timeout,
            "read_timeout": 5,
            "write_timeout": 5,
            "cursorclass": DictCursor,
            "autocommit": False,
        }
        self._table = table_name
        self._check_ready()

    def get(self, user_id: int) -> GrowthMemoryData:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT *
                    FROM `{self._table}`
                    WHERE user_id = %s AND status = 'ACTIVE'
                    ORDER BY updated_at DESC
                    """,
                    (user_id,),
                )
                items = [self._row_to_item(row) for row in cursor.fetchall()]
        return self._project(user_id, items)

    def remember(
        self,
        *,
        user_id: int,
        source_session: str,
        memory_type: MemoryType,
        raw_text: str,
        normalized_data: dict | None = None,
        source_message_id: str | None = None,
    ) -> MemoryWriteResult:
        cleaned_text = _clean_text(raw_text, limit=500)
        cleaned_data = _clean_normalized_data(normalized_data or {})
        memory_key = build_memory_key(memory_type, cleaned_text, cleaned_data)
        now = datetime.now(timezone.utc)

        with self._connection() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT *
                        FROM `{self._table}`
                        WHERE user_id = %s AND active_key = %s
                        FOR UPDATE
                        """,
                        (user_id, memory_key),
                    )
                    row = cursor.fetchone()
                    existing = self._row_to_item(row) if row else None
                    if existing is not None and _same_memory(
                        existing, cleaned_text, cleaned_data
                    ):
                        connection.rollback()
                        return MemoryWriteResult(
                            applied=False,
                            action="NOOP",
                            code="MEMORY_UNCHANGED",
                            message="这条长期记忆已经存在",
                            memory=existing,
                            current=self.get(user_id),
                        )

                    action = "ADD"
                    if existing is not None:
                        old_polarity = str(existing.normalized_data.get("polarity", ""))
                        new_polarity = str(cleaned_data.get("polarity", ""))
                        action = (
                            "SUPERSEDE"
                            if old_polarity
                            and new_polarity
                            and old_polarity != new_polarity
                            else "UPDATE"
                        )
                        cursor.execute(
                            f"""
                            UPDATE `{self._table}`
                            SET status = 'SUPERSEDED', active_key = NULL,
                                valid_to = %s, updated_at = %s
                            WHERE memory_id = %s
                            """,
                            (self._to_mysql_time(now), self._to_mysql_time(now), existing.memory_id),
                        )

                    item = MemoryItem(
                        memoryId=uuid.uuid4().hex,
                        userId=user_id,
                        memoryType=memory_type,
                        memoryKey=memory_key,
                        rawText=cleaned_text,
                        normalizedData=cleaned_data,
                        status="ACTIVE",
                        validFrom=now,
                        validTo=None,
                        sourceSession=source_session,
                        sourceMessageId=source_message_id,
                        createdAt=now,
                        updatedAt=now,
                    )
                    cursor.execute(
                        f"""
                        INSERT INTO `{self._table}` (
                            memory_id, user_id, memory_type, memory_key, active_key,
                            raw_text, normalized_data, status, valid_from, valid_to,
                            source_session, source_message_id, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, 'ACTIVE', %s, NULL,
                            %s, %s, %s, %s
                        )
                        """,
                        (
                            item.memory_id,
                            user_id,
                            memory_type,
                            memory_key,
                            memory_key,
                            cleaned_text,
                            json.dumps(cleaned_data, ensure_ascii=False),
                            self._to_mysql_time(now),
                            source_session,
                            source_message_id,
                            self._to_mysql_time(now),
                            self._to_mysql_time(now),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return MemoryWriteResult(
            applied=True,
            action=action,
            code={
                "ADD": "MEMORY_ADDED",
                "UPDATE": "MEMORY_UPDATED",
                "SUPERSEDE": "MEMORY_SUPERSEDED",
            }[action],
            message={
                "ADD": "已保存长期记忆",
                "UPDATE": "已更新长期记忆",
                "SUPERSEDE": "已用新的表达替代旧记忆",
            }[action],
            memory=item,
            current=self.get(user_id),
        )

    def save_goal(
        self,
        *,
        user_id: int,
        source_session: str,
        target_award_id: int,
        target_award_name: str,
        target_date: date,
    ) -> MemoryChangeResult:
        self.remember(
            user_id=user_id,
            source_session=source_session,
            memory_type="goal",
            raw_text=f"计划在 {target_date.isoformat()} 兑换 {target_award_name}",
            normalized_data={
                "subject": f"award:{target_award_id}",
                "target": target_award_name,
                "awardId": target_award_id,
                "targetDate": target_date.isoformat(),
            },
        )
        return self._change_result(
            True, "REDEMPTION_GOAL_SAVED", "已保存兑换目标", user_id
        )

    def replace_preferences(
        self,
        *,
        user_id: int,
        source_session: str,
        preferred_categories: list[str],
        disliked_categories: list[str],
        task_preferences: list[str],
    ) -> MemoryChangeResult:
        self.forget(user_id=user_id, scope="preferences")
        for value in preferred_categories:
            self.remember(
                user_id=user_id,
                source_session=source_session,
                memory_type="preference",
                raw_text=f"喜欢 {value}",
                normalized_data={"subject": value, "polarity": "LIKE"},
            )
        for value in disliked_categories:
            self.remember(
                user_id=user_id,
                source_session=source_session,
                memory_type="preference",
                raw_text=f"不喜欢 {value}",
                normalized_data={"subject": value, "polarity": "DISLIKE"},
            )
        for value in task_preferences:
            self.remember(
                user_id=user_id,
                source_session=source_session,
                memory_type="preference",
                raw_text=f"偏好 {value} 任务",
                normalized_data={
                    "subject": value,
                    "polarity": "LIKE",
                    "preferenceKind": "task",
                },
            )
        return self._change_result(
            True, "USER_PREFERENCES_SAVED", "已保存长期偏好", user_id
        )

    def forget(self, *, user_id: int, scope: ForgetScope) -> MemoryChangeResult:
        memory_types = sorted(_scope_memory_types(scope))
        placeholders = ", ".join(["%s"] * len(memory_types))
        with self._connection() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        DELETE FROM `{self._table}`
                        WHERE user_id = %s AND memory_type IN ({placeholders})
                        """,
                        (user_id, *memory_types),
                    )
                    removed = cursor.rowcount
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self._change_result(
            removed > 0,
            "GROWTH_MEMORY_FORGOTTEN" if removed else "NOTHING_TO_FORGET",
            "已遗忘指定的长期记忆" if removed else "对应范围内没有已保存的长期记忆",
            user_id,
        )

    def stats(self) -> dict[str, int]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT memory_type, COUNT(*) AS total
                    FROM `{self._table}`
                    WHERE status = 'ACTIVE'
                    GROUP BY memory_type
                    """
                )
                counts = {row["memory_type"]: int(row["total"]) for row in cursor.fetchall()}
        return {
            "goals": counts.get("goal", 0),
            "preferences": counts.get("preference", 0),
            "memories": sum(counts.values()),
        }

    def close(self) -> None:
        return None

    @contextmanager
    def _connection(self) -> Iterator[pymysql.Connection]:
        connection = pymysql.connect(**self._connection_options)
        try:
            yield connection
        finally:
            connection.close()

    def _check_ready(self) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM `{self._table}` LIMIT 1")

    def _project(self, user_id: int, items: list[MemoryItem]) -> GrowthMemoryData:
        goal = None
        goal_item = next(
            (
                item
                for item in items
                if item.memory_type == "goal"
                and item.normalized_data.get("awardId")
                and item.normalized_data.get("targetDate")
            ),
            None,
        )
        if goal_item is not None:
            target_date = date.fromisoformat(str(goal_item.normalized_data["targetDate"]))
            goal = RedemptionGoalData(
                userId=user_id,
                targetAwardId=int(goal_item.normalized_data["awardId"]),
                targetAwardName=str(goal_item.normalized_data.get("target", "目标奖品")),
                targetDate=target_date,
                status=(
                    "ACTIVE"
                    if target_date >= business_date(datetime.now(timezone.utc))
                    else "EXPIRED"
                ),
                createdAt=goal_item.created_at,
                updatedAt=goal_item.updated_at,
                sourceSession=goal_item.source_session,
            )

        preference_items = [item for item in items if item.memory_type == "preference"]
        preferences = None
        if preference_items:
            preferred = []
            disliked = []
            tasks = []
            for item in preference_items:
                subject = str(item.normalized_data.get("subject", item.raw_text))
                if item.normalized_data.get("preferenceKind") == "task":
                    tasks.append(subject)
                elif item.normalized_data.get("polarity") == "DISLIKE":
                    disliked.append(subject)
                else:
                    preferred.append(subject)
            latest = max(preference_items, key=lambda item: item.updated_at)
            preferences = UserPreferenceData(
                userId=user_id,
                preferredCategories=preferred,
                dislikedCategories=disliked,
                taskPreferences=tasks,
                createdAt=min(item.created_at for item in preference_items),
                updatedAt=latest.updated_at,
                sourceSession=latest.source_session,
            )
        return GrowthMemoryData(goal=goal, preferences=preferences, memories=items)

    def _change_result(
        self,
        applied: bool,
        code: str,
        message: str,
        user_id: int,
    ) -> MemoryChangeResult:
        return MemoryChangeResult(
            applied=applied,
            code=code,
            message=message,
            memory=self.get(user_id),
        )

    @staticmethod
    def _row_to_item(row: dict) -> MemoryItem:
        normalized_data = row["normalized_data"]
        if isinstance(normalized_data, str):
            normalized_data = json.loads(normalized_data)
        return MemoryItem(
            memoryId=row["memory_id"],
            userId=row["user_id"],
            memoryType=row["memory_type"],
            memoryKey=row["memory_key"],
            rawText=row["raw_text"],
            normalizedData=normalized_data or {},
            status=row["status"],
            validFrom=MysqlGrowthMemoryStore._from_mysql_time(row["valid_from"]),
            validTo=MysqlGrowthMemoryStore._from_mysql_time(row["valid_to"]),
            sourceSession=row["source_session"],
            sourceMessageId=row["source_message_id"],
            createdAt=MysqlGrowthMemoryStore._from_mysql_time(row["created_at"]),
            updatedAt=MysqlGrowthMemoryStore._from_mysql_time(row["updated_at"]),
        )

    @staticmethod
    def _to_mysql_time(value: datetime) -> datetime:
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _from_mysql_time(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)
