"""
Migration Router — /api/v1/ts-migration/

Endpoints:
  POST   /upload              → upload .tml/.zip, start conversion job
  GET    /{id}                → get job status + stats
  GET    /{id}/conversions    → list of all DAX conversions (for Review page)
  GET    /{id}/download       → download output (zip/pbip/excel/dax/json)
"""
import uuid
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from api.config import config
from api.models import (
    UploadResponse,
    MigrationStatusResponse,
    ConversionsResponse,
)
from storage.migration_store import (
    create_migration,
    get_migration,
    update_migration_status,
    get_migration_conversions,
)
from storage.file_store import FileStore

router = APIRouter(prefix="/api/v1/ts-migration")

# Shared FileStore instance
_file_store = FileStore(config.UPLOAD_DIR, config.EXPORT_DIR)

# ── Simple one-at-a-time job lock ─────────────────────────────────────────────
_job_lock = threading.Lock()
_running_job: Optional[str] = None


# ── Upload & Start ─────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
):
    """
    Upload ThoughtSpot .tml or .zip files and start the migration pipeline.
    Returns a migration_id immediately; poll GET /{id} for status.
    """
    global _running_job

    # Validate file types
    for f in files:
        if not (f.filename.endswith(".tml") or f.filename.endswith(".zip")):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file: '{f.filename}'. Only .tml and .zip files are accepted.",
            )

    # One-at-a-time guard
    if _running_job and _running_job != "":
        raise HTTPException(
            status_code=429,
            detail="A migration job is already running. Please wait for it to complete.",
        )

    migration_id = f"ts_mig_{uuid.uuid4().hex[:12]}"

    # Save uploaded files via FileStore
    upload_dir = _file_store.upload_dir(migration_id)

    file_paths = []
    for f in files:
        dest = upload_dir / f.filename
        content = await f.read()
        dest.write_bytes(content)
        file_paths.append(str(dest))

    # Create DB record
    create_migration(
        db_path=config.DATABASE_PATH,
        migration_id=migration_id,
        source_type="thoughtspot",
        file_count=len(files),
    )

    # Start background job
    background_tasks.add_task(_run_migration, migration_id, file_paths)

    logger.info(f"Migration {migration_id} queued with {len(files)} file(s)")

    return {
        "migration_id": migration_id,
        "status": "processing",
        "file_count": len(files),
        "message": f"Uploaded {len(files)} file(s). Migration started.",
    }


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/{migration_id}", response_model=MigrationStatusResponse)
async def get_status(migration_id: str):
    """Get migration job status and summary statistics."""
    row = get_migration(config.DATABASE_PATH, migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Migration not found")

    return {
        "migration_id": row["migration_id"],
        "status": row["status"],
        "file_count": row["file_count"],
        "tables": row["tables_count"],
        "formulas_converted": row["formulas_count"],
        "high_confidence": row["high_confidence"],
        "medium_confidence": row["medium_confidence"],
        "low_confidence": row["low_confidence"],
        "requires_review": row["requires_review"],
        "error_message": row["error_message"],
        "elapsed_seconds": row["elapsed_seconds"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "narrative_summary": row["narrative_summary"],
    }




# ── Conversions (for Review page) ──────────────────────────────────────────────

@router.get("/{migration_id}/conversions")
async def get_conversions(migration_id: str):
    """
    Return all DAX conversion results for the Review page.
    Grouped by source_object in the response.
    """
    row = get_migration(config.DATABASE_PATH, migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Migration not found")
    if row["status"] == "processing":
        return JSONResponse(status_code=202, content={"detail": "Migration still in progress"})

    conversions = get_migration_conversions(config.DATABASE_PATH, migration_id)
    return {"migration_id": migration_id, "conversions": conversions}


# ── Download ────────────────────────────────────────────────────────────────────

@router.get("/{migration_id}/download")
async def download_output(
    migration_id: str,
    file: str = Query(default="all", description="all | pbip | excel | dax | json"),
):
    """Download migration output files."""
    row = get_migration(config.DATABASE_PATH, migration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Migration not found")
    if row["status"] != "completed":
        raise HTTPException(status_code=202, detail="Migration not yet complete")

    MEDIA_TYPES = {
        "all":   ("application/zip",                                                      f"powerbi_migration_{migration_id}.zip"),
        "pbip":  ("application/zip",                                                      f"pbip_{migration_id}.zip"),
        "excel": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",   f"migration_report_{migration_id}.xlsx"),
        "dax":   ("text/plain",                                                           f"measures_{migration_id}.dax"),
        "json":  ("application/json",                                                     f"model_{migration_id}.json"),
    }

    if file not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid file param. Use: {', '.join(MEDIA_TYPES.keys())}")

    path = _file_store.get_download_path(migration_id, file)
    media_type, filename = MEDIA_TYPES[file]

    if not path or not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    return FileResponse(path=str(path), media_type=media_type, filename=filename)


# ── Background Runner ───────────────────────────────────────────────────────────

def _run_migration(migration_id: str, file_paths: List[str]):
    """Run the migration pipeline in a background thread."""
    global _running_job
    _running_job = migration_id

    try:
        from src.orchestrator import MigrationOrchestrator
        orchestrator = MigrationOrchestrator(
            db_path=config.DATABASE_PATH,
            export_dir=config.EXPORT_DIR,
        )
        orchestrator.execute(migration_id, file_paths)
    except Exception as e:
        logger.error(f"Migration {migration_id} failed: {e}", exc_info=True)
        update_migration_status(
            config.DATABASE_PATH,
            migration_id,
            status="failed",
            error_message=str(e),
        )
    finally:
        _running_job = ""
