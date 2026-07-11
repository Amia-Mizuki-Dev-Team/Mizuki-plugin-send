from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import SendConfig
from .models import ActivityRecord
from .storage import ActivityStore


logger = logging.getLogger(__name__)


class ActivityWriter:
    def __init__(self, store: ActivityStore, config: SendConfig) -> None:
        self._store = store
        self._config = config
        self._queue: asyncio.Queue[ActivityRecord] = asyncio.Queue(
            config.queue_size
        )
        self._task: asyncio.Task[None] | None = None
        self._dead_letter_tasks: set[asyncio.Task[None]] = set()
        self._dead_letter_lock = asyncio.Lock()

        self.dropped_records = 0
        self.last_dropped_at: float | None = None
        self.failed_batches = 0
        self.failed_records = 0
        self.last_failure_at: datetime | None = None
        self.last_failure_error: str | None = None

    @property
    def dead_letter_path(self) -> Path:
        return self._config.dead_letter_path or Path(
            f"{self._config.db_path}.dead-letter.jsonl"
        )

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="amia-send-writer",
            )

    def enqueue(self, record: ActivityRecord) -> None:
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.dropped_records += 1
            self.last_dropped_at = asyncio.get_running_loop().time()
            logger.warning(
                "send activity queue full; record redirected to dead letter "
                "storage (total=%s)",
                self.dropped_records,
            )
            task = asyncio.create_task(
                self._persist_failed_records(
                    [record],
                    RuntimeError("activity writer queue is full"),
                )
            )
            self._dead_letter_tasks.add(task)
            task.add_done_callback(self._dead_letter_tasks.discard)

    async def stop(self) -> None:
        if self._task is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error(
                    "send writer shutdown timed out with %s queued records",
                    self._queue.qsize(),
                )

            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._dead_letter_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *tuple(self._dead_letter_tasks),
                        return_exceptions=True,
                    ),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "send dead letter tasks did not finish before shutdown"
                )

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            records = [first]
            deadline = (
                asyncio.get_running_loop().time()
                + self._config.flush_interval_seconds
            )

            try:
                while len(records) < self._config.batch_size:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    records.append(
                        await asyncio.wait_for(
                            self._queue.get(),
                            remaining,
                        )
                    )
            except TimeoutError:
                pass

            persisted = False
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    await self._store.upsert_batch(records)
                    persisted = True
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        await asyncio.sleep(0.1 * (2**attempt))

            if not persisted:
                self.failed_batches += 1
                await self._persist_failed_records(
                    records,
                    last_error or RuntimeError("unknown persistence failure"),
                )
                if last_error is not None:
                    logger.error(
                        "unable to persist send activity batch after retries; "
                        "records written to %s",
                        self.dead_letter_path,
                        exc_info=(
                            type(last_error),
                            last_error,
                            last_error.__traceback__,
                        ),
                    )

            for _ in records:
                self._queue.task_done()

    async def _persist_failed_records(
        self,
        records: list[ActivityRecord],
        error: Exception,
    ) -> None:
        self.failed_records += len(records)
        self.last_failure_at = datetime.now(timezone.utc)
        self.last_failure_error = f"{type(error).__name__}: {error}"

        payload = {
            "failed_at": self.last_failure_at.isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "records": [asdict(record) for record in records],
        }

        try:
            async with self._dead_letter_lock:
                await asyncio.to_thread(
                    self._append_dead_letter_payload,
                    payload,
                )
        except Exception:
            logger.exception(
                "unable to write send activity dead letter file"
            )

    def _append_dead_letter_payload(self, payload: dict) -> None:
        path = self.dead_letter_path
        path.parent.mkdir(parents=True, exist_ok=True)

        line = json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ) + "\n"
        encoded_size = len(line.encode("utf-8"))

        if (
            path.exists()
            and path.stat().st_size + encoded_size
            > self._config.dead_letter_max_bytes
        ):
            rotated = path.with_name(f"{path.name}.1")
            rotated.unlink(missing_ok=True)
            path.replace(rotated)

        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
