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
                narrative_summary TEXT,
                progress_percent  INTEGER DEFAULT 0,
                current_stage     TEXT DEFAULT '',
                workbook_count    INTEGER DEFAULT 0,
                calculation_count INTEGER DEFAULT 0,
                relationship_count INTEGER DEFAULT 0,
                logic_graph_json  TEXT
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

            CREATE TABLE IF NOT EXISTS ts_calculations (
                calc_id           TEXT PRIMARY KEY,
                migration_id      TEXT NOT NULL,
                calc_name         TEXT NOT NULL,
                calc_formula      TEXT,
                calc_type         TEXT DEFAULT 'STANDARD',
                dependency_level  INTEGER DEFAULT 0,
                depends_on        TEXT,
                depends_on_metadata TEXT,
                used_in_worksheets TEXT,
                source_object     TEXT,
                source_object_type TEXT,
                FOREIGN KEY (migration_id) REFERENCES migrations(migration_id)
            );

            CREATE TABLE IF NOT EXISTS ts_validation_results (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                conversion_id     TEXT NOT NULL,
                migration_id      TEXT NOT NULL,
                overall_passed    INTEGER DEFAULT 0,
                pass_rate         REAL DEFAULT 0.0,
                test_results      TEXT,
                error_categories  TEXT,
                needs_manual_review INTEGER DEFAULT 0,
                created_at        TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ts_correction_attempts (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                conversion_id     TEXT NOT NULL,
                migration_id      TEXT NOT NULL,
                attempt_number    INTEGER,
                original_dax      TEXT,
                corrected_dax     TEXT,
                root_cause        TEXT,
                explanation       TEXT,
                changes_made      TEXT,
                created_at        TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ts_model_enhancements (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_id      TEXT NOT NULL,
                enhancement_type  TEXT,
                description       TEXT,
                dax_code          TEXT,
                m_script          TEXT,
                priority          TEXT DEFAULT 'MEDIUM',
                related_calc_name TEXT,
                created_at        TEXT DEFAULT (datetime('now'))
            );
        """)
        
        # Backward compatibility: add columns if they don't exist yet
        _new_columns = [
            ("narrative_summary", "TEXT"),
            ("progress_percent", "INTEGER DEFAULT 0"),
            ("current_stage", "TEXT DEFAULT ''"),
            ("workbook_count", "INTEGER DEFAULT 0"),
            ("calculation_count", "INTEGER DEFAULT 0"),
            ("relationship_count", "INTEGER DEFAULT 0"),
            ("logic_graph_json", "TEXT"),
        ]
        for col_name, col_type in _new_columns:
            try:
                conn.execute(f"ALTER TABLE migrations ADD COLUMN {col_name} {col_type}")
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


def update_migration_progress(
    db_path: str,
    migration_id: str,
    progress_percent: int,
    current_stage: str,
    message: str = "",
):
    """Update the real-time progress fields (called by ProgressCallback)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE migrations SET progress_percent=?, current_stage=?
               WHERE migration_id=?""",
            (progress_percent, current_stage, migration_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_calculations_batch(db_path: str, migration_id: str, calculations: List[Dict[str, Any]]):
    """Bulk-insert calculation records for the logic graph."""
    conn = _connect(db_path)
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO ts_calculations
               (calc_id, migration_id, calc_name, calc_formula, calc_type,
                dependency_level, depends_on, depends_on_metadata,
                used_in_worksheets, source_object, source_object_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    c.get("calc_id", ""),
                    migration_id,
                    c.get("calc_name", ""),
                    c.get("calc_formula", ""),
                    c.get("calc_type", "STANDARD"),
                    c.get("dependency_level", 0),
                    json.dumps(c.get("depends_on", [])),
                    json.dumps(c.get("depends_on_metadata", {})),
                    c.get("used_in_worksheets", ""),
                    c.get("source_object", ""),
                    c.get("source_object_type", ""),
                )
                for c in calculations
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_calculations(db_path: str, migration_id: str) -> List[Dict[str, Any]]:
    """Fetch all calculations for a migration."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ts_calculations WHERE migration_id=? ORDER BY dependency_level, calc_name",
            (migration_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["depends_on"] = json.loads(d["depends_on"]) if d["depends_on"] else []
            except Exception:
                d["depends_on"] = []
            try:
                d["depends_on_metadata"] = json.loads(d["depends_on_metadata"]) if d["depends_on_metadata"] else {}
            except Exception:
                d["depends_on_metadata"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def update_migration_counts(
    db_path: str,
    migration_id: str,
    workbook_count: Optional[int] = None,
    calculation_count: Optional[int] = None,
    relationship_count: Optional[int] = None,
):
    """Update object count fields on the migration record."""
    conn = _connect(db_path)
    try:
        sets = []
        vals = []
        if workbook_count is not None:
            sets.append("workbook_count=?")
            vals.append(workbook_count)
        if calculation_count is not None:
            sets.append("calculation_count=?")
            vals.append(calculation_count)
        if relationship_count is not None:
            sets.append("relationship_count=?")
            vals.append(relationship_count)
        if sets:
            vals.append(migration_id)
            conn.execute(
                f"UPDATE migrations SET {', '.join(sets)} WHERE migration_id=?",
                vals,
            )
            conn.commit()
    finally:
        conn.close()


def save_logic_graph(db_path: str, migration_id: str, graph_json: str):
    """Store the serialized logic graph JSON."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE migrations SET logic_graph_json=? WHERE migration_id=?",
            (graph_json, migration_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_logic_graph(db_path: str, migration_id: str) -> Optional[str]:
    """Retrieve the stored logic graph JSON string."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT logic_graph_json FROM migrations WHERE migration_id=?",
            (migration_id,),
        ).fetchone()
        return row["logic_graph_json"] if row else None
    finally:
        conn.close()


def update_conversion_dax(db_path: str, conversion_id: str, dax_formula: str, notes: str = ""):
    """Update a single conversion's DAX formula (manual override)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE ts_conversions SET dax_formula=?, notes=? WHERE conversion_id=?",
            (dax_formula, notes, conversion_id),
        )
        conn.commit()
    finally:
        conn.close()
