"""visual_mapper.py — maps ThoughtSpot chart types to Power BI visual types."""
from typing import Dict

# ThoughtSpot mark_type → Power BI visualType
VISUAL_TYPE_MAP: Dict[str, str] = {
    "bar":       "clusteredColumnChart",
    "line":      "lineChart",
    "area":      "areaChart",
    "pie":       "pieChart",
    "donut":     "donutChart",
    "circle":    "scatterChart",
    "text":      "card",
    "map":       "map",
    "square":    "treemap",
    "funnel":    "funnel",
    "waterfall": "waterfallChart",
    "automatic": "clusteredColumnChart",
}

# ThoughtSpot ts_chart_type → Power BI visualType (raw mapping per plan §4.7)
TS_CHART_TYPE_MAP: Dict[str, str] = {
    "COLUMN":        "clusteredColumnChart",
    "BAR":           "clusteredBarChart",
    "LINE":          "lineChart",
    "AREA":          "areaChart",
    "PIE":           "pieChart",
    "DONUT":         "donutChart",
    "SCATTER":       "scatterChart",
    "STACKED_COLUMN":"stackedColumnChart",
    "STACKED_BAR":   "stackedBarChart",
    "STACKED_AREA":  "stackedAreaChart",
    "KPI":           "card",
    "TABLE":         "tableEx",
    "PIVOT_TABLE":   "pivotTable",
    "GEO_AREA":      "map",
    "GEO_BUBBLE":    "map",
    "TREEMAP":       "treemap",
    "FUNNEL":        "funnel",
    "WATERFALL":     "waterfallChart",
    "HEATMAP":       "matrix",
    "SANKEY":        "custom",
    "CANDLESTICK":   "custom",
}


def ts_chart_to_pbi_visual(ts_chart_type: str) -> str:
    """Convert a ThoughtSpot chart type string to a Power BI visual type string."""
    return TS_CHART_TYPE_MAP.get(ts_chart_type.upper() if ts_chart_type else "", "clusteredColumnChart")


def mark_to_pbi_visual(mark_type: str) -> str:
    """Convert an intermediate mark_type to a Power BI visual type string."""
    return VISUAL_TYPE_MAP.get(mark_type.lower() if mark_type else "automatic", "clusteredColumnChart")


def is_custom_visual(ts_chart_type: str) -> bool:
    """Return True if the chart type requires a custom Power BI visual (no built-in equivalent)."""
    return TS_CHART_TYPE_MAP.get(ts_chart_type.upper(), "") == "custom"
