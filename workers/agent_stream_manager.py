"""
Agent Stream Manager — per-agent SSE queue management.

Manages asyncio queues keyed by (migration_id, agent_name) for
streaming granular agent events to connected frontend clients.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from loguru import logger


class AgentStreamManager:
    """
    Manage in-memory queues for Server-Sent Events (SSE),
    keyed by (migration_id, agent_name).
    """

    def __init__(self):
        # (migration_id, agent_name) -> list of active client queues
        self._queues: Dict[Tuple[str, str], List[asyncio.Queue]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def register_queue(self, migration_id: str, agent_name: str) -> asyncio.Queue:
        """Register and return a new queue for a specific agent stream."""
        key = (migration_id, agent_name)
        if key not in self._queues:
            self._queues[key] = []
        queue = asyncio.Queue()
        self._queues[key].append(queue)
        self._loop = asyncio.get_event_loop()

        logger.info(
            f"Registered agent stream queue: {agent_name} for migration {migration_id} "
            f"(total listeners: {len(self._queues[key])})"
        )
        return queue

    def unregister_queue(self, migration_id: str, agent_name: str, queue: asyncio.Queue):
        """Remove a specific queue from a specific agent stream."""
        key = (migration_id, agent_name)
        if key in self._queues:
            try:
                self._queues[key].remove(queue)
            except ValueError:
                pass
            if not self._queues[key]:
                del self._queues[key]
            logger.info(f"Unregistered agent stream queue: {agent_name} for migration {migration_id}")

    def publish_sync(self, migration_id: str, agent_name: str, data: Dict[str, Any]):
        """
        Publish a message to all registered queues for a specific agent.
        Thread-safe: uses call_soon_threadsafe for cross-thread publishing.
        """
        key = (migration_id, agent_name)
        if not self._loop or key not in self._queues:
            return

        message = {
            **data,
            "migration_id": migration_id,
            "agent": agent_name,
            "timestamp": datetime.utcnow().isoformat(),
        }

        for queue in self._queues[key]:
            try:
                self._loop.call_soon_threadsafe(queue.put_nowait, message)
            except Exception as e:
                logger.warning(f"Failed to publish to agent stream queue: {e}")

    def get_stream_count(self, migration_id: str, agent_name: str) -> int:
        """Return number of active streams for an agent."""
        key = (migration_id, agent_name)
        return len(self._queues.get(key, []))


# Global singleton
agent_stream_manager = AgentStreamManager()
