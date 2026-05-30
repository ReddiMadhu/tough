"""
Stream Manager — manages active SSE client stream queues for real-time progress updates.

Thread-safe publishing from background threads uses asyncio.get_event_loop().call_soon_threadsafe().
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger


class ProgressStreamManager:
    """
    Manage in-memory queues for Server-Sent Events (SSE) progress streams,
    grouped by migration_id.
    """

    def __init__(self):
        # migration_id -> list of active client queues
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        # Reference to the running event loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def register_queue(self, migration_id: str) -> asyncio.Queue:
        """Register and return a new queue for a migration stream connection."""
        if migration_id not in self._queues:
            self._queues[migration_id] = []
        queue = asyncio.Queue()
        self._queues[migration_id].append(queue)
        self._loop = asyncio.get_event_loop()

        logger.info(f"Registered progress stream queue for migration {migration_id} "
                     f"(total listening: {len(self._queues[migration_id])})")
        return queue

    def unregister_queue(self, migration_id: str, queue: asyncio.Queue):
        """Remove a progress stream queue."""
        if migration_id in self._queues:
            try:
                self._queues[migration_id].remove(queue)
            except ValueError:
                pass
            if not self._queues[migration_id]:
                del self._queues[migration_id]
            logger.info(f"Unregistered progress stream queue for migration {migration_id}")

    def publish_sync(self, migration_id: str, data: Dict[str, Any]):
        """
        Publish message to all registered queues for a migration.
        Safe to call from synchronous background execution threads.
        """
        if not self._loop or migration_id not in self._queues:
            return

        message = {
            **data,
            "migration_id": migration_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Put items in all active queues in a thread-safe manner
        for queue in self._queues[migration_id]:
            try:
                self._loop.call_soon_threadsafe(queue.put_nowait, message)
            except Exception as e:
                logger.warning(f"Failed to publish to stream queue: {e}")

    def get_stream_count(self, migration_id: str) -> int:
        """Return number of active streams for a migration."""
        return len(self._queues.get(migration_id, []))


# Global singleton
stream_manager = ProgressStreamManager()
