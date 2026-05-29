"""model_builder.py — builds a clean summary dict from intermediate model for API responses."""
from typing import Dict, Any


def build_summary(intermediate_model: Dict[str, Any]) -> Dict[str, Any]:
    """Build a lightweight summary of the intermediate model for status responses."""
    tables = intermediate_model.get("tables", [])
    columns = intermediate_model.get("columns", [])
    joins = intermediate_model.get("joins", [])
    worksheets = intermediate_model.get("worksheets", [])

    formulas = [c for c in columns if c.get("formula")]

    return {
        "table_count": len(tables),
        "column_count": len(columns),
        "formula_count": len(formulas),
        "join_count": len(joins),
        "visualization_count": len(worksheets),
        "model_type": intermediate_model.get("model_type", "FLAT"),
        "tables": [t["name"] for t in tables],
    }
