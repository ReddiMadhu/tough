"""
ThoughtSpot Formula → DAX Converter

Handles:
- Simple aggregations: sum, average, count, unique_count, min, max, stddev, variance
- Group aggregations: group_sum, group_count, group_average, group_aggregate
- Percent of total: sum(x) / group_sum(x)
- Conditional: if (cond) then val else val
- Date functions: date_diff, add_days, month, year, today, etc.
- Text functions: contains, starts_with, strlen, substr, trim, lower, upper, replace, concat
- Arithmetic: (a - b) / c → DIVIDE(a-b, c, 0)
- Cumulative / running totals
- Moving averages
- Fallback with partial substitution
"""
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from loguru import logger


@dataclass
class DAXResult:
    """Result of converting a single ThoughtSpot formula to DAX."""
    original_formula: str
    dax_formula: str
    measure_name: str
    confidence: float        # 0.0 – 1.0
    pattern: str             # e.g. "DIRECT_AGG", "CALCULATE_ALLEXCEPT"
    notes: List[str] = field(default_factory=list)
    requires_review: bool = False


class ThoughtSpotFormulaConverter:
    """Convert ThoughtSpot formulas to Power BI DAX measures."""

    def __init__(self, table_name: str = "Table", column_table_map: Dict[str, str] = None):
        self.default_table = table_name
        self.col_table_map: Dict[str, str] = column_table_map or {}
        self.known_measures: set = set()
        
        # Build normalized column mapping (case-insensitive, space/underscore equivalent)
        self.norm_col_map = {}
        for col, table in self.col_table_map.items():
            norm_name = self._normalize_identifier(col)
            self.norm_col_map[norm_name] = (table, col)

    def convert(self, formula: str, measure_name: str) -> DAXResult:
        """Convert a single ThoughtSpot formula to a DAX measure."""
        if not formula or not formula.strip():
            return DAXResult(
                original_formula=formula,
                dax_formula=f"{measure_name} = BLANK()",
                measure_name=measure_name,
                confidence=0.5,
                pattern="EMPTY",
                notes=["Empty formula — defaulted to BLANK()"],
                requires_review=True,
            )

        formula = formula.strip()

        converters = [
            self._try_group_aggregate,
            self._try_group_function,
            self._try_percent_of_total,
            self._try_cumulative,
            self._try_conditional,
            self._try_date_function,
            self._try_text_function,
            self._try_simple_aggregation,
            self._try_arithmetic,
            self._try_fallback,
        ]

        for converter in converters:
            result = converter(formula, measure_name)
            if result:
                self.known_measures.add(measure_name)
                return result

        return self._try_fallback(formula, measure_name)

    # ── Column resolution ──────────────────────────────────────────────────────

    def _normalize_identifier(self, name: str) -> str:
        """Normalize identifier for comparison: lowercase, strip, strip special chars, underscores to spaces."""
        name = re.sub(r"[%\(\)#\$@/\-]", "", name)
        name = name.replace("_", " ").lower().strip()
        return name

    def _get_table_and_col(self, col: str) -> Tuple[str, str]:
        """Get (table_name, column_name) for a given column reference, with fallbacks."""
        col = col.strip().strip("'\"")
        norm = self._normalize_identifier(col)
        if norm in self.norm_col_map:
            table, orig_name = self.norm_col_map[norm]
            if table is not None:
                return table, orig_name
        # Fallback
        sanitized = self._sanitize_name(col)
        table = self.col_table_map.get(col, self.default_table)
        return table, sanitized

    def _resolve_col_name_only(self, col_name: str) -> Optional[str]:
        """Resolve a single column/measure name to its DAX reference format."""
        norm = self._normalize_identifier(col_name)
        
        # Check normalized map
        if norm in self.norm_col_map:
            table, orig_name = self.norm_col_map[norm]
            if table is None:
                return f"[{orig_name}]"
            return f"'{table}'[{orig_name}]"
            
        # Check known measures
        for m in self.known_measures:
            if self._normalize_identifier(m) == norm:
                return f"[{m}]"
                
        return None

    def _resolve_expr_identifiers(self, expr: str) -> str:
        """Resolve all column and measure references in a complex expression string."""
        literals = []
        def mask_literal(m):
            literals.append(m.group(0))
            return f"__LITERAL_{len(literals)-1}__"
            
        # Mask string literals: '...' or "..."
        masked = re.sub(r"'[^']*'|\"[^\"]*\"", mask_literal, expr)
        
        def replace_identifier(m):
            token = m.group(0)
            
            # If it's brackets [Col Name], extract the inner content
            if token.startswith("[") and token.endswith("]"):
                inner = token[1:-1]
                resolved = self._resolve_col_name_only(inner)
                if resolved:
                    return resolved
                return token
                
            # If it's a plain word
            lower_token = token.lower()
            if lower_token in (
                "if", "then", "else", "and", "or", "not", "true", "false", "null", "blank",
                "sum", "average", "avg", "count", "unique_count", "min", "max", "group_sum",
                "group_count", "group_average", "group_aggregate", "cumulative_sum"
            ):
                return token
                
            resolved = self._resolve_col_name_only(token)
            if resolved:
                return resolved
            return token

        # Match [identifier] or plain word
        pattern = r"\[[^\]]+\]|\b[a-zA-Z_][a-zA-Z0-9_]*\b"
        result = re.sub(pattern, replace_identifier, masked)
        
        # Unmask string literals
        for i, lit in enumerate(literals):
            result = result.replace(f"__LITERAL_{i}__", lit)
            
        return result

    def _resolve_col(self, col: str) -> str:
        """Resolve column name to DAX 'Table'[Column] format."""
        col = col.strip().strip("'\"")
        resolved = self._resolve_col_name_only(col)
        if resolved:
            return resolved
        # Fallback if not found in mapping
        sanitized = self._sanitize_name(col)
        table = self.col_table_map.get(col, self.default_table)
        return f"'{table}'[{sanitized}]"

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Strip special chars but preserve spaces."""
        return re.sub(r"[%\(\)#\$@/\-]", "", name).strip()

    # ── Converters ─────────────────────────────────────────────────────────────

    def _try_simple_aggregation(self, formula: str, name: str) -> Optional[DAXResult]:
        AGG_MAP = {
            "sum": "SUM", "average": "AVERAGE", "avg": "AVERAGE",
            "count": "COUNT", "unique_count": "DISTINCTCOUNT",
            "unique count": "DISTINCTCOUNT",
            "min": "MIN", "max": "MAX",
            "stddev": "STDEV.S", "variance": "VAR.S",
        }
        pattern = r"^(sum|average|avg|count|unique_count|unique count|min|max|stddev|variance)\s*\(\s*([^)]+)\s*\)$"
        m = re.match(pattern, formula.strip(), re.IGNORECASE)
        if not m:
            return None
        ts_func = m.group(1).lower()
        col = m.group(2).strip()
        dax_func = AGG_MAP[ts_func]
        dax_col = self._resolve_col(col)
        return DAXResult(
            original_formula=formula,
            dax_formula=f"{name} = {dax_func}({dax_col})",
            measure_name=name,
            confidence=0.95,
            pattern="DIRECT_AGG",
            notes=[f"{ts_func}() → {dax_func}()"],
        )

    def _try_group_function(self, formula: str, name: str) -> Optional[DAXResult]:
        GROUP_MAP = {
            "group_sum": "SUM", "group_count": "COUNT", "group_average": "AVERAGE",
            "group_unique_count": "DISTINCTCOUNT", "group_max": "MAX",
            "group_min": "MIN", "group_stddev": "STDEV.S",
        }
        pat = r"^(group_sum|group_count|group_average|group_unique_count|group_max|group_min|group_stddev)\s*\((.+)\)$"
        m = re.match(pat, formula.strip(), re.IGNORECASE)
        if not m:
            return None

        func_name = m.group(1).lower()
        args = self._split_args(m.group(2).strip())
        if not args:
            return None

        measure_col = args[0].strip()
        dim_cols = [a.strip() for a in args[1:]]
        dax_func = GROUP_MAP[func_name]
        dax_measure = self._resolve_col(measure_col)
        table, _ = self._get_table_and_col(measure_col)

        if dim_cols:
            allexcept_parts = []
            for d in dim_cols:
                d_table, d_col = self._get_table_and_col(d)
                allexcept_parts.append(f"'{d_table}'[{d_col}]")
            allexcept = ", ".join(allexcept_parts)
            dax = (
                f"{name} = \n"
                f"    CALCULATE(\n"
                f"        {dax_func}({dax_measure}),\n"
                f"        ALLEXCEPT('{table}', {allexcept})\n"
                f"    )"
            )
            pat_name = "CALCULATE_ALLEXCEPT"
        else:
            dax = (
                f"{name} = \n"
                f"    CALCULATE(\n"
                f"        {dax_func}({dax_measure}),\n"
                f"        ALL('{table}')\n"
                f"    )"
            )
            pat_name = "CALCULATE_ALL"

        return DAXResult(
            original_formula=formula,
            dax_formula=dax,
            measure_name=name,
            confidence=0.90,
            pattern=pat_name,
            notes=[f"{func_name}() → CALCULATE + ALLEXCEPT pattern",
                   f"Grouped by: {', '.join(dim_cols) if dim_cols else 'ALL (grand total)'}"],
        )

    def _try_group_aggregate(self, formula: str, name: str) -> Optional[DAXResult]:
        """Handle group_aggregate(expr, {dims}, {filters}, window_fn)."""
        m = re.match(r"^group_aggregate\s*\((.+)\)$", formula.strip(), re.IGNORECASE)
        if not m:
            return None

        inner = m.group(1).strip()

        # Dynamic grouping — no DAX equivalent
        if "query_groups()" in inner:
            return DAXResult(
                original_formula=formula,
                dax_formula=(
                    f"-- {name}: Manual conversion required\n"
                    f"-- Original ThoughtSpot: {formula}\n"
                    f"-- query_groups() has no direct DAX equivalent.\n"
                    f"-- This measure depends on which dimensions are on the visual.\n"
                    f"{name} = BLANK()  -- TODO: Replace with correct DAX"
                ),
                measure_name=name,
                confidence=0.30,
                pattern="DYNAMIC_GROUPING",
                notes=[
                    "query_groups() is context-dependent — no direct DAX equivalent",
                    "Manually author DAX in Power BI Desktop",
                    "Consider CALCULATE with explicit ALLEXCEPT/REMOVEFILTERS",
                ],
                requires_review=True,
            )

        # Cumulative / running total
        if "cumulative" in inner.lower():
            return self._convert_cumulative(formula, name, inner)

        # Moving average
        if "moving_average" in inner.lower():
            return self._convert_moving_average(formula, name, inner)

        # Parse {dim1, dim2} grouping
        dims_match = re.search(r"\{([^}]*)\}", inner)
        if dims_match:
            dims_str = dims_match.group(1).strip()
            dims = [d.strip() for d in dims_str.split(",") if d.strip()] if dims_str else []
            expr_part = inner[: inner.index("{")].strip().rstrip(",").strip()
            inner_dax = self._convert_expr(expr_part)
            
            table_match = re.search(r"'([^']+)'\[", inner_dax)
            table = table_match.group(1) if table_match else self.default_table
 
            if dims:
                allexcept_parts = []
                for d in dims:
                    d_table, d_col = self._get_table_and_col(d)
                    allexcept_parts.append(f"'{d_table}'[{d_col}]")
                allexcept = ", ".join(allexcept_parts)
                dax = (
                    f"{name} = \n"
                    f"    CALCULATE(\n"
                    f"        {inner_dax},\n"
                    f"        ALLEXCEPT('{table}', {allexcept})\n"
                    f"    )"
                )
            else:
                dax = (
                    f"{name} = \n"
                    f"    CALCULATE(\n"
                    f"        {inner_dax},\n"
                    f"        ALL('{table}')\n"
                    f"    )"
                )

            return DAXResult(
                original_formula=formula,
                dax_formula=dax,
                measure_name=name,
                confidence=0.75,
                pattern="CALCULATE_ALLEXCEPT",
                notes=["group_aggregate() → CALCULATE + ALLEXCEPT", "Review the filter context for correctness"],
                requires_review=True,
            )

        return None

    def _convert_cumulative(self, formula: str, name: str, inner: str) -> DAXResult:
        agg_m = re.search(r"(sum|count|average)\s*\(\s*([^)]+)\s*\)", inner, re.IGNORECASE)
        measure_col = agg_m.group(2).strip() if agg_m else "Amount"
        agg_func = agg_m.group(1).upper() if agg_m else "SUM"
        dim_m = re.search(r"\{([^}]+)\}", inner)
        
        date_expr = dim_m.group(1).strip() if dim_m else "Date"
        table, m_col = self._get_table_and_col(measure_col)
        date_table, date_col = self._get_table_and_col(date_expr)
        
        dax = (
            f"{name} = \n"
            f"    CALCULATE(\n"
            f"        {agg_func}('{table}'[{m_col}]),\n"
            f"        FILTER(\n"
            f"            ALL('{date_table}'[{date_col}]),\n"
            f"            '{date_table}'[{date_col}] <= MAX('{date_table}'[{date_col}])\n"
            f"        )\n"
            f"    )"
        )
        return DAXResult(
            original_formula=formula, dax_formula=dax, measure_name=name,
            confidence=0.80, pattern="RUNNING_TOTAL",
            notes=["Cumulative sum → CALCULATE + FILTER + ALL", f"Running total over '{date_col}'"],
            requires_review=True,
        )

    def _convert_moving_average(self, formula: str, name: str, inner: str) -> DAXResult:
        table = self.default_table
        dax = (
            f"{name} = \n"
            f"    AVERAGEX(\n"
            f"        DATESINPERIOD(\n"
            f"            '{table}'[Date],\n"
            f"            MAX('{table}'[Date]),\n"
            f"            -30,\n"
            f"            DAY\n"
            f"        ),\n"
            f"        CALCULATE(SUM('{table}'[Value]))\n"
            f"    )"
        )
        return DAXResult(
            original_formula=formula, dax_formula=dax, measure_name=name,
            confidence=0.65, pattern="MOVING_AVERAGE",
            notes=["Moving average → AVERAGEX + DATESINPERIOD",
                   "Replace [Date] and [Value] with actual column names",
                   "Adjust period (currently 30 days) if needed"],
            requires_review=True,
        )

    def _try_percent_of_total(self, formula: str, name: str) -> Optional[DAXResult]:
        pat = r"^(sum|count|average)\s*\(\s*([^)]+)\s*\)\s*/\s*group_(sum|count|average)\s*\(\s*([^)]+)\s*\)$"
        m = re.match(pat, formula.strip(), re.IGNORECASE)
        if not m:
            return None
        agg_func = m.group(1).upper()
        col = m.group(2).strip()
        dax_col = self._resolve_col(col)
        table, _ = self._get_table_and_col(col)
        dax = (
            f"{name} = \n"
            f"    DIVIDE(\n"
            f"        {agg_func}({dax_col}),\n"
            f"        CALCULATE({agg_func}({dax_col}), ALL('{table}')),\n"
            f"        0\n"
            f"    )"
        )
        return DAXResult(
            original_formula=formula, dax_formula=dax, measure_name=name,
            confidence=0.95, pattern="PERCENT_OF_TOTAL",
            notes=["Percent of total → DIVIDE + CALCULATE + ALL"],
        )

    def _try_conditional(self, formula: str, name: str) -> Optional[DAXResult]:
        m = re.match(
            r"^if\s*\((.+?)\)\s+then\s+(.+?)\s+else\s+(.+)$",
            formula.strip(), re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return None
        condition = self._convert_expr(m.group(1).strip())
        then_val = self._convert_expr(m.group(2).strip())
        else_val = m.group(3).strip()

        if else_val.lower().startswith("if "):
            nested = self.convert(else_val, "__nested__")
            nested_dax = nested.dax_formula.replace("__nested__ = ", "").strip()
            dax = f"{name} = \n    IF({condition}, {then_val}, {nested_dax})"
        else:
            else_dax = self._convert_expr(else_val)
            dax = f"{name} = IF({condition}, {then_val}, {else_dax})"

        return DAXResult(
            original_formula=formula, dax_formula=dax, measure_name=name,
            confidence=0.90, pattern="CONDITIONAL",
            notes=["if...then...else → IF() function"],
        )

    def _try_date_function(self, formula: str, name: str) -> Optional[DAXResult]:
        DATE_PATTERNS = [
            (r"^date_diff\s*\(\s*(.+?)\s*,\s*(.+?)\s*,\s*'(day|month|year|week|hour|minute|second)'\s*\)$",
             lambda m: f"DATEDIFF({self._resolve_col(m.group(2))}, {self._resolve_col(m.group(1))}, {m.group(3).upper()})"),
            (r"^add_days\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)$",
             lambda m: f"{self._resolve_col(m.group(1))} + {m.group(2)}"),
            (r"^day_of_week\s*\(\s*(.+?)\s*\)$",
             lambda m: f"WEEKDAY({self._resolve_col(m.group(1))})"),
            (r"^month\s*\(\s*(.+?)\s*\)$",
             lambda m: f"MONTH({self._resolve_col(m.group(1))})"),
            (r"^year\s*\(\s*(.+?)\s*\)$",
             lambda m: f"YEAR({self._resolve_col(m.group(1))})"),
            (r"^quarter\s*\(\s*(.+?)\s*\)$",
             lambda m: f"QUARTER({self._resolve_col(m.group(1))})"),
            (r"^day\s*\(\s*(.+?)\s*\)$",
             lambda m: f"DAY({self._resolve_col(m.group(1))})"),
            (r"^today\s*\(\s*\)$", lambda m: "TODAY()"),
            (r"^now\s*\(\s*\)$", lambda m: "NOW()"),
            (r"^start_of_month\s*\(\s*(.+?)\s*\)$",
             lambda m: f"EOMONTH({self._resolve_col(m.group(1))}, -1) + 1"),
            (r"^start_of_year\s*\(\s*(.+?)\s*\)$",
             lambda m: f"DATE(YEAR({self._resolve_col(m.group(1))}), 1, 1)"),
            (r"^end_of_month\s*\(\s*(.+?)\s*\)$",
             lambda m: f"EOMONTH({self._resolve_col(m.group(1))}, 0)"),
        ]
        for pat, converter in DATE_PATTERNS:
            m = re.match(pat, formula.strip(), re.IGNORECASE)
            if m:
                dax_expr = converter(m)
                return DAXResult(
                    original_formula=formula,
                    dax_formula=f"{name} = {dax_expr}",
                    measure_name=name,
                    confidence=0.90,
                    pattern="DATE_FUNCTION",
                    notes=["Date function converted"],
                )
        return None

    def _try_text_function(self, formula: str, name: str) -> Optional[DAXResult]:
        TEXT_PATTERNS = [
            (r"^contains\s*\(\s*(.+?)\s*,\s*'([^']+)'\s*\)$",
             lambda m: f'CONTAINSSTRING({self._resolve_col(m.group(1))}, "{m.group(2)}")'),
            (r"^starts_with\s*\(\s*(.+?)\s*,\s*'([^']+)'\s*\)$",
             lambda m: f'LEFT({self._resolve_col(m.group(1))}, {len(m.group(2))}) = "{m.group(2)}"'),
            (r"^strlen\s*\(\s*(.+?)\s*\)$",
             lambda m: f"LEN({self._resolve_col(m.group(1))})"),
            (r"^substr\s*\(\s*(.+?)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$",
             lambda m: f"MID({self._resolve_col(m.group(1))}, {m.group(2)}, {m.group(3)})"),
            (r"^trim\s*\(\s*(.+?)\s*\)$",
             lambda m: f"TRIM({self._resolve_col(m.group(1))})"),
            (r"^lower\s*\(\s*(.+?)\s*\)$",
             lambda m: f"LOWER({self._resolve_col(m.group(1))})"),
            (r"^upper\s*\(\s*(.+?)\s*\)$",
             lambda m: f"UPPER({self._resolve_col(m.group(1))})"),
            (r"^replace\s*\(\s*(.+?)\s*,\s*'([^']+)'\s*,\s*'([^']*)'\s*\)$",
             lambda m: f'SUBSTITUTE({self._resolve_col(m.group(1))}, "{m.group(2)}", "{m.group(3)}")'),
            (r"^concat\s*\((.+)\)$",
             lambda m: " & ".join(
                 f'"{a.strip()[1:-1]}"' if (a.strip().startswith("'") and a.strip().endswith("'")) else self._resolve_col(a.strip())
                 for a in self._split_args(m.group(1))
             )),
        ]
        for pat, converter in TEXT_PATTERNS:
            m = re.match(pat, formula.strip(), re.IGNORECASE)
            if m:
                return DAXResult(
                    original_formula=formula,
                    dax_formula=f"{name} = {converter(m)}",
                    measure_name=name,
                    confidence=0.90,
                    pattern="TEXT_FUNCTION",
                    notes=["Text function converted"],
                )
        return None

    def _try_arithmetic(self, formula: str, name: str) -> Optional[DAXResult]:
        # Safe division
        div_m = re.match(r"^(.+?)\s*/\s*(.+)$", formula.strip())
        if div_m:
            num = self._convert_expr(div_m.group(1).strip())
            den = self._convert_expr(div_m.group(2).strip())
            return DAXResult(
                original_formula=formula,
                dax_formula=f"{name} = DIVIDE({num}, {den}, 0)",
                measure_name=name,
                confidence=0.85,
                pattern="ARITHMETIC",
                notes=["Division → DIVIDE() for safe division-by-zero handling"],
            )
        # General arithmetic
        if re.search(r"[+\-*]", formula):
            dax_expr = self._convert_expr(formula)
            return DAXResult(
                original_formula=formula,
                dax_formula=f"{name} = {dax_expr}",
                measure_name=name,
                confidence=0.80,
                pattern="ARITHMETIC",
                notes=["Arithmetic expression converted"],
            )
        return None

    def _try_cumulative(self, formula: str, name: str) -> Optional[DAXResult]:
        """Detect standalone cumulative/running total patterns."""
        if "cumulative" not in formula.lower():
            return None
        return self._convert_cumulative(formula, name, formula)

    def _try_fallback(self, formula: str, name: str) -> DAXResult:
        # Attempt LLM Translation first if enabled
        try:
            from src.llm_reasoner import LLMReasoner
            llm = LLMReasoner()
            if llm.llm:
                schema_context = []
                if self.default_table:
                    schema_context.append(f"Primary table: '{self.default_table}'")
                if self.col_table_map:
                    schema_context.append("Known column mappings:")
                    for col, tbl in list(self.col_table_map.items())[:20]:
                        schema_context.append(f"  - Column '{col}' is in table '{tbl}'")
                if self.known_measures:
                    schema_context.append("Known measure references:")
                    for m in list(self.known_measures)[:20]:
                        schema_context.append(f"  - Measure: [{m}]")
                schema_str = "\n".join(schema_context)

                llm_result = llm.translate_formula(formula, name, schema_str)
                if llm_result:
                    return DAXResult(
                        original_formula=formula,
                        dax_formula=llm_result.get("dax_formula", f"{name} = BLANK()"),
                        measure_name=name,
                        confidence=llm_result.get("confidence", 0.6),
                        pattern=llm_result.get("pattern", "AI_TRANSLATION"),
                        notes=llm_result.get("notes", ["AI fallback translation"]),
                        requires_review=llm_result.get("requires_review", True),
                    )
        except Exception as e:
            logger.error(f"Error in LLM fallback translator: {e}")

        # Regex fallback when LLM is unavailable
        dax = formula
        REPLACEMENTS = {
            r"\bifnull\s*\(": "IF(ISBLANK(",
            r"\bisnull\s*\(": "ISBLANK(",
            r"\bavg\s*\(": "AVERAGE(",
            r"\bunique_count\s*\(": "DISTINCTCOUNT(",
        }
        for pat, repl in REPLACEMENTS.items():
            dax = re.sub(pat, repl, dax, flags=re.IGNORECASE)

        changed = dax.strip() != formula.strip()
        return DAXResult(
            original_formula=formula,
            dax_formula=f"{name} = {dax}",
            measure_name=name,
            confidence=0.50 if changed else 0.30,
            pattern="FALLBACK",
            notes=[
                "Partial automatic conversion — manual review required" if changed
                else "Could not auto-convert — manual DAX authoring needed",
                f"Original ThoughtSpot: {formula}",
            ],
            requires_review=True,
        )


    # ── Expression helpers ─────────────────────────────────────────────────────

    def _convert_expr(self, expr: str) -> str:
        """Convert a sub-expression."""
        expr = expr.strip().strip("()")
        
        # Check if it is a simple aggregation
        agg_m = re.match(r"^(sum|average|avg|count|min|max)\s*\(\s*([^)]+)\s*\)$", expr, re.IGNORECASE)
        if agg_m:
            func = agg_m.group(1).upper()
            if func == "AVG":
                func = "AVERAGE"
            return f"{func}({self._resolve_col(agg_m.group(2).strip())})"
            
        # Check if it is a simple literal/value
        if expr.startswith("'") and expr.endswith("'"):
            return f'"{expr[1:-1]}"'
            
        # Otherwise, resolve all identifier tokens in the expression
        return self._resolve_expr_identifiers(expr)

    def _split_args(self, args_str: str) -> List[str]:
        """Split function arguments respecting nested parens."""
        args, depth, current = [], 0, []
        for ch in args_str:
            if ch in ("(", "{"):
                depth += 1
                current.append(ch)
            elif ch in (")", "}"):
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            args.append("".join(current).strip())
        return args
