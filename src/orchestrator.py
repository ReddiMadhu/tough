"""
MigrationOrchestrator — main pipeline coordinator.

Pipeline:
  Phase 1 (0-15%):   Load & parse TML files
  Phase 2 (15-30%):  Build Logic Graph (dependency DAG)
  Phase 3 (30-55%):  Convert formulas to DAX (topological order)
  Phase 4 (55-75%):  Generate PBIP project
  Phase 5 (75-85%):  Generate Excel + DAX + JSON exports
  Phase 6 (85-95%):  Package outputs as ZIP
  Phase 7 (95-100%): Finalize
"""
import uuid
import time
import json
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
from storage.migration_store import (
    update_migration_status,
    save_conversions,
    update_migration_progress,
    save_calculations_batch,
    save_logic_graph,
    update_migration_counts,
)


class MigrationOrchestrator:
    """Orchestrates the full ThoughtSpot → Power BI migration pipeline."""

    def __init__(self, db_path: str, export_dir: str):
        self.db_path = db_path
        self.export_dir = export_dir
        self.loader = SpotAppLoader()
        self.parser = TMLParser()

    def execute(self, migration_id: str, file_paths: List[str], progress_callback=None):
        """Run the complete pipeline synchronously (called from background thread)."""
        start_time = time.time()
        logger.info(f"[{migration_id}] Starting migration pipeline")

        def _progress(stage: str, percent: int, message: str):
            """Report progress via callback and DB."""
            update_migration_progress(self.db_path, migration_id, percent, stage, message)
            if progress_callback:
                progress_callback.update(stage, percent, message)

        try:
            # ── Phase 1: Parse TML files ──────────────────────────────────────
            _progress("parsing", 5, "Parsing ThoughtSpot TML files...")
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
            _progress("parsing", 15, f"Parsed {table_count} tables, {len(formula_columns)} formulas")

            # ── Phase 2: Build Logic Graph ────────────────────────────────────
            _progress("building_graph", 18, "Building calculation dependency graph...")
            logger.info(f"[{migration_id}] Phase 2: Building logic graph...")
            graph_data = self._build_logic_graph(migration_id, intermediate_model, formula_columns)
            _progress("building_graph", 28, f"Built graph with {len(graph_data.get('nodes', []))} nodes")

            # ── Phase 3: Convert formulas to DAX ─────────────────────────────
            _progress("converting", 30, "Converting formulas to DAX...")
            logger.info(f"[{migration_id}] Phase 3: Converting formulas to DAX...")
            col_table_map = self._build_col_table_map(intermediate_model)
            default_table = (
                intermediate_model["tables"][0]["name"]
                if intermediate_model.get("tables")
                else "Table"
            )

            # Build column metadata dictionary to pass to formula converter
            column_metadata = {}
            for table in intermediate_model.get("tables", []):
                for col in table.get("column_details", []):
                    column_metadata[col.get("name", "")] = {
                        "column_type": col.get("column_type"),
                        "aggregation": col.get("aggregation"),
                        "data_type": col.get("data_type"),
                    }

            converter = ThoughtSpotFormulaConverter(
                table_name=default_table,
                column_table_map=col_table_map,
                column_metadata=column_metadata,
            )

            dax_conversions = []
            total_formulas = len(formula_columns)
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

                # Granular progress within conversion phase
                if total_formulas > 0:
                    conv_pct = 30 + int(((i + 1) / total_formulas) * 25)
                    _progress("converting", conv_pct, f"Converted {i + 1}/{total_formulas} formulas")

            logger.info(f"[{migration_id}] Converted {len(dax_conversions)} formulas")

            # ── Phase 3.5: Validate & Self-Heal Conversions ───────────────────
            _progress("validating", 50, "Validating DAX conversions and running self-healing agent...")
            logger.info(f"[{migration_id}] Phase 3.5: Validating conversions...")
            
            from src.validation.validation_engine import ValidationEngine
            from src.agents.self_healer import SelfHealingAgent
            from storage.fidelity_validation_store import save_validation_result, save_correction_attempt

            val_engine = ValidationEngine()
            healer = SelfHealingAgent(max_attempts=3)

            # Build schema context string for the self-healer
            schema_context_lines = []
            if default_table:
                schema_context_lines.append(f"Primary table: '{default_table}'")
            if col_table_map:
                schema_context_lines.append("Known column mappings:")
                for col, tbl in list(col_table_map.items())[:30]:
                    schema_context_lines.append(f"  - Column '{col}' is in table '{tbl}'")
            known_measures = [c["measure_name"] for c in dax_conversions]
            if known_measures:
                schema_context_lines.append("Known measure references:")
                for m in known_measures:
                    schema_context_lines.append(f"  - Measure: [{m}]")
            schema_str = "\n".join(schema_context_lines)

            for idx, conv in enumerate(dax_conversions):
                c_id = conv["conversion_id"]
                meas_name = conv["measure_name"]
                orig_f = conv["original_formula"]
                curr_dax = conv["dax_formula"]
                conf = conv["confidence"]

                # 1. Run validation
                val_res = val_engine.validate(c_id, orig_f, curr_dax, meas_name, conf, migration_id)
                save_validation_result(self.db_path, migration_id, c_id, val_res)

                # ── Temporary Debug Logging for Diagnostics (Initial validation) ──
                debug_log_paths = [
                    Path(self.export_dir) / migration_id / "dax_healing_debug.log",
                    Path(self.export_dir).resolve().parent / "dax_healing_debug.log"
                ]
                for p in debug_log_paths:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    with open(p, "a", encoding="utf-8") as debug_file:
                        debug_file.write(f"\n{'='*80}\n")
                        debug_file.write(f"MIGRATION ID                  : {migration_id}\n")
                        debug_file.write(f"MEASURE NAME                  : {meas_name}\n")
                        debug_file.write(f"ORIGINAL THOUGHTSPOT FORMULA  :\n{orig_f}\n\n")
                        debug_file.write(f"INITIAL TRANSLATED DAX        :\n{curr_dax}\n\n")
                        debug_file.write(f"INITIAL VALIDATION RESULT     :\n")
                        debug_file.write(f"  Passed                      : {val_res.get('overall_passed')}\n")
                        debug_file.write(f"  Pass Rate                   : {val_res.get('pass_rate')}\n")
                        debug_file.write(f"  Validation Discrepancies    :\n{json.dumps(val_res.get('test_slices', []), indent=2)}\n")
                        debug_file.write(f"{'='*80}\n")

                # 2. Self-healing loop if failed
                attempt_num = 1
                while not val_res.get("overall_passed") and attempt_num <= 3:
                    for p in debug_log_paths:
                        with open(p, "a", encoding="utf-8") as debug_file:
                            debug_file.write(f"\n{'='*80}\n")
                            debug_file.write(f"MIGRATION ID                  : {migration_id}\n")
                            debug_file.write(f"MEASURE NAME                  : {meas_name}\n")
                            debug_file.write(f"HEALING CYCLE                 : Attempt {attempt_num} / 3\n")
                            debug_file.write(f"INPUT FAILED DAX FORMULA      :\n{curr_dax}\n\n")
                            debug_file.write(f"INPUT VALIDATION FAILURES     :\n{json.dumps(val_res.get('test_slices', []), indent=2)}\n\n")

                    attempt = healer.correct_dax(
                        original_formula=orig_f,
                        failed_dax=curr_dax,
                        failures=val_res.get("test_slices", []),
                        attempt_number=attempt_num,
                        measure_name=meas_name,
                        schema_context=schema_str
                    )
                    save_correction_attempt(self.db_path, migration_id, c_id, attempt)

                    # Update and re-validate
                    curr_dax = attempt["corrected_dax"]
                    val_res = val_engine.validate(c_id, orig_f, curr_dax, meas_name, conf, migration_id)
                    save_validation_result(self.db_path, migration_id, c_id, val_res)

                    for p in debug_log_paths:
                        with open(p, "a", encoding="utf-8") as debug_file:
                            debug_file.write(f"HEALER LLM DIAGNOSIS          :\n")
                            debug_file.write(f"  Root Cause   : {attempt.get('root_cause')}\n")
                            debug_file.write(f"  Explanation  : {attempt.get('explanation')}\n")
                            debug_file.write(f"  Changes Made : {attempt.get('changes_made')}\n\n")
                            debug_file.write(f"OUTPUT HEALED DAX FORMULA     :\n{curr_dax}\n\n")
                            debug_file.write(f"POST-HEALING VALIDATION STATE :\n")
                            debug_file.write(f"  Passed       : {val_res.get('overall_passed')}\n")
                            debug_file.write(f"  Pass Rate    : {val_res.get('pass_rate')}\n")
                            debug_file.write(f"  Failures Left: {json.dumps(val_res.get('test_slices', []), indent=2)}\n")
                            debug_file.write(f"{'='*80}\n")

                    attempt_num += 1

                # Update conversion list
                conv["dax_formula"] = curr_dax
                if val_res.get("overall_passed"):
                    conv["confidence"] = 1.0
                    conv["requires_review"] = False
                else:
                    conv["confidence"] = min(conv["confidence"], 0.5)
                    conv["requires_review"] = True
                    if "Self-healing could not fully resolve validation discrepancies. Manual review required." not in conv["notes"]:
                        conv["notes"].append("Self-healing could not fully resolve validation discrepancies. Manual review required.")

            logger.info(f"[{migration_id}] Completed validation and self-healing")

            # ── Phase 4: Generate PBIP ────────────────────────────────────────
            _progress("generating_pbip", 65, "Generating Power BI project...")
            logger.info(f"[{migration_id}] Phase 4: Generating PBIP project...")
            export_path = Path(self.export_dir) / migration_id
            export_path.mkdir(parents=True, exist_ok=True)

            project_name = self._derive_project_name(intermediate_model, file_paths)
            pbip_gen = PBIPGenerator(project_name, str(export_path / "pbip"))
            pbip_path = pbip_gen.generate(intermediate_model, dax_conversions)

            # ── Phase 4.5: Model Enhancement Detection ───────────────────────
            _progress("enhancing", 70, "Detecting required Power BI model enhancements...")
            logger.info(f"[{migration_id}] Phase 4.5: Running model enhancement agent...")
            
            from src.powerbi.model_enhancement_agent import ModelEnhancementAgent
            from src.powerbi.enhancement_guide_generator import EnhancementGuideGenerator
            from storage.fidelity_validation_store import save_model_enhancement, clear_model_enhancements

            clear_model_enhancements(self.db_path, migration_id)
            
            enh_agent = ModelEnhancementAgent()
            enhancements = []
            
            for conv in dax_conversions:
                orig_f = conv["original_formula"]
                curr_d = conv["dax_formula"]
                name = conv["measure_name"]
                
                enh = enh_agent.assess(orig_f, curr_d, name, default_table)
                if enh:
                    save_model_enhancement(self.db_path, migration_id, enh)
                    enhancements.append(enh)

            guide_gen = EnhancementGuideGenerator()
            guide_file_path = guide_gen.generate_guide(enhancements, export_path)
            guide_path_str = str(guide_file_path) if guide_file_path else None
            logger.info(f"[{migration_id}] Detected {len(enhancements)} model enhancements")

            # ── Phase 5: Generate exports ─────────────────────────────────────
            _progress("exporting", 75, "Generating Excel + DAX + JSON exports...")
            logger.info(f"[{migration_id}] Phase 5: Generating Excel + DAX + JSON...")
            
            # AI Narrative Summary removed (LLM cost saving)
            narrative_summary = None

            excel_gen = ExcelReportGenerator()
            excel_path = excel_gen.generate(
                intermediate_model=intermediate_model,
                dax_conversions=dax_conversions,
                output_dir=str(export_path),
                migration_id=migration_id,
            )

            dax_path = export_dax_file(dax_conversions, str(export_path), migration_id)
            json_path = export_json_model(intermediate_model, str(export_path), migration_id)

            # ── Phase 6: Package ──────────────────────────────────────────────
            _progress("packaging", 88, "Packaging migration outputs...")
            logger.info(f"[{migration_id}] Phase 6: Packaging outputs...")
            zip_path = package_outputs(
                export_dir=str(export_path),
                migration_id=migration_id,
                pbip_dir=str(pbip_path),
                excel_path=excel_path,
                dax_path=dax_path,
                json_path=json_path,
                guide_path=guide_path_str,
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

            _progress("completed", 100, f"Migration complete in {round(elapsed, 1)}s")
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

    def _build_logic_graph(
        self,
        migration_id: str,
        model: Dict[str, Any],
        formula_columns: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build dependency graph and save calculations & visualization data to database."""
        from src.thoughtspot.logic_graph_builder import LogicGraphBuilder
        
        # Build base field metadata
        base_field_metadata = {}
        for table in model.get("tables", []):
            table_name = table.get("name", "")
            for col in table.get("column_details", []):
                col_name = col.get("name", "")
                base_field_metadata[col_name] = {
                    "type": col.get("data_type", "VARCHAR"),
                    "generic_type": "NUMERIC" if col.get("column_type") == "MEASURE" else "TEXT",
                    "table": table_name
                }
                
        builder = LogicGraphBuilder()
        builder.build_graph(model, base_field_metadata)
        
        # Save calculations to DB
        calcs_dict = builder.to_dict()
        save_calculations_batch(self.db_path, migration_id, calcs_dict.get("nodes", []))
        
        # Save logic graph JSON (for ReactFlow visualization)
        reactflow_data = builder.export_for_reactflow()
        save_logic_graph(self.db_path, migration_id, json.dumps(reactflow_data))
        
        # Also update workbook count, calculation count, relationship count
        update_migration_counts(
            db_path=self.db_path,
            migration_id=migration_id,
            workbook_count=len(model.get("worksheets", [])),
            calculation_count=len(formula_columns),
            relationship_count=len(model.get("joins", []))
        )
        
        return reactflow_data
