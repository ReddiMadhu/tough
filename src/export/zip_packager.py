"""ZIP packager — bundles all output files into a single downloadable archive."""
import zipfile
from pathlib import Path
from typing import List, Optional
from loguru import logger


def package_outputs(
    export_dir: str,
    migration_id: str,
    pbip_dir: Optional[str] = None,
    excel_path: Optional[str] = None,
    dax_path: Optional[str] = None,
    json_path: Optional[str] = None,
    guide_path: Optional[str] = None,
) -> str:
    """
    Create a master ZIP containing all migration outputs.
    Returns path to the zip file.
    """
    zip_path = Path(export_dir) / f"{migration_id}_powerbi_output.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # PBIP project folder
        if pbip_dir and Path(pbip_dir).exists():
            pbip_root = Path(pbip_dir)
            for file_path in pbip_root.rglob("*"):
                if file_path.is_file():
                    arcname = f"pbip/{file_path.relative_to(pbip_root)}"
                    zf.write(file_path, arcname)

        # Individual files
        for path, arcname in [
            (excel_path, f"{migration_id}_migration_report.xlsx"),
            (dax_path, f"{migration_id}_measures.dax"),
            (json_path, f"{migration_id}_intermediate_model.json"),
            (guide_path, "MODEL_ENHANCEMENTS_REQUIRED.md"),
        ]:
            if path and Path(path).exists():
                zf.write(path, arcname)

    logger.info(f"Output ZIP created: {zip_path}")
    return str(zip_path)


def package_pbip_only(pbip_dir: str, export_dir: str, migration_id: str) -> str:
    """Create a ZIP containing just the PBIP project folder."""
    zip_path = Path(export_dir) / f"{migration_id}_pbip.zip"
    pbip_root = Path(pbip_dir)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pbip_root.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(pbip_root))

    logger.info(f"PBIP ZIP created: {zip_path}")
    return str(zip_path)
