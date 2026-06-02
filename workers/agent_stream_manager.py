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
    Manage in-memory queues and event history for Server-Sent Events (SSE),
    keyed by (migration_id, agent_name).
    """

    def __init__(self):
        # (migration_id, agent_name) -> list of active client queues
        self._queues: Dict[Tuple[str, str], List[asyncio.Queue]] = {}
        # (migration_id, agent_name) -> list of historical event payloads (for replay)
        self._history: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def clear_history(self, migration_id: str, agent_name: str):
        """Clear event history for a specific agent execution."""
        key = (migration_id, agent_name)
        if key in self._history:
            del self._history[key]
            logger.info(f"Cleared stream event history for agent: {agent_name}")

    def register_queue(self, migration_id: str, agent_name: str) -> asyncio.Queue:
        """Register and return a new queue for a specific agent stream, pre-populating with history."""
        key = (migration_id, agent_name)
        if key not in self._queues:
            self._queues[key] = []
        queue = asyncio.Queue()
        
        # Replay any historical events emitted before the client connected
        if key in self._history:
            logger.info(f"Replaying {len(self._history[key])} historical event(s) to new stream listener: {agent_name}")
            for msg in self._history[key]:
                queue.put_nowait(msg)
                
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
        
        message = {
            **data,
            "migration_id": migration_id,
            "agent": agent_name,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Store in history for late-connecting clients
        if key not in self._history:
            self._history[key] = []
        self._history[key].append(message)

        if not self._loop or key not in self._queues:
            return

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
