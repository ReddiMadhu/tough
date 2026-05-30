"""
LLM Semantic Reasoning Layer for ThoughtSpot to Power BI Migration.
Uses Gemini (or Azure OpenAI / OpenAI compatible endpoint) via LangChain.
"""

import os
import json
from typing import Dict, Any, Optional, List
from loguru import logger

from api.config import config


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
            result = json.loads(response.content)
            
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
            result = json.loads(response.content)
            return result.get("narrative", "")
        except Exception as e:
            logger.error(f"LLM narrative generation failed: {e}")
            return None
