"""
MigrationOrchestrator — main pipeline coordinator.

Pipeline:
  Phase 1 (0-20%):   Load & parse TML files
  Phase 2 (20-60%):  Convert formulas to DAX
  Phase 3 (60-80%):  Generate PBIP project
  Phase 4 (80-90%):  Generate Excel + DAX + JSON exports
  Phase 5 (90-100%): Package outputs as ZIP
"""
import uuid
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from loguru import logger

from src.thoughtspot.spotapp_loader import SpotAppLoader
from src.thoughtspot.tml_parser import TMLParser
from src.thoughtspot.formula_converter import ThoughtSpotFormulaConverter
from src.powerbi.pbip_generator import PBIPGenerator
from src.export.excel_report import ExcelReportGenerator
from src.export.dax_exporter import export_dax_file
from src.export.json_exporter import export_json_model
from src.export.zip_packager import package_outputs, package_pbip_only
from storage.migration_store import update_migration_status, save_conversions


class MigrationOrchestrator:
    """Orchestrates the full ThoughtSpot → Power BI migration pipeline."""

    def __init__(self, db_path: str, export_dir: str):
        self.db_path = db_path
        self.export_dir = export_dir
        self.loader = SpotAppLoader()
        self.parser = TMLParser()

    def execute(self, migration_id: str, file_paths: List[str]):
        """Run the complete pipeline synchronously (called from background thread)."""
        start_time = time.time()
        logger.info(f"[{migration_id}] Starting migration pipeline")

        try:
            # ── Phase 1: Parse ────────────────────────────────────────────────
            logger.info(f"[{migration_id}] Phase 1: Parsing TML files...")
            spotapp_data = self.loader.load_files(file_paths)
            intermediate_model = self.parser.parse_all(spotapp_data)

            table_count = len(intermediate_model.get("tables", []))
            formula_columns = [
                c for c in intermediate_model.get("columns", []) if c.get("formula")
            ]
            viz_count = len(intermediate_model.get("worksheets", []))
            join_count = len(intermediate_model.get("joins", []))

            logger.info(
                f"[{migration_id}] Parsed: {table_count} tables, "
                f"{len(formula_columns)} formulas, {viz_count} viz, {join_count} joins"
            )

            # ── Phase 2: Convert formulas to DAX ─────────────────────────────
            logger.info(f"[{migration_id}] Phase 2: Converting formulas to DAX...")
            col_table_map = self._build_col_table_map(intermediate_model)
            default_table = (
                intermediate_model["tables"][0]["name"]
                if intermediate_model.get("tables")
                else "Table"
            )

            converter = ThoughtSpotFormulaConverter(
                table_name=default_table,
                column_table_map=col_table_map,
            )

            dax_conversions = []
            for i, col in enumerate(formula_columns):
                measure_name = col.get("caption") or col.get("internal_name") or f"Measure_{i}"
                result = converter.convert(col["formula"], measure_name)

                dax_conversions.append({
                    "conversion_id": f"conv_{uuid.uuid4().hex[:8]}",
                    "measure_name": measure_name,
                    "original_formula": col["formula"],
                    "dax_formula": result.dax_formula,
                    "confidence": result.confidence,
                    "pattern": result.pattern,
                    "notes": result.notes,
                    "requires_review": result.requires_review,
                    "format_pattern": col.get("format", ""),
                    "source_object": col.get("source_object", ""),
                    "source_object_type": col.get("source_object_type", ""),
                })

            logger.info(f"[{migration_id}] Converted {len(dax_conversions)} formulas")

            # ── Phase 3: Generate PBIP ────────────────────────────────────────
            logger.info(f"[{migration_id}] Phase 3: Generating PBIP project...")
            export_path = Path(self.export_dir) / migration_id
            export_path.mkdir(parents=True, exist_ok=True)

            project_name = self._derive_project_name(intermediate_model, file_paths)
            pbip_gen = PBIPGenerator(project_name, str(export_path / "pbip"))
            pbip_path = pbip_gen.generate(intermediate_model, dax_conversions)

            # ── Phase 4: Generate exports ─────────────────────────────────────
            logger.info(f"[{migration_id}] Phase 4: Generating Excel + DAX + JSON...")
            
            # Generate AI Narrative Summary if LLM is enabled
            narrative_summary = None
            try:
                from src.llm_reasoner import LLMReasoner
                llm = LLMReasoner()
                if llm.llm:
                    logger.info(f"[{migration_id}] Generating AI Executive Narrative...")
                    narrative_summary = llm.generate_model_narrative(
                        tables=intermediate_model.get("tables", []),
                        relationships=intermediate_model.get("joins", []),
                        conversions=dax_conversions,
                    )
            except Exception as e:
                logger.error(f"[{migration_id}] AI Narrative Generation skipped: {e}")

            if narrative_summary:
                intermediate_model["narrative_summary"] = narrative_summary

            excel_gen = ExcelReportGenerator()
            excel_path = excel_gen.generate(
                intermediate_model=intermediate_model,
                dax_conversions=dax_conversions,
                output_dir=str(export_path),
                migration_id=migration_id,
            )

            dax_path = export_dax_file(dax_conversions, str(export_path), migration_id)
            json_path = export_json_model(intermediate_model, str(export_path), migration_id)

            # ── Phase 5: Package ──────────────────────────────────────────────
            logger.info(f"[{migration_id}] Phase 5: Packaging outputs...")
            zip_path = package_outputs(
                export_dir=str(export_path),
                migration_id=migration_id,
                pbip_dir=str(pbip_path),
                excel_path=excel_path,
                dax_path=dax_path,
                json_path=json_path,
            )

            # PBIP-only zip
            package_pbip_only(str(pbip_path), str(export_path), migration_id)

            elapsed = time.time() - start_time

            # ── Save conversions to DB ────────────────────────────────────────
            save_conversions(self.db_path, migration_id, dax_conversions)

            # ── Update status ─────────────────────────────────────────────────
            high_conf = sum(1 for c in dax_conversions if c["confidence"] >= 0.9)
            medium_conf = sum(1 for c in dax_conversions if 0.6 <= c["confidence"] < 0.9)
            low_conf = sum(1 for c in dax_conversions if c["confidence"] < 0.6)
            review_count = sum(1 for c in dax_conversions if c["requires_review"])

            update_migration_status(
                db_path=self.db_path,
                migration_id=migration_id,
                status="completed",
                stats={
                    "tables": table_count,
                    "formulas_converted": len(dax_conversions),
                    "high_confidence": high_conf,
                    "medium_confidence": medium_conf,
                    "low_confidence": low_conf,
                    "requires_review": review_count,
                },
                elapsed_seconds=round(elapsed, 1),
                narrative_summary=narrative_summary,
            )


            logger.info(f"[{migration_id}] ✅ Migration complete in {elapsed:.1f}s")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[{migration_id}] ❌ Migration failed: {e}", exc_info=True)
            update_migration_status(
                db_path=self.db_path,
                migration_id=migration_id,
                status="failed",
                error_message=str(e),
                elapsed_seconds=round(elapsed, 1),
            )
            raise

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_col_table_map(self, model: Dict[str, Any]) -> Dict[str, str]:
        """Map column names to their source table names."""
        col_map: Dict[str, str] = {}
        for table in model.get("tables", []):
            table_name = table.get("name", "")
            for col in table.get("column_details", []):
                col_map[col.get("name", "")] = table_name
            for col_name in table.get("columns", []):
                if col_name not in col_map:
                    col_map[col_name] = table_name
        return col_map

    def _derive_project_name(self, model: Dict, file_paths: List[str]) -> str:
        """Derive a clean project name from the model or file names."""
        for ws in model.get("worksheets", []):
            lb = ws.get("source_liveboard")
            if lb:
                return lb.replace(" ", "_")
        if file_paths:
            return Path(file_paths[0]).stem.replace(" ", "_")
        return "ThoughtSpot_Migration"
