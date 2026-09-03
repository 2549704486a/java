from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.observability.models import AgentRequestObservation


logger = logging.getLogger(__name__)


class AgentObservationSink(Protocol):
    def save(self, observation: AgentRequestObservation) -> None: ...

    def delete_before(self, cutoff: datetime) -> int: ...


class AgentObservationWriter:
    """通过有界队列异步落库，使观测故障与 Agent 主流程隔离。"""

    def __init__(
        self,
        sink: AgentObservationSink,
        *,
        queue_capacity: int,
        retention_days: int,
    ) -> None:
        if queue_capacity <= 0:
            raise ValueError("queue_capacity 必须大于 0")
        if retention_days <= 0:
            raise ValueError("retention_days 必须大于 0")
        self._sink = sink
        self._queue: asyncio.Queue[AgentRequestObservation | None] = asyncio.Queue(
            maxsize=queue_capacity
        )
        self._retention = timedelta(days=retention_days)
        self._next_cleanup_at: datetime | None = None
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._worker = asyncio.create_task(
            self._run(),
            name="agent-observation-writer",
        )

    def submit(self, observation: AgentRequestObservation) -> bool:
        if self._worker is None or self._worker.done():
            logger.warning(
                "agent_observation_dropped request_id=%s reason=writer_not_running",
                observation.request_id,
            )
            return False
        try:
            self._queue.put_nowait(observation)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "agent_observation_dropped request_id=%s reason=queue_full",
                observation.request_id,
            )
            return False

    async def close(self, *, timeout_seconds: float = 3.0) -> None:
        worker = self._worker
        if worker is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout_seconds)
            self._queue.put_nowait(None)
            await asyncio.wait_for(worker, timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(
                "agent_observation_writer_close_timeout pending=%s",
                self._queue.qsize(),
            )
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        finally:
            self._worker = None

    async def _run(self) -> None:
        await self._cleanup_if_due()
        while True:
            observation = await self._queue.get()
            try:
                if observation is None:
                    return
                try:
                    await asyncio.to_thread(self._sink.save, observation)
                except Exception as exc:
                    logger.warning(
                        "agent_observation_write_failed request_id=%s error_type=%s",
                        observation.request_id,
                        exc.__class__.__name__,
                    )
                await self._cleanup_if_due()
            finally:
                self._queue.task_done()

    async def _cleanup_if_due(self) -> None:
        now = datetime.now(timezone.utc)
        if self._next_cleanup_at is not None and now < self._next_cleanup_at:
            return
        try:
            removed = await asyncio.to_thread(
                self._sink.delete_before,
                now - self._retention,
            )
            logger.info("agent_observation_cleanup removed=%s", removed)
        except Exception as exc:
            logger.warning(
                "agent_observation_cleanup_failed error_type=%s",
                exc.__class__.__name__,
            )
        finally:
            self._next_cleanup_at = now + timedelta(days=1)
