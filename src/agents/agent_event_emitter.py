"""
Agent Event Emitter — thread-safe event publishing for agent execution.

Each agent instance gets its own emitter that publishes structured events
to the AgentStreamManager for SSE delivery to the frontend.
"""
from typing import Dict, Any, Optional
from loguru import logger


class AgentEventEmitter:
    """
    Thread-safe event emitter for a specific agent execution.
    Publishes structured events to all connected SSE clients.
    """

    # Valid agent names
    VALID_AGENTS = ("source_analysis", "data_model", "dax_conversion", "export")

    def __init__(self, migration_id: str, agent_name: str):
        if agent_name not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent name: {agent_name}. Must be one of {self.VALID_AGENTS}")

        self.migration_id = migration_id
        self.agent_name = agent_name

    def emit(
        self,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        sub_phase: str = "",
        progress: int = 0,
        message: str = "",
    ):
        """
        Emit a single agent event to all connected SSE clients.

        Args:
            event: Event type (e.g., 'file_parsed', 'formula_converted')
            data: Event-specific payload dict
            sub_phase: Current sub-phase label (e.g., 'Parsing TML...', 'Building graph...')
            progress: Agent-level progress 0-100
            message: Human-readable status message
        """
        from workers.agent_stream_manager import agent_stream_manager

        payload = {
            "type": "agent_event",
            "agent": self.agent_name,
            "event": event,
            "data": data or {},
            "sub_phase": sub_phase,
            "progress": max(0, min(100, progress)),
            "message": message,
        }

        agent_stream_manager.publish_sync(self.migration_id, self.agent_name, payload)

        logger.debug(
            f"[{self.migration_id}] Agent '{self.agent_name}' event: {event} "
            f"({progress}%) — {message or sub_phase}"
        )

    def complete(self, summary: Optional[Dict[str, Any]] = None, message: str = "Agent completed"):
        """Emit agent_complete event."""
        from workers.agent_stream_manager import agent_stream_manager

        payload = {
            "type": "agent_complete",
            "agent": self.agent_name,
            "event": "agent_complete",
            "data": summary or {},
            "sub_phase": "complete",
            "progress": 100,
            "message": message,
        }

        agent_stream_manager.publish_sync(self.migration_id, self.agent_name, payload)
        logger.info(f"[{self.migration_id}] Agent '{self.agent_name}' completed: {message}")

    def fail(self, error: str):
        """Emit agent_failed event."""
        from workers.agent_stream_manager import agent_stream_manager

        payload = {
            "type": "agent_failed",
            "agent": self.agent_name,
            "event": "agent_failed",
            "data": {"error": error},
            "sub_phase": "failed",
            "progress": -1,
            "message": error,
        }

        agent_stream_manager.publish_sync(self.migration_id, self.agent_name, payload)
        logger.error(f"[{self.migration_id}] Agent '{self.agent_name}' failed: {error}")
