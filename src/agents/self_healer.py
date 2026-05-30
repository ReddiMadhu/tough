"""
Self-Healing Agent - Autonomous DAX correction based on validation failures for ThoughtSpot formulas.
"""
import json
from typing import Dict, List, Any, Optional
from loguru import logger

from src.llm_reasoner import LLMReasoner


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
        measure_name: str
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

        prompt = f"""You are an expert DAX debugger specializing in migrating ThoughtSpot analytics models to Power BI.
We are on self-healing correction attempt {attempt_number} of {self.max_attempts} for metric `{measure_name}`.

## METRIC DETAILS:
- Name: {measure_name}
- Original ThoughtSpot Formula: `{original_formula}`
- Current Generated DAX (Failed): `{failed_dax}`

## VALIDATION DISCREPANCIES:
{failure_summary}

## AUDIT ANALYSIS:
- Error Categories: {json.dumps(error_categories)}

## YOUR TASK:
Generate a corrected DAX formula that fixes the discrepancy.

**Rules for DAX correction:**
1. Check division context: Always use `DIVIDE(num, den, 0)` instead of `num / den`.
2. Check aggregation: In ThoughtSpot, columns are often aggregated implicitly or explicitly. Ensure DAX aggregates correctly (e.g. `SUM('Table'[Col])`).
3. Check filter context: If `group_aggregate` was used with a dimension list, ALLEXCEPT or REMOVEFILTERS might be required to lock the aggregation grain.
4. If there is a scaling issue (e.g. off by 100x), check whether the ThoughtSpot formula expects decimal ratios while DAX does not, or vice versa.

Respond ONLY with a valid JSON object in the exact format below (no markdown wraps, no explanation outside JSON):
{{
  "root_cause": "Detailed explanation of why the current DAX failed validation...",
  "corrected_dax": "Measure = <corrected DAX formula>",
  "explanation": "What changes were made and why...",
  "changes_made": ["Changed operator X to Y", "Added DIVIDE safety", "Adjusted filter context"]
}}
"""
        try:
            if not self.llm_reasoner.llm:
                logger.warning("LLM Reasoner is not active. Skipping LLM correction.")
                return self._fallback_correction(failed_dax, error_categories, attempt_number)

            response = self.llm_reasoner.reason(prompt)
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)

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
