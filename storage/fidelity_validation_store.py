"""
Fidelity Validation Store - Database operations for ThoughtSpot → Power BI 100% fidelity validation
"""
import sqlite3
import json
from typing import Dict, List, Any, Optional
from loguru import logger
from storage.migration_store import _connect


def save_validation_result(db_path: str, migration_id: str, conversion_id: str, result: Dict[str, Any]) -> int:
    """Save validation results for a conversion."""
    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO ts_validation_results
               (conversion_id, migration_id, overall_passed, pass_rate, test_results, error_categories, needs_manual_review)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                conversion_id,
                migration_id,
                1 if result.get("overall_passed") else 0,
                result.get("pass_rate", 0.0),
                json.dumps(result.get("test_slices", [])),
                json.dumps(result.get("error_categories", {})),
                1 if result.get("needs_manual_review") else 0
            )
        )
        conn.commit()
        logger.info(f"Saved validation result for conversion {conversion_id}")
        return cursor.lastrowid
    finally:
        conn.close()


def get_validation_results(db_path: str, migration_id: str) -> List[Dict[str, Any]]:
    """Get all validation results for a migration."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ts_validation_results WHERE migration_id=? ORDER BY created_at DESC",
            (migration_id,)
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["overall_passed"] = bool(d["overall_passed"])
            d["needs_manual_review"] = bool(d["needs_manual_review"])
            try:
                d["test_results"] = json.loads(d["test_results"]) if d["test_results"] else []
            except Exception:
                d["test_results"] = []
            try:
                d["error_categories"] = json.loads(d["error_categories"]) if d["error_categories"] else {}
            except Exception:
                d["error_categories"] = {}
            results.append(d)
        return results
    finally:
        conn.close()


def get_validation_result_by_conversion(db_path: str, conversion_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest validation result for a single conversion."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM ts_validation_results WHERE conversion_id=? ORDER BY created_at DESC LIMIT 1",
            (conversion_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["overall_passed"] = bool(d["overall_passed"])
        d["needs_manual_review"] = bool(d["needs_manual_review"])
        try:
            d["test_results"] = json.loads(d["test_results"]) if d["test_results"] else []
        except Exception:
            d["test_results"] = []
        try:
            d["error_categories"] = json.loads(d["error_categories"]) if d["error_categories"] else {}
        except Exception:
            d["error_categories"] = {}
        return d
    finally:
        conn.close()


def save_correction_attempt(db_path: str, migration_id: str, conversion_id: str, attempt: Dict[str, Any]) -> int:
    """Save a self-healing correction attempt."""
    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO ts_correction_attempts
               (conversion_id, migration_id, attempt_number, original_dax, corrected_dax, root_cause, explanation, changes_made)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conversion_id,
                migration_id,
                attempt.get("attempt_number"),
                attempt.get("original_dax"),
                attempt.get("corrected_dax"),
                attempt.get("root_cause"),
                attempt.get("explanation"),
                json.dumps(attempt.get("changes_made", []))
            )
        )
        conn.commit()
        logger.info(f"Saved correction attempt {attempt.get('attempt_number')} for conversion {conversion_id}")
        return cursor.lastrowid
    finally:
        conn.close()


def get_correction_history(db_path: str, migration_id: str) -> List[Dict[str, Any]]:
    """Get the correction history timeline for a migration."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ts_correction_attempts WHERE migration_id=? ORDER BY created_at ASC",
            (migration_id,)
        ).fetchall()
        attempts = []
        for r in rows:
            d = dict(r)
            try:
                d["changes_made"] = json.loads(d["changes_made"]) if d["changes_made"] else []
            except Exception:
                d["changes_made"] = []
            attempts.append(d)
        return attempts
    finally:
        conn.close()


def save_model_enhancement(db_path: str, migration_id: str, enhancement: Dict[str, Any]) -> int:
    """Save a recommended model enhancement to the database."""
    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO ts_model_enhancements
               (migration_id, enhancement_type, description, dax_code, m_script, priority, related_calc_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                migration_id,
                enhancement.get("enhancement_type"),
                enhancement.get("description"),
                enhancement.get("dax_code"),
                enhancement.get("m_script"),
                enhancement.get("priority", "MEDIUM"),
                enhancement.get("related_calc_name")
            )
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_model_enhancements(db_path: str, migration_id: str) -> List[Dict[str, Any]]:
    """Get all recommended model enhancements for a migration."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ts_model_enhancements WHERE migration_id=? ORDER BY priority DESC, id ASC",
            (migration_id,)
        ).fetchall()
        enhancements = []
        for r in rows:
            enhancements.append(dict(r))
        return enhancements
    finally:
        conn.close()


def clear_model_enhancements(db_path: str, migration_id: str):
    """Delete all model enhancements for a migration."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM ts_model_enhancements WHERE migration_id=?", (migration_id,))
        conn.commit()
    finally:
        conn.close()

