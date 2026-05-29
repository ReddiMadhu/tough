"""
SQLite storage for ThoughtSpot → Power BI migration jobs.
Shares the same migrations.db as the Tableau migrator via source_type column.
"""
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from loguru import logger


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: str):
    """Create the migrations and conversions tables if they don't exist."""
    conn = _connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS migrations (
                migration_id      TEXT PRIMARY KEY,
                source_type       TEXT NOT NULL DEFAULT 'thoughtspot',
                status            TEXT NOT NULL DEFAULT 'processing',
                file_count        INTEGER DEFAULT 0,
                tables_count      INTEGER DEFAULT 0,
                formulas_count    INTEGER DEFAULT 0,
                high_confidence   INTEGER DEFAULT 0,
                medium_confidence INTEGER DEFAULT 0,
                low_confidence    INTEGER DEFAULT 0,
                requires_review   INTEGER DEFAULT 0,
                error_message     TEXT,
                created_at        TEXT,
                completed_at      TEXT,
                elapsed_seconds   REAL,
                narrative_summary TEXT
            );

            CREATE TABLE IF NOT EXISTS ts_conversions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id      TEXT NOT NULL,
                conversion_id     TEXT,
                measure_name      TEXT,
                original_formula  TEXT,
                dax_formula       TEXT,
                confidence        REAL,
                pattern           TEXT,
                notes             TEXT,
                requires_review   INTEGER DEFAULT 0,
                source_object     TEXT,
                source_object_type TEXT,
                format_pattern    TEXT,
                FOREIGN KEY (migration_id) REFERENCES migrations(migration_id)
            );
        """)
        
        # Ensure narrative_summary exists if table already existed (backward compatibility)
        try:
            conn.execute("ALTER TABLE migrations ADD COLUMN narrative_summary TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Already exists
            
        conn.commit()
        logger.info(f"Database initialized at {db_path}")
    finally:
        conn.close()



def create_migration(db_path: str, migration_id: str, source_type: str, file_count: int):
    """Insert a new migration record with processing status."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO migrations (migration_id, source_type, status, file_count, created_at)
               VALUES (?, ?, 'processing', ?, ?)""",
            (migration_id, source_type, file_count, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def update_migration_status(
    db_path: str,
    migration_id: str,
    status: str,
    error_message: Optional[str] = None,
    stats: Optional[Dict[str, Any]] = None,
    elapsed_seconds: Optional[float] = None,
    narrative_summary: Optional[str] = None,
):
    """Update migration status and optionally set stats."""
    conn = _connect(db_path)
    try:
        if stats:
            conn.execute(
                """UPDATE migrations SET
                       status=?, tables_count=?, formulas_count=?,
                       high_confidence=?, medium_confidence=?, low_confidence=?,
                       requires_review=?, error_message=?, completed_at=?, elapsed_seconds=?,
                       narrative_summary=?
                   WHERE migration_id=?""",
                (
                    status,
                    stats.get("tables", 0),
                    stats.get("formulas_converted", 0),
                    stats.get("high_confidence", 0),
                    stats.get("medium_confidence", 0),
                    stats.get("low_confidence", 0),
                    stats.get("requires_review", 0),
                    error_message,
                    datetime.utcnow().isoformat(),
                    elapsed_seconds,
                    narrative_summary,
                    migration_id,
                ),
            )
        else:
            conn.execute(
                """UPDATE migrations SET status=?, error_message=?, completed_at=?, elapsed_seconds=?
                   WHERE migration_id=?""",
                (status, error_message, datetime.utcnow().isoformat(), elapsed_seconds, migration_id),
            )
        conn.commit()
    finally:
        conn.close()



def get_migration(db_path: str, migration_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a migration record by ID."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM migrations WHERE migration_id=?", (migration_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_conversions(db_path: str, migration_id: str, conversions: List[Dict[str, Any]]):
    """Bulk-insert all DAX conversion results."""
    conn = _connect(db_path)
    try:
        conn.executemany(
            """INSERT INTO ts_conversions
               (migration_id, conversion_id, measure_name, original_formula, dax_formula,
                confidence, pattern, notes, requires_review, source_object, source_object_type, format_pattern)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    migration_id,
                    c.get("conversion_id", ""),
                    c.get("measure_name", ""),
                    c.get("original_formula", ""),
                    c.get("dax_formula", ""),
                    c.get("confidence", 0.0),
                    c.get("pattern", ""),
                    json.dumps(c.get("notes", [])),
                    1 if c.get("requires_review") else 0,
                    c.get("source_object", ""),
                    c.get("source_object_type", ""),
                    c.get("format_pattern", ""),
                )
                for c in conversions
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_migration_conversions(db_path: str, migration_id: str) -> List[Dict[str, Any]]:
    """Fetch all DAX conversions for a migration."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ts_conversions WHERE migration_id=? ORDER BY source_object, id",
            (migration_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["notes"] = json.loads(d["notes"]) if d["notes"] else []
            except Exception:
                d["notes"] = []
            d["requires_review"] = bool(d["requires_review"])
            result.append(d)
        return result
    finally:
        conn.close()
