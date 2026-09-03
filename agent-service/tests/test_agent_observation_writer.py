from __future__ import annotations

import asyncio
import threading
import unittest
from datetime import datetime, timezone

from app.observability.models import AgentRequestObservation
from app.observability.writer import AgentObservationWriter


def observation(request_id: str) -> AgentRequestObservation:
    now = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
    return AgentRequestObservation(
        request_id=request_id,
        agent_type="USER",
        started_at=now,
        completed_at=now,
        status="COMPLETED",
        elapsed_ms=0,
        model_call_count=0,
        input_tokens=0,
        output_tokens=0,
    )


class RecordingSink:
    def __init__(self, *, fail_save: bool = False) -> None:
        self.fail_save = fail_save
        self.saved = []
        self.cleanup_cutoffs = []

    def save(self, item):
        if self.fail_save:
            raise RuntimeError("database unavailable")
        self.saved.append(item)

    def delete_before(self, cutoff):
        self.cleanup_cutoffs.append(cutoff)
        return 0


class BlockingCleanupSink(RecordingSink):
    def __init__(self) -> None:
        super().__init__()
        self.cleanup_started = threading.Event()
        self.cleanup_release = threading.Event()

    def delete_before(self, cutoff):
        self.cleanup_started.set()
        self.cleanup_release.wait(timeout=2)
        return super().delete_before(cutoff)


class AgentObservationWriterTest(unittest.IsolatedAsyncioTestCase):
    async def test_persists_submitted_snapshot_and_runs_cleanup(self):
        sink = RecordingSink()
        writer = AgentObservationWriter(
            sink,
            queue_capacity=2,
            retention_days=30,
        )
        await writer.start()

        accepted = writer.submit(observation("request-1"))
        await writer.close()

        self.assertTrue(accepted)
        self.assertEqual(["request-1"], [item.request_id for item in sink.saved])
        self.assertEqual(1, len(sink.cleanup_cutoffs))

    async def test_storage_failure_does_not_escape_close(self):
        sink = RecordingSink(fail_save=True)
        writer = AgentObservationWriter(
            sink,
            queue_capacity=2,
            retention_days=30,
        )
        await writer.start()

        self.assertTrue(writer.submit(observation("request-failed")))
        await writer.close()

    async def test_full_queue_drops_new_snapshot_without_blocking(self):
        sink = BlockingCleanupSink()
        writer = AgentObservationWriter(
            sink,
            queue_capacity=1,
            retention_days=30,
        )
        await writer.start()
        await asyncio.to_thread(sink.cleanup_started.wait, 1)

        first = writer.submit(observation("request-1"))
        second = writer.submit(observation("request-2"))
        sink.cleanup_release.set()
        await writer.close()

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(["request-1"], [item.request_id for item in sink.saved])


if __name__ == "__main__":
    unittest.main()
