from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Sequence

import pymysql
from pymysql.cursors import DictCursor

from app.config import Settings
from app.observability.models import (
    AgentRequestDetail,
    AgentRequestObservation,
    AgentRequestPage,
    AgentRequestRecord,
    AgentRunStatus,
    AgentToolObservation,
    AgentType,
)


REQUEST_TABLE = "agent_request_observation"
TOOL_TABLE = "agent_tool_observation"


class MysqlAgentObservationStore:
    """Agent 运行摘要事实源；每次操作使用独立短连接。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        connect_timeout: int = 3,
        check_ready: bool = True,
    ) -> None:
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
        if check_ready:
            self.check_ready()

    @classmethod
    def from_settings(cls, settings: Settings) -> "MysqlAgentObservationStore":
        return cls(
            host=settings.agent_observability_mysql_host,
            port=settings.agent_observability_mysql_port,
            database=settings.agent_observability_mysql_database,
            user=settings.agent_observability_mysql_user,
            password=settings.agent_observability_mysql_password,
            connect_timeout=settings.agent_observability_mysql_connect_timeout,
        )

    def check_ready(self) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM `{REQUEST_TABLE}` LIMIT 1")
                cursor.execute(f"SELECT 1 FROM `{TOOL_TABLE}` LIMIT 1")

    def save(self, observation: AgentRequestObservation) -> None:
        with self._connection() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO `{REQUEST_TABLE}` (
                            request_id, agent_type, started_at, completed_at, status,
                            elapsed_ms, model_call_count, input_tokens, output_tokens,
                            tool_call_count, error_type
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            agent_type = VALUES(agent_type),
                            started_at = VALUES(started_at),
                            completed_at = VALUES(completed_at),
                            status = VALUES(status),
                            elapsed_ms = VALUES(elapsed_ms),
                            model_call_count = VALUES(model_call_count),
                            input_tokens = VALUES(input_tokens),
                            output_tokens = VALUES(output_tokens),
                            tool_call_count = VALUES(tool_call_count),
                            error_type = VALUES(error_type)
                        """,
                        (
                            observation.request_id,
                            observation.agent_type,
                            self._to_mysql_time(observation.started_at),
                            self._to_mysql_time(observation.completed_at),
                            observation.status,
                            observation.elapsed_ms,
                            observation.model_call_count,
                            observation.input_tokens,
                            observation.output_tokens,
                            observation.tool_call_count,
                            observation.error_type,
                        ),
                    )
                    # 重放同一 request_id 时先替换旧轨迹，避免残留多余 sequence。
                    cursor.execute(
                        f"DELETE FROM `{TOOL_TABLE}` WHERE request_id = %s",
                        (observation.request_id,),
                    )
                    if observation.tool_calls:
                        cursor.executemany(
                            f"""
                            INSERT INTO `{TOOL_TABLE}` (
                                request_id, sequence, tool_name, transport, completed,
                                business_success, result_code, elapsed_ms, error_type
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            [
                                (
                                    item.request_id,
                                    item.sequence,
                                    item.tool_name,
                                    item.transport,
                                    item.completed,
                                    item.business_success,
                                    item.result_code,
                                    item.elapsed_ms,
                                    item.error_type,
                                )
                                for item in observation.tool_calls
                            ],
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def delete_before(self, cutoff: datetime) -> int:
        with self._connection() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"DELETE FROM `{REQUEST_TABLE}` WHERE started_at < %s",
                        (self._to_mysql_time(cutoff),),
                    )
                    removed = cursor.rowcount
                connection.commit()
                return int(removed)
            except Exception:
                connection.rollback()
                raise

    def scan_requests(
        self,
        started_at: datetime,
        ended_at: datetime,
    ) -> list[AgentRequestRecord]:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT request_id, agent_type, started_at, completed_at, status,
                           elapsed_ms, model_call_count, input_tokens, output_tokens,
                           tool_call_count, error_type
                    FROM `{REQUEST_TABLE}`
                    WHERE started_at >= %s AND started_at <= %s
                    ORDER BY started_at ASC, request_id ASC
                    """,
                    (
                        self._to_mysql_time(started_at),
                        self._to_mysql_time(ended_at),
                    ),
                )
                return [self._request_record(row) for row in cursor.fetchall()]

    def scan_tools(self, request_ids: Sequence[str]) -> list[AgentToolObservation]:
        if not request_ids:
            return []
        records: list[AgentToolObservation] = []
        with self._connection() as connection:
            with connection.cursor() as cursor:
                for offset in range(0, len(request_ids), 500):
                    batch = request_ids[offset : offset + 500]
                    placeholders = ", ".join(["%s"] * len(batch))
                    cursor.execute(
                        f"""
                        SELECT request_id, sequence, tool_name, transport, completed,
                               business_success, result_code, elapsed_ms, error_type
                        FROM `{TOOL_TABLE}`
                        WHERE request_id IN ({placeholders})
                        ORDER BY request_id ASC, sequence ASC
                        """,
                        tuple(batch),
                    )
                    records.extend(self._tool_record(row) for row in cursor.fetchall())
        return records

    def list_requests(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        page: int,
        page_size: int,
        agent_type: AgentType | None = None,
        status: AgentRunStatus | None = None,
    ) -> AgentRequestPage:
        clauses = ["started_at >= %s", "started_at <= %s"]
        values: list[object] = [
            self._to_mysql_time(started_at),
            self._to_mysql_time(ended_at),
        ]
        if agent_type is not None:
            clauses.append("agent_type = %s")
            values.append(agent_type)
        if status is not None:
            clauses.append("status = %s")
            values.append(status)
        where = " AND ".join(clauses)

        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) AS total FROM `{REQUEST_TABLE}` WHERE {where}",
                    tuple(values),
                )
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"""
                    SELECT request_id, agent_type, started_at, completed_at, status,
                           elapsed_ms, model_call_count, input_tokens, output_tokens,
                           tool_call_count, error_type
                    FROM `{REQUEST_TABLE}`
                    WHERE {where}
                    ORDER BY started_at DESC, request_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*values, page_size, (page - 1) * page_size),
                )
                items = tuple(self._request_record(row) for row in cursor.fetchall())
        return AgentRequestPage(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )

    def get_request(self, request_id: str) -> AgentRequestDetail | None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT request_id, agent_type, started_at, completed_at, status,
                           elapsed_ms, model_call_count, input_tokens, output_tokens,
                           tool_call_count, error_type
                    FROM `{REQUEST_TABLE}`
                    WHERE request_id = %s
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    f"""
                    SELECT request_id, sequence, tool_name, transport, completed,
                           business_success, result_code, elapsed_ms, error_type
                    FROM `{TOOL_TABLE}`
                    WHERE request_id = %s
                    ORDER BY sequence ASC
                    """,
                    (request_id,),
                )
                tools = tuple(self._tool_record(item) for item in cursor.fetchall())
        return AgentRequestDetail(request=self._request_record(row), tool_calls=tools)

    @contextmanager
    def _connection(self) -> Iterator[pymysql.Connection]:
        connection = pymysql.connect(**self._connection_options)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _request_record(row: dict) -> AgentRequestRecord:
        return AgentRequestRecord(
            request_id=row["request_id"],
            agent_type=row["agent_type"],
            started_at=MysqlAgentObservationStore._from_mysql_time(row["started_at"]),
            completed_at=MysqlAgentObservationStore._from_mysql_time(
                row["completed_at"]
            ),
            status=row["status"],
            elapsed_ms=int(row["elapsed_ms"]),
            model_call_count=int(row["model_call_count"]),
            input_tokens=(
                int(row["input_tokens"]) if row["input_tokens"] is not None else None
            ),
            output_tokens=(
                int(row["output_tokens"])
                if row["output_tokens"] is not None
                else None
            ),
            tool_call_count=int(row["tool_call_count"]),
            error_type=row["error_type"],
        )

    @staticmethod
    def _tool_record(row: dict) -> AgentToolObservation:
        return AgentToolObservation(
            request_id=row["request_id"],
            sequence=int(row["sequence"]),
            tool_name=row["tool_name"],
            transport=row["transport"],
            completed=bool(row["completed"]),
            business_success=(
                bool(row["business_success"])
                if row["business_success"] is not None
                else None
            ),
            result_code=row["result_code"],
            elapsed_ms=int(row["elapsed_ms"]),
            error_type=row["error_type"],
        )

    @staticmethod
    def _to_mysql_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("观测时间必须包含时区")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _from_mysql_time(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc)
