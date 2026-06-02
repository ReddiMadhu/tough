"""
LLM Semantic Reasoning Layer for ThoughtSpot to Power BI Migration.
Uses Gemini (or Azure OpenAI / OpenAI compatible endpoint) via LangChain.
"""

import os
import json
import time
from typing import Dict, Any, Optional, List
from loguru import logger
from pydantic import BaseModel, Field

from api.config import config


class FormulaTranslationResponse(BaseModel):
    dax_formula: str = Field(description="The translated DAX formula including the measure name, e.g. 'Measure = SUM(...)' or just the expression.")
    confidence: float = Field(description="Confidence level between 0.0 and 1.0", ge=0.0, le=1.0)
    pattern: str = Field(description="Pattern identified, e.g. 'AI_TRANSLATION'")
    notes: List[str] = Field(default_factory=list, description="Implementation notes and assumptions")
    requires_review: bool = Field(description="Flag to indicate if manual verification is needed")


class ModelNarrativeResponse(BaseModel):
    narrative: str = Field(description="A markdown-formatted summary with Executive Overview, Semantic Architecture, Key Metrics, and Data Governance.")


class DaxCorrectionResponse(BaseModel):
    root_cause: str = Field(description="Detailed explanation of why the current DAX failed validation")
    corrected_dax: str = Field(description="The corrected DAX formula, e.g., 'Measure = ...'")
    explanation: str = Field(description="What changes were made and why")
    changes_made: List[str] = Field(description="List of specific changes made")


class MockTestSlice(BaseModel):
    dimensions: Dict[str, str] = Field(description="Mock dimension slice, e.g. {'Region': 'North'}")
    tableau_value: Any = Field(description="Mock expected value from ThoughtSpot")
    source_value: Any = Field(description="Mock expected value from ThoughtSpot (alias)")
    dax_value: Any = Field(description="Mock value produced by the DAX formula")
    delta: Optional[float] = Field(None, description="Absolute difference between expected and dax values")
    relative_error: Optional[float] = Field(None, description="Relative error")
    passed: bool = Field(description="True if within acceptable epsilon delta")
    error_category: str = Field(description="Error category, e.g., 'PERFECT_MATCH', 'ROUNDING_ERROR', 'CONTEXT_SHIFT'")



class SemanticValidationResponse(BaseModel):
    overall_passed: bool = Field(description="True if the DAX formula matches the ThoughtSpot formula semantically")
    pass_rate: float = Field(description="Pass rate from 0.0 to 1.0", ge=0.0, le=1.0)
    error_category: str = Field(description="The primary error category, e.g. 'PERFECT_MATCH', 'AGGREGATION_MISMATCH', etc.")
    reason: str = Field(description="Explanation of the validation audit findings")
    test_slices: List[MockTestSlice] = Field(description="Mock test slices for validation verification")



def clean_and_validate_json(raw_response: str, model_cls: type[BaseModel]) -> BaseModel:
    """
    Cleans markdown backticks (like ```json ... ```) from LLM output,
    parses the JSON, and validates it against the provided Pydantic model.
    """
    cleaned = raw_response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    
    return model_cls.model_validate_json(cleaned)



class LLMReasoner:
    """
    LLM-based semantic reasoning and formula translation.
    Reuses configured credentials for Gemini / Azure OpenAI.
    """

    def __init__(self):
        self.api_key = config.AZURE_OPENAI_API_KEY
        self.endpoint = config.AZURE_OPENAI_ENDPOINT
        self.deployment = config.AZURE_OPENAI_DEPLOYMENT_NAME
        self.llm = None

        if not config.ENABLE_LLM_VALIDATION:
            logger.warning("LLM reasoning is disabled in configuration")
            return

        if not self.endpoint or not self.api_key:
            logger.warning(
                "Azure OpenAI / Gemini credentials not configured. "
                "LLM fallback translation will be skipped."
            )
            return

        # Initialize LangChain LLM
        try:
            from langchain_openai import ChatOpenAI

            self.llm = ChatOpenAI(
                model=self.deployment,
                api_key=self.api_key,
                base_url=self.endpoint,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
                model_kwargs={
                    "response_format": {"type": "json_object"}  # FORCE JSON MODE
                }
            )
            logger.info(f"LLM Semantic Reasoning Layer initialized successfully: {self.deployment}")

        except ImportError:
            logger.warning("langchain-openai is not installed. Fallback to offline regex.")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")

    def invoke(self, prompt: str) -> Any:
        """
        Execute a prompt against the LLM with rate-limiting sleep if configured.
        """
        if not self.llm:
            raise ValueError("LLM is not initialized")
        sleep_time = getattr(config, "LLM_SLEEP_TIME", 0.0)
        if sleep_time > 0:
            logger.info(f"Rate limit safety: sleeping for {sleep_time}s before LLM call")
            time.sleep(sleep_time)
        return self.llm.invoke(prompt)

    def reason(self, prompt: str) -> str:
        """
        Execute a raw prompt against the LLM and return the string content response.
        """
        response = self.invoke(prompt)
        return response.content

    def translate_formula(
        self, formula: str, measure_name: str, schema_context: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Translate a complex ThoughtSpot formula to Power BI DAX using LLM.
        """
        if not self.llm:
            return None

        prompt = f"""You are a world-class Business Intelligence engineer specializing in ThoughtSpot-to-Power BI DAX conversion.

---

## TASK
Translate the ThoughtSpot formula below into a clean, functionally identical Power BI DAX measure.

## INPUT
- **Measure Name**: `{measure_name}`
- **ThoughtSpot Formula**: `{formula}`

## SCHEMA CONTEXT (MANDATORY — use EXACT names from here)
{schema_context or "No schema context provided. Default to '[Column Name]' with table 'Table'."}

---

## DAX MEASURE RULES (Your translation MUST obey ALL of these)

### R1 — Aggregation Required
In DAX measures, ALL column references MUST be inside an aggregation: SUM(), AVERAGE(), COUNT(), DISTINCTCOUNT(), MIN(), MAX().
**Exception**: Inside iterators (SUMX, FILTER, AVERAGEX, ADDCOLUMNS) naked column refs are valid.

### R2 — DIVIDE Safety
ALL division MUST use `DIVIDE(numerator, denominator, 0)`. NEVER use raw `a / b`.

### R3 — Table Qualification
Columns: `'TableName'[ColumnName]` (with single-quoted table).
Measures: `[MeasureName]` (no table prefix).
NEVER invent or hallucinate table names.

### R4 — group_aggregate Translation
- `group_aggregate(sum(col), {{dim1, dim2}})` → `CALCULATE(SUM('T'[col]), ALLEXCEPT('T', 'T'[dim1], 'T'[dim2]))`
- `group_aggregate(sum(col), {{}})` (grand total) → `CALCULATE(SUM('T'[col]), ALL('T'))`
- `query_groups()` → NO DAX equivalent; output BLANK() with TODO comment.

### R5 — CALCULATE Filter Context
CALCULATE() filter arguments must be Boolean expressions or table functions (ALL, ALLEXCEPT, FILTER).

### R6 — Cumulative / Running Totals
`CALCULATE(SUM('T'[Col]), FILTER(ALL('T'[DateCol]), 'T'[DateCol] <= MAX('T'[DateCol])))`

### R7 — Moving Averages
`AVERAGEX(DATESINPERIOD('T'[Date], MAX('T'[Date]), -N, DAY), CALCULATE(SUM('T'[Value])))`

### R8 — Conditional Logic
`if(cond) then val else val` → `IF(condition, then_value, else_value)`
`and` → `&&`, `or` → `||`, `!=` → `<>`, `isnull()` → `ISBLANK()`, `ifnull(x,y)` → `IF(ISBLANK(x), y, x)`

### R9 — No Ghost Tables
Do NOT assume 'Date'[Date] exists unless in schema. Use actual date columns.

### R10 — VAR/RETURN
For complex formulas, use VAR to break down logic into named steps.

---

## TRANSLATION EXAMPLES

### Example 1 — Simple Aggregation
- **ThoughtSpot**: `sum(revenue)`
- **DAX**: `Total Revenue = SUM('Sales'[Revenue])`
- **Pattern**: DIRECT_AGG

### Example 2 — Group Aggregate (LOD)
- **ThoughtSpot**: `group_aggregate(sum(sales), {{region}})`
- **DAX**: `Regional Sales = CALCULATE(SUM('Sales'[Amount]), ALLEXCEPT('Sales', 'Sales'[Region]))`
- **Pattern**: CALCULATE_ALLEXCEPT

### Example 3 — Conditional with Division
- **ThoughtSpot**: `if (sum(revenue) > 0) then sum(profit) / sum(revenue) else 0`
- **DAX**: `Profit Margin = IF(SUM('Sales'[Revenue]) > 0, DIVIDE(SUM('Sales'[Profit]), SUM('Sales'[Revenue]), 0), 0)`
- **Pattern**: CONDITIONAL

### Example 4 — Percent of Total
- **ThoughtSpot**: `sum(sales) / group_sum(sales)`
- **DAX**: `Pct of Total = DIVIDE(SUM('Sales'[Amount]), CALCULATE(SUM('Sales'[Amount]), ALL('Sales')), 0)`
- **Pattern**: PERCENT_OF_TOTAL

---

## REASONING (Think step-by-step internally)
1. Parse the ThoughtSpot formula: what functions, columns, and logic does it use?
2. Map each ThoughtSpot function to its DAX equivalent using the rules above.
3. Resolve all column names against the SCHEMA CONTEXT.
4. Construct the DAX formula with proper table qualification and aggregation.
5. Verify against all 10 rules — especially R1 (no naked columns) and R2 (DIVIDE safety).

---

## OUTPUT FORMAT
Respond ONLY with a valid JSON object (no markdown wraps):
{{
  "dax_formula": "{measure_name} = <translated DAX>",
  "confidence": 0.0 to 1.0,
  "pattern": "AI_TRANSLATION",
  "notes": ["Brief note about translation choices", "Any warnings"],
  "requires_review": true or false
}}"""

        try:
            response = self.invoke(prompt)
            parsed_res = clean_and_validate_json(response.content, FormulaTranslationResponse)
            result = parsed_res.model_dump()
            
            # Format correction check
            dax = result.get("dax_formula", "")
            if dax and not dax.startswith(f"{measure_name} ="):
                result["dax_formula"] = f"{measure_name} = {dax}"

            logger.debug(f"LLM translated formula '{measure_name}' successfully")
            return result

        except Exception as e:
            logger.error(f"LLM translation failed for '{measure_name}': {e}")
            return None

    def generate_model_narrative(
        self, tables: List[Dict[str, Any]], relationships: List[Dict[str, Any]], conversions: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Generate a premium, business-level narrative summary of the migrated data model.
        """
        if not self.llm:
            return None

        # Format context briefly
        table_summary = []
        for t in tables:
            t_name = t.get("name", "")
            cols = [c.get("name", "") for c in t.get("column_details", [])]
            table_summary.append(f"Table '{t_name}' with columns: {cols}")

        rel_summary = []
        for r in relationships:
            rel_summary.append(
                f"'{r.get('from_table')}'[{r.get('from_column')}] {r.get('cardinality', 'N:1')} '{r.get('to_table')}'[{r.get('to_column')}]"
            )

        conv_summary = []
        for c in conversions:
            conv_summary.append(f"Measure '{c.get('measure_name')}' (DAX: {c.get('dax_formula')})")

        prompt = f"""You are a premium enterprise Business Intelligence consultant.
Analyze this newly migrated Power BI data model (originally migrated from ThoughtSpot TML files) and write a beautiful, professional, and insightful Executive Business Narrative.

DATA MODEL DETAILS:
- Tables:
  {chr(10).join(table_summary[:10])}
- Relationships:
  {chr(10).join(rel_summary[:10])}
- Converted Measures:
  {chr(10).join(conv_summary[:15])}

INSTRUCTIONS:
Respond ONLY with a valid JSON object. No explanation, no markdown wraps.
The executive summary must be detailed and highly professional.
JSON Format:
{{
  "narrative": "A rich markdown summary containing: \\n\\n### Executive Overview\\n[Overview of the model]\\n\\n### Semantic Architecture & Core Business Story\\n[Describe the business domain, e.g., Sales Dashboard, Customer Inventory, and what story the relationships tell]\\n\\n### Key Metrics Developed\\n[List core measures and their business impact]\\n\\n### Data Governance & Audit Recommendations\\n[Data quality warnings, nullable column flags, relationship check suggestions]"
}}"""

        try:
            response = self.invoke(prompt)
            parsed_res = clean_and_validate_json(response.content, ModelNarrativeResponse)
            return parsed_res.narrative
        except Exception as e:
            logger.error(f"LLM narrative generation failed: {e}")
            return None
