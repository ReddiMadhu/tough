"""relationship_builder.py — builds Power BI relationship definitions from joins."""
from typing import Dict, Any, List


def build_pbi_relationships(joins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert ThoughtSpot join definitions to Power BI relationship objects."""
    CARDINALITY_MAP = {
        "many_to_one": "manyToOne",
        "many-to-one": "manyToOne",
        "one_to_many": "oneToMany",
        "one-to-many": "oneToMany",
        "one_to_one": "oneToOne",
        "one-to-one": "oneToOne",
        "many_to_many": "manyToMany",
        "many-to-many": "manyToMany",
    }
    CROSSFILTER_MAP = {
        "INNER": "bothDirections",
        "LEFT_OUTER": "oneDirection",
        "RIGHT_OUTER": "oneDirection",
        "FULL_OUTER": "bothDirections",
    }

    result = []
    for join in joins:
        result.append({
            "name": join.get("name", ""),
            "fromTable": join.get("left_table", ""),
            "fromColumn": join.get("left_column", ""),
            "toTable": join.get("right_table", ""),
            "toColumn": join.get("right_column", ""),
            "cardinality": CARDINALITY_MAP.get(
                join.get("cardinality", "").lower().replace("_", "-"), "manyToOne"
            ),
            "crossFilteringBehavior": CROSSFILTER_MAP.get(
                join.get("join_type", "LEFT_OUTER"), "oneDirection"
            ),
            "isActive": True,
        })
    return result
