"""JSON exporter — saves the intermediate model as a .json file."""
import json
from pathlib import Path
from typing import Dict, Any
from loguru import logger


def export_json_model(
    intermediate_model: Dict[str, Any],
    output_dir: str,
    migration_id: str,
) -> str:
    """Export the parsed intermediate model as a JSON file."""
    output_path = Path(output_dir) / f"{migration_id}_intermediate_model.json"
    output_path.write_text(
        json.dumps(intermediate_model, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(f"Intermediate model JSON saved: {output_path}")
    return str(output_path)
