"""
Agent Executor — 4 decentralized agent classes for the migration pipeline.

Agent 1: SourceAnalysisAgent   — Parse TML files, extract metadata
Agent 2: DataModelAgent        — Build logic graph, detect model enhancements
Agent 3: DaxConversionAgent    — Convert formulas to DAX, validate, self-heal
Agent 4: ExportAgent           — Generate PBIP, exports, package ZIP
"""
import uuid
import time
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger

from src.agents.agent_event_emitter import AgentEventEmitter


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 1: Source Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class SourceAnalysisAgent:
    """Parse TML files, extract comprehensive workbook metadata."""

    AGENT_NAME = "source_analysis"

    def __init__(self, db_path: str, export_dir: str):
        self.db_path = db_path
        self.export_dir = export_dir

    def run(self, migration_id: str, file_paths: List[str], emitter: AgentEventEmitter) -> Dict[str, Any]:
        """Execute source analysis: parse TML → extract metadata → persist model."""
        start = time.time()
        logger.info(f"[{migration_id}] SourceAnalysisAgent starting...")

        try:
            from src.thoughtspot.spotapp_loader import SpotAppLoader
            from src.thoughtspot.tml_parser import TMLParser
            from storage.migration_store import update_migration_progress

            emitter.emit("parsing_started", sub_phase="Loading TML files", progress=5,
                         message="Loading uploaded TML/ZIP files...")

            # Load files
            loader = SpotAppLoader()
            spotapp_data = loader.load_files(file_paths)

            emitter.emit("file_parsed", sub_phase="Parsing TML structure", progress=20,
                         data={"file_count": len(file_paths)},
                         message=f"Loaded {len(file_paths)} file(s)")

            # Parse all TML into intermediate model
            parser = TMLParser()
            intermediate_model = parser.parse_all(spotapp_data)

            table_count = len(intermediate_model.get("tables", []))
            formula_columns = [c for c in intermediate_model.get("columns", []) if c.get("formula")]
            viz_count = len(intermediate_model.get("worksheets", []))
            join_count = len(intermediate_model.get("joins", []))

            # Emit per-table events
            for i, table in enumerate(intermediate_model.get("tables", [])):
                col_count = len(table.get("column_details", []))
                emitter.emit("table_extracted", sub_phase="Extracting tables", progress=20 + int((i + 1) / max(table_count, 1) * 20),
                             data={"table_name": table.get("name", ""), "column_count": col_count},
                             message=f"Table: {table.get('name', '')} ({col_count} columns)")

            # Emit per-worksheet events
            for i, ws in enumerate(intermediate_model.get("worksheets", [])):
                emitter.emit("worksheet_extracted", sub_phase="Extracting visuals", progress=40 + int((i + 1) / max(viz_count, 1) * 20),
                             data={"worksheet_name": ws.get("name", ""), "chart_type": ws.get("ts_chart_type", "")},
                             message=f"Visual: {ws.get('name', '')}")

            # Emit formula count
            for i, fc in enumerate(formula_columns):
                name = fc.get("caption") or fc.get("internal_name") or f"Formula_{i}"
                emitter.emit("formula_found", sub_phase="Cataloging formulas", progress=60 + int((i + 1) / max(len(formula_columns), 1) * 20),
                             data={"formula_name": name},
                             message=f"Formula: {name}")

            # Persist intermediate model to disk for downstream agents
            export_path = Path(self.export_dir) / migration_id
            export_path.mkdir(parents=True, exist_ok=True)
            model_file = export_path / f"{migration_id}_intermediate_model.json"
            with open(model_file, "w", encoding="utf-8") as f:
                json.dump(intermediate_model, f, indent=2, default=str)

            emitter.emit("metadata_ready", sub_phase="Finalizing metadata", progress=90,
                         data={
                             "tables": table_count,
                             "formulas": len(formula_columns),
                             "visuals": viz_count,
                             "joins": join_count,
                         },
                         message=f"Metadata ready: {table_count} tables, {len(formula_columns)} formulas, {viz_count} visuals")

            # Update DB progress
            update_migration_progress(self.db_path, migration_id, 15, "parsing", "Source analysis complete")

            elapsed = time.time() - start
            summary = {
                "tables": table_count,
                "formulas": len(formula_columns),
                "visuals": viz_count,
                "joins": join_count,
                "elapsed_seconds": round(elapsed, 1),
            }
            emitter.complete(summary, f"Source analysis complete in {round(elapsed, 1)}s")

            logger.info(f"[{migration_id}] SourceAnalysisAgent completed in {elapsed:.1f}s")
            return summary

        except Exception as e:
            logger.error(f"[{migration_id}] SourceAnalysisAgent failed: {e}", exc_info=True)
            emitter.fail(str(e))
            raise


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 2: Data Model
# ═══════════════════════════════════════════════════════════════════════════════

class DataModelAgent:
    """Build logic graph (dependency DAG) and detect model enhancements."""

    AGENT_NAME = "data_model"

    def __init__(self, db_path: str, export_dir: str):
        self.db_path = db_path
        self.export_dir = export_dir

    def _load_intermediate_model(self, migration_id: str) -> Dict[str, Any]:
        """Load persisted intermediate model from Agent 1."""
        model_file = Path(self.export_dir) / migration_id / f"{migration_id}_intermediate_model.json"
        if not model_file.exists():
            # Fallback to legacy name
            model_file = Path(self.export_dir) / migration_id / f"model_{migration_id}.json"
        if not model_file.exists():
            raise FileNotFoundError(f"Intermediate model not found for {migration_id}")
        with open(model_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def run(self, migration_id: str, emitter: AgentEventEmitter) -> Dict[str, Any]:
        """Execute data model agent: build graph + detect enhancements."""
        start = time.time()
        logger.info(f"[{migration_id}] DataModelAgent starting...")

        try:
            from src.thoughtspot.logic_graph_builder import LogicGraphBuilder
            from src.powerbi.model_enhancement_agent import ModelEnhancementAgent
            from storage.migration_store import (
                save_calculations_batch, save_logic_graph, update_migration_counts, update_migration_progress
            )
            from storage.fidelity_validation_store import save_model_enhancement, clear_model_enhancements

            emitter.emit("graph_building", sub_phase="Loading parsed model", progress=5,
                         message="Loading intermediate model from source analysis...")

            model = self._load_intermediate_model(migration_id)
            formula_columns = [c for c in model.get("columns", []) if c.get("formula")]

            emitter.emit("graph_building", sub_phase="Building dependency graph", progress=15,
                         message="Constructing calculation dependency graph...")

            # Build base field metadata
            base_field_metadata = {}
            for table in model.get("tables", []):
                table_name = table.get("name", "")
                for col in table.get("column_details", []):
                    col_name = col.get("name", "")
                    base_field_metadata[col_name] = {
                        "type": col.get("data_type", "VARCHAR"),
                        "generic_type": "NUMERIC" if col.get("column_type") == "MEASURE" else "TEXT",
                        "table": table_name,
                    }

            builder = LogicGraphBuilder()
            builder.build_graph(model, base_field_metadata)

            # Save calculations
            calcs_dict = builder.to_dict()
            nodes = calcs_dict.get("nodes", [])
            save_calculations_batch(self.db_path, migration_id, nodes)

            # Emit node events
            for i, node in enumerate(nodes):
                emitter.emit("node_added", sub_phase="Building graph nodes", progress=15 + int((i + 1) / max(len(nodes), 1) * 25),
                             data={"node_name": node.get("calc_name", ""), "node_type": node.get("calc_type", "")},
                             message=f"Node: {node.get('calc_name', '')}")

            # Export ReactFlow data
            reactflow_data = builder.export_for_reactflow()
            save_logic_graph(self.db_path, migration_id, json.dumps(reactflow_data))

            edges = reactflow_data.get("edges", [])
            for i, edge in enumerate(edges[:20]):  # Cap at 20 edge events
                emitter.emit("edge_added", sub_phase="Building graph edges", progress=40 + int((i + 1) / max(len(edges[:20]), 1) * 10),
                             data={"source": edge.get("source", ""), "target": edge.get("target", "")},
                             message=f"Edge: {edge.get('source', '')} → {edge.get('target', '')}")

            # Emit relationship events
            joins = model.get("joins", [])
            for i, join in enumerate(joins):
                left_table = join.get("left_table", "")
                right_table = join.get("right_table", "")
                cardinality = join.get("cardinality", "MANY_TO_ONE").upper().replace("-", "_")
                msg = f'Table "{left_table}" and "{right_table}" are joined with "key" key ({cardinality} relationship)'
                emitter.emit("relationship_extracted", sub_phase="Extracting relationships", progress=50 + int((i + 1) / max(len(joins), 1) * 5),
                             data={"left_table": left_table, "right_table": right_table, "cardinality": cardinality},
                             message=msg)

            emitter.emit("graph_complete", sub_phase="Graph complete", progress=55,
                         data={"nodes": len(nodes), "edges": len(edges)},
                         message=f"Graph built: {len(nodes)} nodes, {len(edges)} edges")

            # Update counts
            update_migration_counts(
                db_path=self.db_path,
                migration_id=migration_id,
                workbook_count=len(model.get("worksheets", [])),
                calculation_count=len(formula_columns),
                relationship_count=len(model.get("joins", [])),
            )

            # ── Model Enhancement Detection ──
            emitter.emit("enhancement_detecting", sub_phase="Detecting model enhancements", progress=60,
                         message="Scanning formulas for required Power BI model enhancements...")

            clear_model_enhancements(self.db_path, migration_id)
            enh_agent = ModelEnhancementAgent()
            enhancements = []

            default_table = model["tables"][0]["name"] if model.get("tables") else "Table"

            for i, fc in enumerate(formula_columns):
                orig_f = fc.get("formula", "")
                name = fc.get("caption") or fc.get("internal_name") or f"Measure_{i}"
                # Use empty dax for detection at this stage
                enh = enh_agent.assess(orig_f, "", name, default_table)
                if enh:
                    save_model_enhancement(self.db_path, migration_id, enh)
                    enhancements.append(enh)
                    emitter.emit("enhancement_detected", sub_phase="Enhancement detected", progress=60 + int((i + 1) / max(len(formula_columns), 1) * 30),
                                 data={"enhancement_type": enh.get("enhancement_type", ""), "measure": name},
                                 message=f"Enhancement needed: {enh.get('enhancement_type', '')} for {name}")

            emitter.emit("enhancement_complete", sub_phase="Enhancements cataloged", progress=95,
                         data={"enhancement_count": len(enhancements)},
                         message=f"Detected {len(enhancements)} model enhancements")

            update_migration_progress(self.db_path, migration_id, 30, "building_graph", "Data model analysis complete")

            elapsed = time.time() - start
            summary = {
                "nodes": len(nodes),
                "edges": len(edges),
                "enhancements": len(enhancements),
                "elapsed_seconds": round(elapsed, 1),
            }
            emitter.complete(summary, f"Data model analysis complete in {round(elapsed, 1)}s")

            logger.info(f"[{migration_id}] DataModelAgent completed in {elapsed:.1f}s")
            return summary

        except Exception as e:
            logger.error(f"[{migration_id}] DataModelAgent failed: {e}", exc_info=True)
            emitter.fail(str(e))
            raise


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 3: DAX Conversion
# ═══════════════════════════════════════════════════════════════════════════════

class DaxConversionAgent:
    """Convert ThoughtSpot formulas to DAX, validate, and self-heal."""

    AGENT_NAME = "dax_conversion"

    def __init__(self, db_path: str, export_dir: str):
        self.db_path = db_path
        self.export_dir = export_dir

    def _load_intermediate_model(self, migration_id: str) -> Dict[str, Any]:
        model_file = Path(self.export_dir) / migration_id / f"{migration_id}_intermediate_model.json"
        if not model_file.exists():
            model_file = Path(self.export_dir) / migration_id / f"model_{migration_id}.json"
        if not model_file.exists():
            raise FileNotFoundError(f"Intermediate model not found for {migration_id}")
        with open(model_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def run(self, migration_id: str, emitter: AgentEventEmitter) -> Dict[str, Any]:
        """Execute DAX conversion using LangGraph pipeline + validation + self-healing."""
        start = time.time()
        logger.info(f"[{migration_id}] DaxConversionAgent starting (LangGraph pipeline)...")

        try:
            from src.thoughtspot.formula_converter import ThoughtSpotFormulaConverter
            from src.validation.validation_engine import ValidationEngine
            from src.agents.self_healer import SelfHealingAgent
            from src.agents.dax_pipeline import build_dax_pipeline, make_initial_state
            from storage.migration_store import save_conversions, update_migration_progress
            from storage.fidelity_validation_store import save_validation_result, save_correction_attempt

            model = self._load_intermediate_model(migration_id)
            formula_columns = [c for c in model.get("columns", []) if c.get("formula")]
            total_formulas = len(formula_columns)

            emitter.emit("conversion_started", sub_phase="Preparing conversion engine", progress=5,
                         data={"total_formulas": total_formulas},
                         message=f"Starting DAX conversion for {total_formulas} formulas...")

            # ── Build column-table map ──
            col_table_map = {}
            table_columns = {}
            for table in model.get("tables", []):
                table_name = table.get("name", "")
                cols = set()
                for col in table.get("column_details", []):
                    col_name = col.get("name", "")
                    cols.add(col_name)
                    if col_name not in col_table_map:
                        col_table_map[col_name] = table_name
                for col_name in table.get("columns", []):
                    cols.add(col_name)
                    if col_name not in col_table_map:
                        col_table_map[col_name] = table_name
                table_columns[table_name] = list(cols)

            default_table = model["tables"][0]["name"] if model.get("tables") else "Table"

            # ── Build column metadata ──
            column_metadata = {}
            for table in model.get("tables", []):
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

            # ── Dependency ordering: sort formulas by dependency_level ──
            dep_level_map = {}
            cyclic_formulas = set()
            try:
                from src.thoughtspot.logic_graph_builder import LogicGraphBuilder
                builder = LogicGraphBuilder()
                base_field_metadata = {}
                for table in model.get("tables", []):
                    t_name = table.get("name", "")
                    for col in table.get("column_details", []):
                        base_field_metadata[col.get("name", "")] = {
                            "type": col.get("data_type", "VARCHAR"),
                            "generic_type": "NUMERIC" if col.get("column_type") == "MEASURE" else "TEXT",
                            "table": t_name,
                        }
                builder.build_graph(model, base_field_metadata)

                # Extract dependency levels
                for name, node in builder.calculations.items():
                    dep_level_map[name] = node.dependency_level

                # Detect cycles: formulas not visited by Kahn's algorithm
                calcs_dict = builder.to_dict()
                visited_count = calcs_dict["stats"]["total_calculations"]
                if visited_count < len(builder.calculations):
                    logger.warning(f"[{migration_id}] Circular dependency detected in formula graph")
                    # Formulas with no level assigned are in cycles
                    all_calc_names = set(builder.calculations.keys())
                    for name, node in builder.calculations.items():
                        # Cycle detection: check if in-degree is still > 0 after topo sort
                        if name not in dep_level_map:
                            cyclic_formulas.add(name)
            except Exception as e:
                logger.warning(f"[{migration_id}] Could not build dependency order: {e}")

            # Sort formula_columns by dependency level (level 1 first, unknown last)
            def get_dep_level(col):
                name = col.get("caption") or col.get("internal_name") or ""
                return dep_level_map.get(name, 999)

            formula_columns.sort(key=get_dep_level)

            # ── Build known measures set (all formula names, available upfront) ──
            known_measures = set()
            for col in formula_columns:
                name = col.get("caption") or col.get("internal_name") or ""
                if name:
                    known_measures.add(name)

            # ── Build schema context string for healer ──
            schema_context_lines = [f"Primary table: '{default_table}'"]
            if col_table_map:
                schema_context_lines.append("Known column mappings:")
                for col_name, tbl in col_table_map.items():
                    schema_context_lines.append(f"  - Column '{col_name}' is in table '{tbl}'")
            if known_measures:
                schema_context_lines.append("Known measure references:")
                for m in known_measures:
                    schema_context_lines.append(f"  - Measure: [{m}]")
            schema_str = "\n".join(schema_context_lines)

            # ── Initialize pipeline tools ──
            val_engine = ValidationEngine()
            healer = SelfHealingAgent(max_attempts=3)
            pipeline = build_dax_pipeline()

            # ── Process each formula through the LangGraph pipeline ──
            dax_conversions = []
            healed_count = 0
            failed_count = 0

            for i, col in enumerate(formula_columns):
                measure_name = col.get("caption") or col.get("internal_name") or f"Measure_{i}"

                # Check for circular dependencies — skip immediately
                if measure_name in cyclic_formulas:
                    logger.warning(f"[{migration_id}] Skipping cyclic formula: {measure_name}")
                    emitter.emit("formula_circular", sub_phase="DAX Conversion",
                                 progress=5 + int((i + 1) / max(total_formulas, 1) * 85),
                                 data={"formula_name": measure_name, "status": "circular_dependency"},
                                 message=f"⚠ Circular dependency: {measure_name}")
                    conv = {
                        "conversion_id": f"conv_{uuid.uuid4().hex[:8]}",
                        "measure_name": measure_name,
                        "original_formula": col["formula"],
                        "dax_formula": f"-- {measure_name}: Circular dependency detected\n{measure_name} = BLANK()  -- TODO: Break circular reference",
                        "confidence": 0.0,
                        "pattern": "CIRCULAR_DEPENDENCY",
                        "notes": ["Circular dependency detected in calculation graph — manual resolution required"],
                        "requires_review": True,
                        "format_pattern": col.get("format", ""),
                        "source_object": col.get("source_object", ""),
                        "source_object_type": col.get("source_object_type", ""),
                    }
                    dax_conversions.append(conv)
                    failed_count += 1
                    continue

                # Build initial state for this formula
                initial_state = make_initial_state(
                    formula_name=measure_name,
                    original_ts=col["formula"],
                    formula_index=i,
                    total_formulas=total_formulas,
                    max_attempts=3,
                )

                # Build config with shared context
                pipeline_config = {
                    "configurable": {
                        "emitter": emitter,
                        "converter": converter,
                        "val_engine": val_engine,
                        "healer": healer,
                        "col_table_map": col_table_map,
                        "column_metadata": column_metadata,
                        "known_measures": known_measures,
                        "schema_context": schema_str,
                        "migration_id": migration_id,
                        "table_columns": table_columns,
                    }
                }

                # Run the LangGraph pipeline for this formula
                try:
                    final_state = pipeline.invoke(initial_state, config=pipeline_config)
                except Exception as e:
                    logger.error(f"[{migration_id}] Pipeline failed for {measure_name}: {e}")
                    final_state = {
                        "translated_dax": f"{measure_name} = BLANK()  -- Pipeline error: {str(e)[:100]}",
                        "translation_confidence": 0.0,
                        "translation_pattern": "ERROR",
                        "translation_notes": [f"Pipeline error: {str(e)}"],
                        "requires_review": True,
                        "final_status": "failed",
                        "healing_attempts": [],
                        "semantic_result": None,
                    }

                # Extract results from final state
                final_dax = final_state.get("translated_dax", f"{measure_name} = BLANK()")
                final_confidence = final_state.get("translation_confidence", 0.0)
                final_status = final_state.get("final_status", "")
                healing_attempts = final_state.get("healing_attempts", [])
                semantic_result = final_state.get("semantic_result")

                # Determine final status
                if final_status == "passed" or (final_state.get("semantic_passed") or final_state.get("syntax_passed") and final_state.get("schema_passed")):
                    if healing_attempts:
                        healed_count += 1
                        final_confidence = max(final_confidence, 0.85)
                    else:
                        final_confidence = max(final_confidence, 0.90)
                    requires_review = False
                else:
                    final_confidence = min(final_confidence, 0.5)
                    requires_review = True
                    failed_count += 1

                # Save validation result if available
                conv_id = f"conv_{uuid.uuid4().hex[:8]}"
                if semantic_result:
                    save_validation_result(self.db_path, migration_id, conv_id, semantic_result)

                # Save healing attempts
                for attempt in healing_attempts:
                    save_correction_attempt(self.db_path, migration_id, conv_id, attempt)

                # Build conversion record
                notes = list(final_state.get("translation_notes", []))
                if healing_attempts:
                    notes.append(f"Auto-fixed after {len(healing_attempts)} attempt(s)")
                if final_status == "failed" and healing_attempts:
                    notes.append("Auto-Fix could not fully resolve validation issues. Manual review required.")

                conv = {
                    "conversion_id": conv_id,
                    "measure_name": measure_name,
                    "original_formula": col["formula"],
                    "dax_formula": final_dax,
                    "confidence": final_confidence,
                    "pattern": final_state.get("translation_pattern", "UNKNOWN"),
                    "notes": notes,
                    "requires_review": requires_review,
                    "format_pattern": col.get("format", ""),
                    "source_object": col.get("source_object", ""),
                    "source_object_type": col.get("source_object_type", ""),
                }
                dax_conversions.append(conv)

                # Log to debug file
                debug_log_path = Path(self.export_dir) / migration_id / "dax_healing_debug.log"
                debug_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_log_path, "a", encoding="utf-8") as debug_file:
                    debug_file.write(f"\n{'='*80}\n")
                    debug_file.write(f"MEASURE: {measure_name} | STATUS: {final_status}\n")
                    debug_file.write(f"ORIGINAL: {col['formula']}\n")
                    debug_file.write(f"FINAL DAX: {final_dax}\n")
                    debug_file.write(f"CONFIDENCE: {final_confidence} | HEALED: {len(healing_attempts)} attempts\n")
                    debug_file.write(f"{'='*80}\n")

            # ── Save conversions to DB ──
            save_conversions(self.db_path, migration_id, dax_conversions)
            update_migration_progress(self.db_path, migration_id, 55, "converting", "DAX conversion complete")

            elapsed = time.time() - start
            high_conf = sum(1 for c in dax_conversions if c["confidence"] >= 0.9)
            summary = {
                "total_formulas": total_formulas,
                "high_confidence": high_conf,
                "healed": healed_count,
                "failed_validation": failed_count,
                "elapsed_seconds": round(elapsed, 1),
            }
            emitter.complete(summary, f"DAX conversion complete in {round(elapsed, 1)}s — {high_conf}/{total_formulas} high confidence")

            logger.info(f"[{migration_id}] DaxConversionAgent completed in {elapsed:.1f}s")
            return summary

        except Exception as e:
            logger.error(f"[{migration_id}] DaxConversionAgent failed: {e}", exc_info=True)
            emitter.fail(str(e))
            raise


# ═══════════════════════════════════════════════════════════════════════════════
# Agent 4: Export
# ═══════════════════════════════════════════════════════════════════════════════

class ExportAgent:
    """Generate PBIP, Excel/DAX/JSON exports, and package ZIP."""

    AGENT_NAME = "export"

    def __init__(self, db_path: str, export_dir: str):
        self.db_path = db_path
        self.export_dir = export_dir

    def _load_intermediate_model(self, migration_id: str) -> Dict[str, Any]:
        model_file = Path(self.export_dir) / migration_id / f"{migration_id}_intermediate_model.json"
        if not model_file.exists():
            model_file = Path(self.export_dir) / migration_id / f"model_{migration_id}.json"
        if not model_file.exists():
            raise FileNotFoundError(f"Intermediate model not found for {migration_id}")
        with open(model_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def run(self, migration_id: str, emitter: AgentEventEmitter) -> Dict[str, Any]:
        """Execute export: PBIP + Excel + DAX + JSON + ZIP packaging."""
        start = time.time()
        logger.info(f"[{migration_id}] ExportAgent starting...")

        try:
            from src.powerbi.pbip_generator import PBIPGenerator
            from src.export.excel_report import ExcelReportGenerator
            from src.export.dax_exporter import export_dax_file
            from src.export.json_exporter import export_json_model
            from src.export.zip_packager import package_outputs, package_pbip_only
            from src.powerbi.enhancement_guide_generator import EnhancementGuideGenerator
            from storage.migration_store import get_migration_conversions, update_migration_status, update_migration_progress
            from storage.fidelity_validation_store import get_model_enhancements

            model = self._load_intermediate_model(migration_id)
            export_path = Path(self.export_dir) / migration_id
            export_path.mkdir(parents=True, exist_ok=True)

            # Load conversions from DB (saved by DaxConversionAgent)
            dax_conversions = get_migration_conversions(self.db_path, migration_id)

            # ── PBIP Generation ──
            emitter.emit("pbip_generating", sub_phase="Generating PBIP project", progress=10,
                         message="Generating Power BI project structure...")

            file_paths = list((Path(self.export_dir).parent / "uploads" / migration_id).glob("*"))
            project_name = self._derive_project_name(model, [str(p) for p in file_paths])
            pbip_gen = PBIPGenerator(project_name, str(export_path / "pbip"))
            pbip_path = pbip_gen.generate(model, dax_conversions)

            emitter.emit("pbip_complete", sub_phase="PBIP project ready", progress=35,
                         data={"project_name": project_name},
                         message=f"PBIP project generated: {project_name}")

            # ── Enhancement Guide ──
            emitter.emit("enhancement_guide", sub_phase="Generating enhancement guide", progress=40,
                         message="Compiling model enhancement guide...")

            try:
                enhancements = get_model_enhancements(self.db_path, migration_id)
            except Exception:
                enhancements = []

            guide_gen = EnhancementGuideGenerator()
            guide_file_path = guide_gen.generate_guide(enhancements, export_path)
            guide_path_str = str(guide_file_path) if guide_file_path else None

            # ── Excel Report ──
            emitter.emit("excel_generating", sub_phase="Generating Excel report", progress=50,
                         message="Creating migration report spreadsheet...")

            excel_gen = ExcelReportGenerator()
            excel_path = excel_gen.generate(
                intermediate_model=model,
                dax_conversions=dax_conversions,
                output_dir=str(export_path),
                migration_id=migration_id,
            )

            emitter.emit("excel_complete", sub_phase="Excel ready", progress=65,
                         message="Migration report generated")

            # ── DAX File ──
            emitter.emit("dax_exporting", sub_phase="Exporting DAX file", progress=70,
                         message="Exporting DAX measures file...")

            dax_path = export_dax_file(dax_conversions, str(export_path), migration_id)

            # ── JSON Model ──
            emitter.emit("json_exporting", sub_phase="Exporting JSON model", progress=75,
                         message="Exporting intermediate JSON model...")

            json_path = export_json_model(model, str(export_path), migration_id)

            # ── ZIP Packaging ──
            emitter.emit("packaging", sub_phase="Packaging outputs", progress=80,
                         message="Creating ZIP archives...")

            zip_path = package_outputs(
                export_dir=str(export_path),
                migration_id=migration_id,
                pbip_dir=str(pbip_path),
                excel_path=excel_path,
                dax_path=dax_path,
                json_path=json_path,
                guide_path=guide_path_str,
            )
            package_pbip_only(str(pbip_path), str(export_path), migration_id)

            emitter.emit("packaging_complete", sub_phase="Packaging complete", progress=95,
                         message="All artifacts packaged successfully")

            # ── Update final migration status ──
            elapsed_total = time.time() - start
            high_conf = sum(1 for c in dax_conversions if c.get("confidence", 0) >= 0.9)
            medium_conf = sum(1 for c in dax_conversions if 0.6 <= c.get("confidence", 0) < 0.9)
            low_conf = sum(1 for c in dax_conversions if c.get("confidence", 0) < 0.6)
            review_count = sum(1 for c in dax_conversions if c.get("requires_review"))

            update_migration_status(
                db_path=self.db_path,
                migration_id=migration_id,
                status="completed",
                stats={
                    "tables": len(model.get("tables", [])),
                    "formulas_converted": len(dax_conversions),
                    "high_confidence": high_conf,
                    "medium_confidence": medium_conf,
                    "low_confidence": low_conf,
                    "requires_review": review_count,
                },
                elapsed_seconds=round(elapsed_total, 1),
                narrative_summary=None,
            )

            summary = {
                "artifacts": ["pbip", "excel", "dax", "json", "zip"],
                "zip_path": str(zip_path),
                "elapsed_seconds": round(elapsed_total, 1),
            }
            emitter.complete(summary, f"Export & packaging complete in {round(elapsed_total, 1)}s")

            logger.info(f"[{migration_id}] ExportAgent completed in {elapsed_total:.1f}s")
            return summary

        except Exception as e:
            logger.error(f"[{migration_id}] ExportAgent failed: {e}", exc_info=True)
            emitter.fail(str(e))
            raise

    def _derive_project_name(self, model: Dict, file_paths: List[str]) -> str:
        for ws in model.get("worksheets", []):
            lb = ws.get("source_liveboard")
            if lb:
                return lb.replace(" ", "_")
        if file_paths:
            return Path(file_paths[0]).stem.replace(" ", "_")
        return "ThoughtSpot_Migration"


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Registry — maps agent names to classes
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_REGISTRY = {
    "source_analysis": SourceAnalysisAgent,
    "data_model": DataModelAgent,
    "dax_conversion": DaxConversionAgent,
    "export": ExportAgent,
}
