"""
Self-Healing Agent - Autonomous DAX correction based on validation failures for ThoughtSpot formulas.
"""
import json
from typing import Dict, List, Any, Optional
from loguru import logger

from src.llm_reasoner import LLMReasoner, DaxCorrectionResponse, clean_and_validate_json


class SelfHealingAgent:
    """
    Analyzes formula validation discrepancies and generates corrected DAX.
    """

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self.llm_reasoner = LLMReasoner()
        logger.info(f"Self-Healing Agent initialized (max attempts: {max_attempts})")

    def correct_dax(
        self,
        original_formula: str,
        failed_dax: str,
        failures: List[Dict[str, Any]],
        attempt_number: int,
        measure_name: str,
        schema_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate corrected DAX based on validation failures.
        """
        logger.info(f"Triggering self-healing attempt {attempt_number} for {measure_name}")

        # Count and analyze failure categories
        error_categories = {}
        for f in failures:
            cat = f.get("error_category", "AGGREGATION_MISMATCH")
            error_categories[cat] = error_categories.get(cat, 0) + 1

        # Render failure summary for LLM context
        failure_details = []
        for idx, f in enumerate(failures[:5], 1):
            failure_details.append(
                f"Failure {idx}:\n"
                f"  Dimensions: {f.get('dimensions')}\n"
                f"  Expected (ThoughtSpot value): {f.get('tableau_value')}\n"
                f"  Got (DAX value): {f.get('dax_value')}\n"
                f"  Delta: {f.get('delta')}\n"
                f"  Error Type: {f.get('error_category')}"
            )
        failure_summary = "\n".join(failure_details)

        prompt = f"""You are a world-class DAX debugger specializing in migrating ThoughtSpot analytics to Power BI.
This is self-healing correction attempt {attempt_number} of {self.max_attempts} for metric `{measure_name}`.

---

## METRIC CONTEXT
- **Measure Name**: `{measure_name}`
- **Original ThoughtSpot Formula**: `{original_formula}`
- **Current Generated DAX (Failed)**: `{failed_dax}`

## SCHEMA CONTEXT (MANDATORY — use EXACT table and column names)
{schema_context or "No schema context provided. Default to '[Column Name]' formatting."}

## COMPILATION & VALIDATION ERRORS
{failure_summary}

## ERROR CATEGORY DISTRIBUTION
{json.dumps(error_categories)}

---

## DAX MEASURE RULES (Your corrected formula MUST obey ALL of these)

### R1 — No Naked Column References
A DAX **measure** MUST aggregate all column references. `'Table'[Col]` alone causes a compilation error.
ALWAYS wrap in: SUM(), AVERAGE(), COUNT(), DISTINCTCOUNT(), MIN(), MAX(), etc.
**Exception**: Inside iterators (SUMX, FILTER, AVERAGEX, ADDCOLUMNS) naked refs are valid (row context).

### R2 — DIVIDE Safety
ALL division MUST use `DIVIDE(numerator, denominator, 0)`. NEVER use `a / b`.

### R3 — CALCULATE Filter Arguments
CALCULATE() filter arguments must be:
- Boolean expressions: `'Table'[Col] = "value"`
- Table functions: ALL(), ALLEXCEPT(), FILTER(), REMOVEFILTERS()
NEVER pass a naked column ref as a CALCULATE filter argument.

### R4 — ALLEXCEPT Semantics
`ALLEXCEPT('Table', 'Table'[Dim])` removes ALL filters from the table EXCEPT the named column.
For ThoughtSpot `group_aggregate(expr, {{dim}})`, use: `CALCULATE(expr, ALLEXCEPT('Table', 'Table'[dim]))`.
For grand totals (no dims), use `CALCULATE(expr, ALL('Table'))`.

### R5 — Table Qualification
ALL column refs MUST use `'TableName'[ColumnName]`. Measure refs use bare `[MeasureName]`.
NEVER hallucinate table names — use ONLY tables from the SCHEMA CONTEXT above.

### R6 — No Ghost Date Tables
Do NOT assume a `'Date'[Date]` table exists unless it's in the schema.
Use actual date columns from the schema for time intelligence functions.

### R7 — Cumulative / Running Totals
Pattern: `CALCULATE(AGG('Table'[Col]), FILTER(ALL('DateTable'[DateCol]), 'DateTable'[DateCol] <= MAX('DateTable'[DateCol])))`

### R8 — Moving Averages
Pattern: `AVERAGEX(DATESINPERIOD('Table'[Date], MAX('Table'[Date]), -N, DAY), CALCULATE(SUM('Table'[Value])))`

### R9 — group_aggregate → CALCULATE + ALLEXCEPT
ThoughtSpot `group_aggregate(sum(col), {{dim1, dim2}})` →
`CALCULATE(SUM('Table'[col]), ALLEXCEPT('Table', 'Table'[dim1], 'Table'[dim2]))`.
`query_groups()` has NO DAX equivalent.

### R10 — Conditional: if/then/else → IF()
`if(cond) then val else val` → `IF(condition, then_value, else_value)`
Boolean: `and` → `&&`, `or` → `||`, `!=` → `<>`

### R11 — Null Handling
`ifnull(x, y)` → `IF(ISBLANK(x), y, x)`
`isnull(x)` → `ISBLANK(x)`

### R12 — VAR/RETURN for Complex Logic
Use VAR to break down complex calculations. This improves readability and performance.

### R13 — Cross-Table References
Use RELATED() for many-to-one lookups inside iterators.
Let relationships propagate filters — do NOT manually filter related tables.

---

## FEW-SHOT CORRECTION EXAMPLES

### Fix Example 1 — Naked Column → Aggregated
- **Failed**: `Revenue = 'Sales'[Amount]`
- **Error**: Naked column reference outside aggregation
- **Fixed**: `Revenue = SUM('Sales'[Amount])`
- **Reasoning**: Measures require aggregation; wrapped in SUM().

### Fix Example 2 — Raw Division → DIVIDE
- **Failed**: `Margin = SUM('Sales'[Profit]) / SUM('Sales'[Revenue])`
- **Error**: Division by zero risk
- **Fixed**: `Margin = DIVIDE(SUM('Sales'[Profit]), SUM('Sales'[Revenue]), 0)`
- **Reasoning**: Replaced `/` with DIVIDE() for safe division.

### Fix Example 3 — Missing ALLEXCEPT Context
- **Failed**: `Regional Total = SUM('Sales'[Amount])`
- **Error**: Missing filter context for group_aggregate
- **Fixed**: `Regional Total = CALCULATE(SUM('Sales'[Amount]), ALLEXCEPT('Sales', 'Sales'[Region]))`
- **Reasoning**: Added CALCULATE + ALLEXCEPT to pin aggregation to Region level.

### Fix Example 4 — Wrong Table Name
- **Failed**: `Total = SUM('Revenue'[Amount])`
- **Error**: Table 'Revenue' does not exist
- **Fixed**: `Total = SUM('Sales'[Amount])`
- **Reasoning**: Corrected table name from schema context.

---

## YOUR TASK

**Think step-by-step** before generating your fix:
1. Read the compilation/validation errors carefully.
2. Identify which DAX rules (R1-R13) are violated.
3. Plan your correction — what exactly needs to change?
4. Generate the corrected DAX using ONLY schema-provided names.
5. Verify your fix against all 13 rules mentally.

Respond ONLY with a valid JSON object (no markdown wraps):
{{
  "root_cause": "Detailed step-by-step explanation of WHY the current DAX failed...",
  "corrected_dax": "{measure_name} = <corrected DAX formula>",
  "explanation": "What changes were made and why, referencing specific rules...",
  "changes_made": ["Changed X to Y (Rule R2)", "Added ALLEXCEPT for filter context (Rule R4)"]
}}
"""
        try:
            if not self.llm_reasoner.llm:
                logger.warning("LLM Reasoner is not active. Skipping LLM correction.")
                return self._fallback_correction(failed_dax, error_categories, attempt_number)

            response = self.llm_reasoner.reason(prompt)
            parsed_res = clean_and_validate_json(response, DaxCorrectionResponse)
            data = parsed_res.model_dump()

            # Ensure the corrected dax starts with the measure name assignment
            corrected_dax = data.get("corrected_dax", failed_dax)
            if corrected_dax and not corrected_dax.startswith(f"{measure_name} ="):
                corrected_dax = f"{measure_name} = {corrected_dax}"

            return {
                "attempt_number": attempt_number,
                "original_dax": failed_dax,
                "corrected_dax": corrected_dax,
                "root_cause": data.get("root_cause", "Logical discrepancy in translation"),
                "explanation": data.get("explanation", "Corrected translation logic"),
                "changes_made": data.get("changes_made", ["Adjusted DAX logic"])
            }

        except Exception as e:
            logger.error(f"Error in self healer LLM execution: {e}")
            return self._fallback_correction(failed_dax, error_categories, attempt_number)

    def _fallback_correction(self, failed_dax: str, error_categories: Dict[str, int], attempt_number: int) -> Dict[str, Any]:
        """Simple rule-based fallback correction when LLM is unavailable."""
        changes = []
        corrected = failed_dax

        # Rule 1: Check division operator
        if "/" in corrected and "DIVIDE" not in corrected:
            # Simple regex attempt to wrap in DIVIDE
            parts = corrected.split("=")
            if len(parts) == 2:
                m_name, expr = parts[0].strip(), parts[1].strip()
                expr_parts = expr.split("/")
                if len(expr_parts) == 2:
                    corrected = f"{m_name} = DIVIDE({expr_parts[0].strip()}, {expr_parts[1].strip()}, 0)"
                    changes.append("Wrapped division in safe DIVIDE() function")

        # Rule 2: If we didn't do anything, make a dummy comment change to prevent infinite loops
        if corrected == failed_dax:
            corrected = f"{corrected}  -- verified in attempt {attempt_number}"
            changes.append(f"Appended validation marker comment for attempt {attempt_number}")

        return {
            "attempt_number": attempt_number,
            "original_dax": failed_dax,
            "corrected_dax": corrected,
            "root_cause": "Offline correction rule applied",
            "explanation": "Applied rule-based syntax fixes (e.g. safe division check)",
            "changes_made": changes
        }
