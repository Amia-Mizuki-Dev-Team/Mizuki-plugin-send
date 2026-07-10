from __future__ import annotations

import asyncio
import logging

from .config import SendConfig
from .models import ActivityRecord
from .storage import ActivityStore


logger = logging.getLogger(__name__)


class ActivityWriter:
    def __init__(self, store: ActivityStore, config: SendConfig) -> None:
        self._store = store
        self._config = config
        self._queue: asyncio.Queue[ActivityRecord] = asyncio.Queue(config.queue_size)
        self._task: asyncio.Task[None] | None = None
        self.dropped_records = 0

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="amia-send-writer")

    def enqueue(self, record: ActivityRecord) -> None:
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.dropped_records += 1
            logger.warning("send activity queue full; record dropped")

    async def stop(self) -> None:
        if self._task is not None:
            await self._queue.join()
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            records = [first]
            try:
                while len(records) < self._config.batch_size:
                    records.append(
                        await asyncio.wait_for(
                            self._queue.get(), self._config.flush_interval_seconds
                        )
                    )
            except TimeoutError:
                pass
            try:
                await self._store.upsert_batch(records)
            except Exception:
                logger.exception("unable to persist send activity batch")
            finally:
                for _ in records:
                    self._queue.task_done()
