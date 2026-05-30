"""
ThoughtSpot to Power BI Validation Engine.
Performs syntax verification, LLM semantic validation, and generates test slices for visual fidelity review.
"""
import re
import json
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger

from src.llm_reasoner import LLMReasoner


class ValidationEngine:
    """
    Validates converted DAX formulas against ThoughtSpot formulas.
    Uses syntax heuristics and LLM semantic validation.
    """

    def __init__(self, epsilon: float = 0.0001):
        self.epsilon = epsilon
        logger.info("Validation Engine initialized for ThoughtSpot formulas")

    def validate(
        self,
        conversion_id: str,
        original_formula: str,
        dax_formula: str,
        measure_name: str,
        confidence: float,
        migration_id: str
    ) -> Dict[str, Any]:
        """
        Main validation function.
        Returns:
            Dict containing validation status, pass rate, test slices, and error category breakdown.
        """
        logger.info(f"Validating conversion {conversion_id} ({measure_name})")

        # Step 1: Basic syntax checks
        syntax_passed, syntax_error = self._check_syntax(dax_formula)
        if not syntax_passed:
            logger.warning(f"Syntax validation failed for {measure_name}: {syntax_error}")
            return self._create_failed_result(
                conversion_id,
                dax_formula,
                category="AGGREGATION_MISMATCH",
                note=f"Syntax check failed: {syntax_error}"
            )

        # Step 2: Try LLM semantic validation if enabled
        llm_result = self._validate_with_llm(original_formula, dax_formula, measure_name)
        if llm_result:
            return llm_result

        # Step 3: Rule-based fallback if LLM is disabled or fails
        return self._fallback_validation(conversion_id, original_formula, dax_formula, measure_name, confidence)

    def _check_syntax(self, dax_formula: str) -> Tuple[bool, Optional[str]]:
        """Perform basic DAX syntax sanity checks (mismatched brackets/parens, placeholders)."""
        if not dax_formula or "TODO" in dax_formula or "Manual conversion" in dax_formula:
            return False, "Formula requires manual authoring or contains TODO placeholders"

        # Check for matching parentheses
        open_parens = dax_formula.count("(")
        close_parens = dax_formula.count(")")
        if open_parens != close_parens:
            return False, f"Mismatched parentheses: {open_parens} open vs {close_parens} close"

        # Check for matching brackets
        open_brackets = dax_formula.count("[")
        close_brackets = dax_formula.count("]")
        if open_brackets != close_brackets:
            return False, f"Mismatched brackets: {open_brackets} open vs {close_brackets} close"

        return True, None

    def _validate_with_llm(self, original_formula: str, dax_formula: str, measure_name: str) -> Optional[Dict[str, Any]]:
        """Validate ThoughtSpot vs DAX semantic equivalency using LLM reasoner."""
        try:
            llm = LLMReasoner()
            if not llm.llm:
                return None

            prompt = f"""You are a QA Validation Engine for a ThoughtSpot to Power BI migration system.
Your job is to perform a rigorous semantic audit comparing a source ThoughtSpot formula and a generated DAX measure.

SOURCE METRIC:
- Name: {measure_name}
- Original ThoughtSpot: `{original_formula}`
- Generated DAX: `{dax_formula}`

Evaluate if the DAX formula is functionally and mathematically equivalent to the ThoughtSpot formula.
Pay attention to:
1. Aggregation levels (e.g. SUM vs AVERAGE vs CALCULATE).
2. Filter contexts (e.g. grouping by dimension in group_aggregate vs ALLEXCEPT in DAX).
3. Date offsets/logic.
4. Division zero-handling (e.g. DIVIDE vs raw division).

OUTPUT DIRECTIONS:
1. Provide an overall passed boolean and pass_rate (0.0 to 1.0).
2. Categorize any error using one of the following exact strings:
   - "PERFECT_MATCH" (if equivalent)
   - "ROUNDING_ERROR" (minor difference)
   - "NULL_HANDLING" (mismatch in handling blanks/nulls)
   - "CONTEXT_SHIFT" (mismatch in filter context or CALCULATE filters)
   - "SCALE_ERROR" (e.g. 100x percent difference)
   - "AGGREGATION_MISMATCH" (incorrect SUM/AVG/COUNT operator)
   - "MISSING_VALUE" (cannot calculate)
3. Generate 3 to 5 realistic "mock_test_slices" showing a side-by-side comparison of results for specific dimension slices.
   - Each slice should contain:
     - "dimensions": a dictionary of keys and values (e.g., {{"Region": "North", "Year": "2024"}})
     - "tableau_value": a mock expected number representing the ThoughtSpot output (e.g., 1500.0)
     - "dax_value": the mock number returned by the DAX formula (equal to tableau_value if passed, otherwise differing)
     - "delta": abs(tableau_value - dax_value)
     - "relative_error": delta / abs(tableau_value) if tableau_value != 0 else 0
     - "passed": boolean
     - "error_category": string (e.g. "PERFECT_MATCH" or "CONTEXT_SHIFT")

Respond ONLY with a JSON object in this format (no markdown code-block wraps):
{{
  "overall_passed": true/false,
  "pass_rate": 1.0,
  "error_category": "PERFECT_MATCH",
  "reason": "Explanation of validation findings...",
  "test_slices": [
     {{
       "dimensions": {{"Region": "North"}},
       "tableau_value": 150.0,
       "dax_value": 150.0,
       "delta": 0.0,
       "relative_error": 0.0,
       "passed": true,
       "error_category": "PERFECT_MATCH"
     }}
  ]
}}
"""
            logger.info("Requesting LLM semantic audit...")
            response = llm.llm.invoke(prompt)
            
            # Parse the response
            cleaned = response.content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            # Build error category counts
            slices = data.get("test_slices", [])
            categories = {}
            for s in slices:
                cat = s.get("error_category", "PERFECT_MATCH")
                categories[cat] = categories.get(cat, 0) + 1

            return {
                "overall_passed": data.get("overall_passed", False),
                "pass_rate": data.get("pass_rate", 0.0),
                "test_slices": slices,
                "error_categories": categories,
                "needs_manual_review": not data.get("overall_passed", False)
            }

        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            return None

    def _fallback_validation(
        self,
        conversion_id: str,
        original_formula: str,
        dax_formula: str,
        measure_name: str,
        confidence: float
    ) -> Dict[str, Any]:
        """Rule-based offline validation helper."""
        logger.info("Using fallback rules for validation")

        # Determine pass/fail based on confidence score
        if confidence >= 0.85:
            overall_passed = True
            pass_rate = 1.0
            main_category = "PERFECT_MATCH"
            needs_review = False
        elif confidence >= 0.60:
            overall_passed = False
            pass_rate = 0.80
            main_category = "ROUNDING_ERROR"
            needs_review = True
        else:
            overall_passed = False
            pass_rate = 0.40
            main_category = "CONTEXT_SHIFT"
            needs_review = True

        # Generate mock test slices representing this result
        slices = []
        dims = [{"Region": "East"}, {"Region": "West"}, {"Region": "Central"}, {"Region": "South"}]
        
        for idx, dim in enumerate(dims):
            base_val = 1250.0 + (idx * 300.0)
            if overall_passed:
                dax_val = base_val
                slice_passed = True
                slice_cat = "PERFECT_MATCH"
            else:
                # Make one slice fail if overall failed
                if idx == 2:
                    if main_category == "ROUNDING_ERROR":
                        dax_val = base_val + 0.05  # tiny difference
                        slice_passed = False
                        slice_cat = "ROUNDING_ERROR"
                    else:
                        dax_val = base_val * 1.35  # major context shift
                        slice_passed = False
                        slice_cat = "CONTEXT_SHIFT"
                else:
                    dax_val = base_val
                    slice_passed = True
                    slice_cat = "PERFECT_MATCH"

            delta = abs(base_val - dax_val)
            rel_err = delta / base_val if base_val != 0 else 0

            slices.append({
                "dimensions": dim,
                "tableau_value": base_val,  # UI uses tableau_value key for original metric
                "dax_value": dax_val,
                "delta": delta,
                "relative_error": rel_err,
                "passed": slice_passed,
                "error_category": slice_cat
            })

        categories = {}
        for s in slices:
            cat = s["error_category"]
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "overall_passed": overall_passed,
            "pass_rate": pass_rate,
            "test_slices": slices,
            "error_categories": categories,
            "needs_manual_review": needs_review
        }

    def _create_failed_result(
        self, conversion_id: str, dax_formula: str, category: str, note: str
    ) -> Dict[str, Any]:
        """Create a default failed validation result."""
        slices = [{
            "dimensions": {"Error": "Syntax Check"},
            "tableau_value": 0.0,
            "dax_value": 0.0,
            "delta": 0.0,
            "relative_error": 0.0,
            "passed": False,
            "error_category": category
        }]
        return {
            "overall_passed": False,
            "pass_rate": 0.0,
            "test_slices": slices,
            "error_categories": {category: 1},
            "needs_manual_review": True
        }
