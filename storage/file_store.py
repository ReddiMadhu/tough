"""
file_store.py — file path management for uploads and exports.

Centralises all path construction so the router and orchestrator
never build paths by hand.
"""
from pathlib import Path
from typing import List, Optional
from loguru import logger


class FileStore:
    """Manage uploaded TML files and generated export files."""

    def __init__(self, upload_dir: str, export_dir: str):
        self.upload_root = Path(upload_dir)
        self.export_root = Path(export_dir)

    # ── Upload paths ───────────────────────────────────────────────────────────

    def upload_dir(self, migration_id: str) -> Path:
        """Return (and create) the upload directory for a migration."""
        path = self.upload_root / migration_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def upload_path(self, migration_id: str, filename: str) -> Path:
        """Return the path for a single uploaded file."""
        return self.upload_dir(migration_id) / filename

    def list_uploads(self, migration_id: str) -> List[str]:
        """Return all uploaded file paths for a migration."""
        d = self.upload_root / migration_id
        if not d.exists():
            return []
        return [str(p) for p in d.iterdir() if p.is_file()]

    # ── Export paths ───────────────────────────────────────────────────────────

    def export_dir(self, migration_id: str) -> Path:
        """Return (and create) the export directory for a migration."""
        path = self.export_root / migration_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def pbip_dir(self, migration_id: str) -> Path:
        """Return the PBIP project subdirectory."""
        return self.export_dir(migration_id) / "pbip"

    def static_pbip_dir(self) -> Path:
        """Return the static pbip-ts directory (pre-built PBIP project)."""
        # Candidate 1: relative to file_store.py (bknd-ts/storage/file_store.py -> bknd-ts/pbip-ts)
        path1 = Path(__file__).resolve().parent.parent / "pbip-ts"
        if path1.exists() and path1.is_dir():
            return path1

        # Candidate 2: relative to current working directory
        path2 = Path("pbip-ts").resolve()
        if path2.exists() and path2.is_dir():
            return path2

        # Candidate 3: relative to parent of current working directory
        path3 = Path("../pbip-ts").resolve()
        if path3.exists() and path3.is_dir():
            return path3

        # Default fallback to Candidate 1
        return path1

    def full_zip_path(self, migration_id: str) -> Path:
        return self.export_dir(migration_id) / f"{migration_id}_powerbi_output.zip"

    def pbip_zip_path(self, migration_id: str) -> Path:
        return self.export_dir(migration_id) / f"{migration_id}_pbip.zip"

    def excel_path(self, migration_id: str) -> Path:
        return self.export_dir(migration_id) / f"{migration_id}_migration_report.xlsx"

    def dax_path(self, migration_id: str) -> Path:
        return self.export_dir(migration_id) / f"{migration_id}_measures.dax"

    def json_path(self, migration_id: str) -> Path:
        return self.export_dir(migration_id) / f"{migration_id}_intermediate_model.json"

    def get_download_path(self, migration_id: str, file_type: str) -> Optional[Path]:
        """
        Resolve a download file_type key to its Path.
        Returns None if the file_type is unknown.
        """
        mapping = {
            "all":   self.full_zip_path(migration_id),
            "pbip":  self.pbip_zip_path(migration_id),
            "excel": self.excel_path(migration_id),
            "dax":   self.dax_path(migration_id),
            "json":  self.json_path(migration_id),
        }
        return mapping.get(file_type)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def delete_uploads(self, migration_id: str):
        """Delete all uploaded source files for a migration (to save disk space)."""
        import shutil
        d = self.upload_root / migration_id
        if d.exists():
            shutil.rmtree(d)
            logger.info(f"Deleted uploads for {migration_id}")
