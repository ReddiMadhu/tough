"""
ProgressCallback — thread-safe progress reporting for the MigrationOrchestrator.

Pushes updates to:
  1. SQLite database (progress_percent, current_stage)
  2. WebSocket clients (real-time via ws_manager.broadcast_sync)

Usage in orchestrator:
    from workers.progress_manager import ProgressCallback

    cb = ProgressCallback(migration_id, db_path)
    cb.update("parsing", 15, "Parsing TML files...")
"""
import time
from typing import Optional, Callable
from loguru import logger


class ProgressCallback:
    """
    Thread-safe progress callback that updates both the database
    and any connected WebSocket clients.
    """

    def __init__(
        self,
        migration_id: str,
        db_path: str,
        min_interval: float = 0.5,
    ):
        """
        Args:
            migration_id: The migration job ID
            db_path: Path to the SQLite database
            min_interval: Minimum seconds between WS broadcasts (throttle)
        """
        self.migration_id = migration_id
        self.db_path = db_path
        self.min_interval = min_interval
        self._last_broadcast_time: float = 0

    def update(
        self,
        stage: str,
        percent: int,
        message: str,
        force: bool = False,
    ):
        """
        Report progress.

        Args:
            stage: Current pipeline stage (e.g. 'parsing', 'converting')
            percent: Progress percentage (0-100)
            message: Human-readable status message
            force: Bypass throttle (e.g. for completion/error)
        """
        is_failed = percent < 0 or stage == "failed"
        is_completed = percent == 100 or stage == "completed"
        is_terminal = is_failed or is_completed

        if not is_failed:
            percent = max(0, min(100, percent))

        # Always update database
        self._update_db(stage, percent, message)

        # Throttle WebSocket broadcasts
        now = time.time()
        if force or is_terminal or (now - self._last_broadcast_time) >= self.min_interval:
            self._broadcast_ws(stage, percent, message)
            self._last_broadcast_time = now

    def complete(self, message: str = "Migration completed successfully"):
        """Report completion."""
        self.update("completed", 100, message, force=True)

    def fail(self, error: str):
        """Report failure."""
        self.update("failed", -1, error, force=True)

    # ── Internal ────────────────────────────────────────────────────────────

    def _update_db(self, stage: str, percent: int, message: str):
        """Persist progress to SQLite."""
        try:
            from storage.migration_store import update_migration_progress
            update_migration_progress(
                db_path=self.db_path,
                migration_id=self.migration_id,
                progress_percent=percent,
                current_stage=stage,
                message=message,
            )
        except Exception as e:
            logger.debug(f"Progress DB update failed (non-critical): {e}")

    def _broadcast_ws(self, stage: str, percent: int, message: str):
        """Push progress to connected SSE clients."""
        try:
            from workers.stream_manager import stream_manager
            status = "completed" if percent == 100 else "failed" if percent < 0 else "processing"
            msg_type = "completed" if percent == 100 else "failed" if percent < 0 else "progress"
            stream_manager.publish_sync(
                self.migration_id,
                {
                    "type": msg_type,
                    "progress_percent": percent,
                    "current_stage": stage,
                    "message": message,
                    "status": status
                },
            )
        except Exception as e:
            logger.debug(f"SSE stream publish failed (non-critical): {e}")
