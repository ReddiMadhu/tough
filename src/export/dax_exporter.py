"""DAX file exporter — generates a standalone .dax file with all measures."""
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger


def export_dax_file(
    dax_conversions: List[Dict[str, Any]],
    output_dir: str,
    migration_id: str,
) -> str:
    """Export all DAX measures to a .dax file."""
    lines = [
        "// ================================================================",
        "// DAX Measures — Migrated from ThoughtSpot",
        f"// Migration ID: {migration_id}",
        "// ================================================================",
        "",
    ]

    for conv in dax_conversions:
        original = conv.get("original_formula", "")
        confidence = conv.get("confidence", 0)
        pattern = conv.get("pattern", "")
        notes = conv.get("notes", [])

        lines.append(f"// ── {conv.get('measure_name', '')} ──────────────────────────────────────")
        lines.append(f"// ThoughtSpot: {original}")
        lines.append(f"// Confidence: {confidence:.0%}  Pattern: {pattern}")
        if notes:
            for note in (notes if isinstance(notes, list) else [notes]):
                lines.append(f"// Note: {note}")
        lines.append(conv.get("dax_formula", ""))
        lines.append("")

    content = "\n".join(lines)
    output_path = Path(output_dir) / f"{migration_id}_measures.dax"
    output_path.write_text(content, encoding="utf-8")
    logger.info(f"DAX file saved: {output_path}")
    return str(output_path)
