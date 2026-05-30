"""
LLM Semantic Reasoning Layer for ThoughtSpot to Power BI Migration.
Uses Gemini (or Azure OpenAI / OpenAI compatible endpoint) via LangChain.
"""

import os
import json
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

    def reason(self, prompt: str) -> str:
        """
        Execute a raw prompt against the LLM and return the string content response.
        """
        if not self.llm:
            raise ValueError("LLM is not initialized")
        response = self.llm.invoke(prompt)
        return response.content

    def translate_formula(
        self, formula: str, measure_name: str, schema_context: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Translate a complex ThoughtSpot formula to Power BI DAX using LLM.
        """
        if not self.llm:
            return None

        prompt = f"""You are a senior Business Intelligence architect and an expert in converting analytics systems from ThoughtSpot to Power BI.
Translate the following ThoughtSpot formula into a clean, functionally identical Power BI DAX formula.

CONTEXT & RULES:
1. In ThoughtSpot, columns are often referenced directly by name (e.g. `sum(sales)`).
2. In Power BI DAX, measures MUST have a table qualifier for columns (e.g. `SUM('Table'[sales])`) but MUST NOT have a table qualifier for other measures.
3. If division is involved, use the safe DAX `DIVIDE(numerator, denominator, 0)` pattern to prevent divide-by-zero errors.
4. If checking for null values, use `ISBLANK(...)` instead of `isnull` or `ifnull`.
5. Support aggregations (`SUM`, `AVERAGE`, `COUNT`, `DISTINCTCOUNT`, `MIN`, `MAX`).
6. Support conditional statements (`IF`, `SWITCH`).
7. For cumulative totals, use `CALCULATE(..., FILTER(ALL(...), ...))`.
8. STRICT SCHEMA ADHERENCE: NEVER hallucinate or invent table names. You MUST use the exact table names provided in the SCHEMA CONTEXT. If the schema specifies that 'revenue' is in the 'Sales' table, write `'Sales'[Revenue]`, NOT `'Revenue'[Revenue]`.
9. NO GHOST DATE TABLES: For time intelligence functions (like `SAMEPERIODLASTYEAR`), do NOT assume a generic `'Date'[Date]` table exists unless it is provided in the schema context. Use an existing date column from the schema if possible, or add a note if missing.

SCHEMA CONTEXT (Use this to resolve correct column and table names if applicable):
{schema_context or "No schema context provided. Default to '[Column Name]' formatting with standard table 'Table'."}

FORMULA TO CONVERT:
- Measure Name: {measure_name}
- Original ThoughtSpot Formula: {formula}

INSTRUCTIONS:
Respond ONLY with a valid JSON object in the exact format shown below. No explanation text, no markdown block wrappers.
JSON Format:
{{
  "dax_formula": "translated DAX string (e.g., \\"Measure_Name = SUM('Table'[Column])\\")",
  "confidence": 0.0 to 1.0 (float reflecting translation certainty),
  "pattern": "AI_TRANSLATION",
  "notes": ["Brief note about translation choices", "Any filter context warnings"],
  "requires_review": true or false
}}"""

        try:
            response = self.llm.invoke(prompt)
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
            response = self.llm.invoke(prompt)
            parsed_res = clean_and_validate_json(response.content, ModelNarrativeResponse)
            return parsed_res.narrative
        except Exception as e:
            logger.error(f"LLM narrative generation failed: {e}")
            return None
