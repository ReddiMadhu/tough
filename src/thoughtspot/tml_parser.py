"""
TML Parser — converts raw SpotApp data into the normalized intermediate model.
"""
import re
import datetime
from typing import List, Dict, Any, Optional
from loguru import logger


class TMLParser:
    """Parse ThoughtSpot TML objects into a normalized intermediate model."""

    def __init__(self):
        self.tables: List[Dict] = []
        self.columns: List[Dict] = []
        self.joins: List[Dict] = []
        self.formulas: List[Dict] = []
        self.worksheets: List[Dict] = []
        self.filters: List[Dict] = []
        self.caption_map: Dict[str, str] = {}

    def parse_all(self, spotapp_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse all TML objects into a unified intermediate model.
        Processing order: tables → models → liveboards → answers
        """
        for tml in spotapp_data.get("tables", []):
            self._parse_table(tml)

        for tml in spotapp_data.get("models", []):
            self._parse_model(tml)

        for tml in spotapp_data.get("liveboards", []):
            self._parse_liveboard(tml)

        for tml in spotapp_data.get("answers", []):
            self._parse_answer(tml)

        return self._build_intermediate_model()

    # ── Table ──────────────────────────────────────────────────────────────────

    def _parse_table(self, tml: Dict[str, Any]):
        table_data = tml.get("table", {})
        table_name = table_data.get("name", "")

        columns = []
        for col in table_data.get("columns", []):
            col_name = col.get("name", "")
            col_entry = {
                "name": col_name,
                "db_column_name": col.get("db_column_name", col_name),
                "data_type": col.get("data_type", "VARCHAR"),
                "column_type": col.get("column_type", "ATTRIBUTE"),
                "aggregation": col.get("aggregation", ""),
                "format_pattern": col.get("format_pattern", ""),
            }
            columns.append(col_entry)
            self.caption_map[f"{table_name}::{col_name}"] = col_name

        self.tables.append({
            "name": table_name,
            "raw_name": table_name,
            "source": table_data.get("db_table", ""),
            "database": table_data.get("db", ""),
            "schema": table_data.get("schema", ""),
            "type": "table",
            "columns": [c["name"] for c in columns],
            "column_details": columns,
            "connection": table_data.get("connection", {}),
            "guid": tml.get("guid", ""),
        })

        for join in table_data.get("joins_with", []):
            self._parse_table_join(table_name, join)

    def _parse_table_join(self, source_table: str, join_def: Dict):
        dest = join_def.get("destination", {})
        on_clause = join_def.get("on") or join_def.get(True) or ""
        left_col, right_col = self._parse_on_clause(on_clause)
        self.joins.append({
            "name": join_def.get("name", ""),
            "left_table": source_table,
            "left_column": left_col,
            "right_table": dest.get("name", ""),
            "right_column": right_col,
            "join_type": join_def.get("type", "LEFT_OUTER"),
            "cardinality": join_def.get("cardinality", "MANY_TO_ONE"),
        })

    # ── Model / Worksheet ──────────────────────────────────────────────────────

    def _parse_model(self, tml: Dict[str, Any]):
        # Handle both worksheet: and model: root keys
        model_data = tml.get("worksheet") or tml.get("model", {})
        model_name = model_data.get("name", "")

        # Build table alias → name map
        table_refs: Dict[str, str] = {}
        tables_list = model_data.get("tables") or model_data.get("model_tables", [])
        for t in tables_list:
            table_id = t.get("id") or t.get("name", "")
            table_refs[table_id] = t.get("name", "")

        # Formulas (calculated fields)
        for formula in model_data.get("formulas", []):
            expr = formula.get("expr", "")
            entry = {
                "internal_name": formula.get("id", ""),
                "caption": formula.get("name", ""),
                "formula": expr,
                "formula_type": self._classify_formula(expr),
                "datatype": "real",
                "role": "measure",
                "type": "continuous",
                "default_aggregation": "",
                "format": "",
                "hidden": False,
                "source_tables": [],
                "source_object": model_name,
                "source_object_type": "Model",
            }
            self.formulas.append(entry)
            self.caption_map[formula.get("id", "")] = formula.get("name", "")

        # Columns defined in the model
        formula_lookup = {f["internal_name"]: f for f in self.formulas}
        for col in model_data.get("columns", []):
            col_id = col.get("column_id", col.get("formula_id", ""))
            is_formula = bool(col.get("formula_id"))

            source_table = ""
            col_name = col.get("name", "")
            if "::" in str(col_id):
                parts = col_id.split("::")
                source_table = table_refs.get(parts[0], parts[0])
                col_name = parts[1] if len(parts) > 1 else col_name

            formula_expr = ""
            formula_type = ""
            if is_formula and col.get("formula_id") in formula_lookup:
                fd = formula_lookup[col["formula_id"]]
                formula_expr = fd["formula"]
                formula_type = fd["formula_type"]

            self.columns.append({
                "internal_name": col.get("name", ""),
                "caption": col.get("name", ""),
                "datatype": col.get("data_type", ""),
                "role": "measure" if col.get("column_type") == "MEASURE" else "dimension",
                "type": "continuous" if col.get("column_type") == "MEASURE" else "discrete",
                "default_aggregation": col.get("aggregation", ""),
                "format": col.get("format_pattern", ""),
                "hidden": col.get("hidden", False),
                "formula": formula_expr,
                "formula_type": formula_type,
                "source_tables": [source_table] if source_table else [],
                "formula_id": col.get("formula_id", ""),
                "source_object": model_name,
                "source_object_type": "Model",
            })
            self.caption_map[col.get("name", "")] = col.get("name", "")

        # Joins in model
        for join in model_data.get("joins", []):
            src_alias = join.get("source", "")
            dst_alias = join.get("destination", "")
            on_clause = join.get("on") or join.get(True) or ""
            left_col, right_col = self._parse_on_clause(on_clause)
            self.joins.append({
                "name": join.get("name", ""),
                "left_table": table_refs.get(src_alias, src_alias),
                "left_column": left_col,
                "right_table": table_refs.get(dst_alias, dst_alias),
                "right_column": right_col,
                "join_type": join.get("type", "LEFT_OUTER"),
                "cardinality": join.get("cardinality", "MANY_TO_ONE"),
            })

        for t in model_data.get("model_tables", []):
            src_table = t.get("name", "")
            for join in t.get("joins", []):
                dst_table = join.get("with", "")
                on_clause = join.get("on") or join.get(True) or ""
                left_col, right_col = self._parse_on_clause(on_clause)
                self.joins.append({
                    "name": join.get("name", f"{src_table}_{dst_table}_join"),
                    "left_table": src_table,
                    "left_column": left_col,
                    "right_table": dst_table,
                    "right_column": right_col,
                    "join_type": join.get("type", "LEFT_OUTER"),
                    "cardinality": join.get("cardinality", "MANY_TO_ONE"),
                })

        # Model-level filters
        for f in model_data.get("filters", []):
            self.filters.append({
                "column": f.get("column", ""),
                "operator": f.get("oper", ""),
                "values": f.get("values", []),
                "source": model_name,
            })

    # ── Liveboard ──────────────────────────────────────────────────────────────

    def _parse_liveboard(self, tml: Dict[str, Any]):
        lb_data = tml.get("liveboard") or tml.get("pinboard", {})
        lb_name = lb_data.get("name", "")

        for viz in lb_data.get("visualizations", []):
            answer = viz.get("answer", {})
            chart = answer.get("chart", {})

            axis_map = {}
            for config in chart.get("axis_configs", []):
                for axis_name, col_ids in config.items():
                    if isinstance(col_ids, list):
                        for cid in col_ids:
                            axis_map[cid] = axis_name.upper()
                    elif isinstance(col_ids, str):
                        axis_map[col_ids] = axis_name.upper()

            rows, cols_list = [], []
            for chart_col in chart.get("chart_columns", []):
                col_name = chart_col.get("column_id") or chart_col.get("column", {}).get("name", "")
                if not col_name:
                    continue
                axis = chart_col.get("axis", "")
                if not axis and col_name in axis_map:
                    axis = axis_map[col_name]
                if axis in ("Y_AXIS", "Y_AXIS_2", "Y", "Y2", "SIZE"):
                    rows.append(col_name)
                else:
                    cols_list.append(col_name)

            # Local formulas in this answer
            for f in answer.get("formulas", []):
                expr = f.get("expr", "")
                self.formulas.append({
                    "internal_name": f.get("id", ""),
                    "caption": f.get("name", ""),
                    "formula": expr,
                    "formula_type": self._classify_formula(expr),
                    "datatype": "real",
                    "role": "measure",
                    "type": "continuous",
                    "default_aggregation": "",
                    "format": "",
                    "hidden": False,
                    "source_tables": [],
                    "source_object": lb_name,
                    "source_object_type": "Liveboard",
                })

            ts_chart_type = chart.get("type", "TABLE")
            self.worksheets.append({
                "name": answer.get("name", viz.get("id", "")),
                "title": answer.get("name", ""),
                "mark_type": self._map_chart_type(ts_chart_type),
                "rows": [f"[{r}]" for r in rows],
                "cols": [f"[{c}]" for c in cols_list],
                "search_query": answer.get("search_query", ""),
                "source_liveboard": lb_name,
                "ts_chart_type": ts_chart_type,
                "source_object_type": "Liveboard",
            })

    # ── Answer ─────────────────────────────────────────────────────────────────

    def _parse_answer(self, tml: Dict[str, Any]):
        answer_data = tml.get("answer", {})
        chart = answer_data.get("chart", {})
        answer_name = answer_data.get("name", "")

        axis_map = {}
        for config in chart.get("axis_configs", []):
            for axis_name, col_ids in config.items():
                if isinstance(col_ids, list):
                    for cid in col_ids:
                        axis_map[cid] = axis_name.upper()
                elif isinstance(col_ids, str):
                    axis_map[col_ids] = axis_name.upper()

        rows, cols_list = [], []
        for chart_col in chart.get("chart_columns", []):
            col_name = chart_col.get("column_id") or chart_col.get("column", {}).get("name", "")
            if not col_name:
                continue
            axis = chart_col.get("axis", "")
            if not axis and col_name in axis_map:
                axis = axis_map[col_name]
            if axis in ("Y_AXIS", "Y_AXIS_2", "Y", "Y2", "SIZE"):
                rows.append(col_name)
            else:
                cols_list.append(col_name)

        for f in answer_data.get("formulas", []):
            expr = f.get("expr", "")
            self.formulas.append({
                "internal_name": f.get("id", ""),
                "caption": f.get("name", ""),
                "formula": expr,
                "formula_type": self._classify_formula(expr),
                "datatype": "real",
                "role": "measure",
                "type": "continuous",
                "default_aggregation": "",
                "format": "",
                "hidden": False,
                "source_tables": [],
                "source_object": answer_name,
                "source_object_type": "Answer",
            })

        ts_chart_type = chart.get("type", "TABLE")
        self.worksheets.append({
            "name": answer_name,
            "title": answer_name,
            "mark_type": self._map_chart_type(ts_chart_type),
            "rows": [f"[{r}]" for r in rows],
            "cols": [f"[{c}]" for c in cols_list],
            "search_query": answer_data.get("search_query", ""),
            "source_liveboard": "",
            "ts_chart_type": ts_chart_type,
            "source_object_type": "Answer",
        })

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _parse_on_clause(self, on_clause):
        """Parse '[Table1::Col1] = [Table2::Col2]' → (col1, col2).
        
        Handles edge cases:
        - PyYAML 1.1 may parse the key 'on' as boolean True
        - Values may or may not be bracket-quoted
        """
        # Handle boolean True from PyYAML 1.1 (key 'on' → True)
        if on_clause is True or on_clause is False:
            return ("", "")
        if not on_clause:
            return ("", "")

        on_str = str(on_clause).strip().strip("'\"")

        # Try full regex match first: [Table::Col] = [Table::Col]
        m = re.search(r"\[([^:]+)::([^\]]+)\]\s*=\s*\[([^:]+)::([^\]]+)\]", on_str)
        if m:
            return m.group(2).strip(), m.group(4).strip()

        # Fallback: split on '=' and extract columns
        parts = on_str.split("=")
        if len(parts) != 2:
            logger.warning(f"Could not parse on-clause: {on_str}")
            return ("", "")

        left_part = parts[0].strip()
        right_part = parts[1].strip()

        left_match = re.search(r"([^:\[]+)::([^\]]+)\]?", left_part)
        right_match = re.search(r"([^:\[]+)::([^\]]+)\]?", right_part)

        left_col = left_match.group(2).strip().rstrip("]") if left_match else ""
        right_col = right_match.group(2).strip().rstrip("]") if right_match else ""

        # Last resort: use the raw value after stripping brackets
        if not left_col:
            lm = re.search(r"\[?([^\]]+)\]?", left_part)
            if lm:
                left_col = lm.group(1).strip()
        if not right_col:
            rm = re.search(r"\[?([^\]]+)\]?", right_part)
            if rm:
                right_col = rm.group(1).strip()

        return left_col, right_col

    def _classify_formula(self, formula: str) -> str:
        if not formula:
            return ""
        f = formula.lower()
        if any(fn in f for fn in ("group_aggregate", "group_sum", "group_count", "group_average", "group_unique_count", "group_max", "group_min")):
            return "GROUP_AGGREGATE"
        if any(fn in f for fn in ("cumulative", "moving_average", "rank(")):
            return "WINDOW_CALC"
        return "STANDARD"

    def _map_chart_type(self, ts_type: str) -> str:
        mapping = {
            "COLUMN": "bar", "BAR": "bar", "LINE": "line",
            "AREA": "area", "PIE": "pie", "DONUT": "pie",
            "SCATTER": "circle", "KPI": "text", "TABLE": "text",
            "PIVOT_TABLE": "text", "STACKED_COLUMN": "bar",
            "STACKED_BAR": "bar", "GEO_AREA": "map", "GEO_BUBBLE": "map",
            "TREEMAP": "square", "FUNNEL": "bar", "WATERFALL": "bar",
            "HEATMAP": "square",
        }
        return mapping.get(ts_type.upper() if ts_type else "", "automatic")

    def _build_intermediate_model(self) -> Dict[str, Any]:
        """Assemble all parsed data into the unified intermediate model."""
        # Merge formulas into columns (formulas ARE columns)
        all_columns = list(self.columns)
        existing = {c["internal_name"] for c in all_columns}
        
        # Track formula IDs already referenced by model columns to prevent duplicates
        referenced_formula_ids = {
            col.get("formula_id") for col in self.columns if col.get("formula_id")
        }
        
        for f in self.formulas:
            f_id = f["internal_name"]
            if f_id not in existing and f_id not in referenced_formula_ids:
                all_columns.append(f)
                existing.add(f_id)

        # Deduplicate joins by left+right table pair
        seen_joins = set()
        deduped_joins = []
        for j in self.joins:
            key = (j["left_table"], j["right_table"], j["left_column"], j["right_column"])
            if key not in seen_joins:
                seen_joins.add(key)
                deduped_joins.append(j)

        return {
            "_meta": {
                "source_type": "thoughtspot",
                "extractor": "thoughtspot_tml_parser v1",
                "extraction_time": datetime.datetime.utcnow().isoformat(),
            },
            "model_type": "RELATIONSHIP" if deduped_joins else "FLAT",
            "tables": self.tables,
            "joins": deduped_joins,
            "relationships": [
                {
                    "table1": j["left_table"],
                    "table2": j["right_table"],
                    "table1_column": j["left_column"],
                    "table2_column": j["right_column"],
                    "cardinality": j["cardinality"].lower().replace("_", "-"),
                    "join_type": j["join_type"],
                    "name": j["name"],
                }
                for j in deduped_joins
            ],
            "columns": all_columns,
            "lod_calcs": [f for f in self.formulas if f.get("formula_type") == "GROUP_AGGREGATE"],
            "table_calcs": [f for f in self.formulas if f.get("formula_type") == "WINDOW_CALC"],
            "worksheets": self.worksheets,
            "filters": self.filters,
            "caption_map": self.caption_map,
        }
