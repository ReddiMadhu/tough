"""
Model Enhancement Agent - Detects when Power BI model changes are needed for converted ThoughtSpot formulas.
"""
from enum import Enum
from typing import Dict, List, Any, Optional
from loguru import logger


class EnhancementType(str, Enum):
    INDEX_COLUMN = "INDEX_COLUMN"
    DATE_TABLE = "DATE_TABLE"
    SORT_COLUMN = "SORT_COLUMN"
    CALCULATED_TABLE = "CALCULATED_TABLE"
    HELPER_MEASURE = "HELPER_MEASURE"
    NONE = "NONE"


class ModelEnhancementAgent:
    """
    Analyzes ThoughtSpot formulas to recommend structural Power BI model changes.
    """

    def __init__(self):
        logger.info("Model Enhancement Agent initialized for ThoughtSpot")

    def assess(self, original_formula: str, dax_formula: str, calc_name: str, table_name: str = "Table") -> Optional[Dict[str, Any]]:
        """
        Check formula patterns and return a ModelEnhancement recommendation if needed.
        """
        formula_upper = original_formula.upper()

        # Pattern 1: DYNAMIC GROUPING (query_groups())
        if "QUERY_GROUPS()" in formula_upper:
            return {
                "enhancement_type": EnhancementType.CALCULATED_TABLE.value,
                "description": f"Formula '{calc_name}' uses query_groups(), which dynamically calculates values based on visual columns. "
                               "In Power BI, this context-aware aggregation requires a calculated table using SUMMARIZE or a dynamic helper table.",
                "priority": "HIGH",
                "related_calc_name": calc_name,
                "dax_code": f"""
-- Suggested Calculated Table for dynamic grouping:
Grouped_{calc_name} = 
SUMMARIZE(
    '{table_name}',
    '{table_name}'[GroupColumn1],  -- Replace with visual group column
    "Grouped_Value", {dax_formula.split('=', 1)[1].strip() if '=' in dax_formula else dax_formula}
)
""".strip(),
                "m_script": None
            }

        # Pattern 2: CUMULATIVE SUM (cumulative_sum())
        if "CUMULATIVE_SUM(" in formula_upper or "CUMULATIVE_AVERAGE(" in formula_upper:
            return {
                "enhancement_type": EnhancementType.DATE_TABLE.value,
                "description": f"Formula '{calc_name}' performs a cumulative time-series calculation. "
                               "Power BI requires a dedicated Date Dimension Table to ensure proper time intelligence and sorting.",
                "priority": "MEDIUM",
                "related_calc_name": calc_name,
                "dax_code": f"""
-- Cumulative Measure using a Date table:
{calc_name}_Cumulative = 
CALCULATE(
    SUM('{table_name}'[Amount]), -- Replace with target field
    FILTER(
        ALL('DateTable'[Date]),
        'DateTable'[Date] <= MAX('DateTable'[Date])
    )
)
""".strip(),
                "m_script": self._generate_date_table_m()
            }

        # Pattern 3: MOVING AVERAGE (moving_average())
        if "MOVING_AVERAGE(" in formula_upper:
            return {
                "enhancement_type": EnhancementType.INDEX_COLUMN.value,
                "description": f"Formula '{calc_name}' calculates a moving average window, which requires sequential row indices. "
                               "Power BI models benefit from a sequential index column in Power Query to define sliding window intervals.",
                "priority": "MEDIUM",
                "related_calc_name": calc_name,
                "dax_code": f"""
-- Sliding Window moving average using Index column:
{calc_name}_MovingAvg = 
VAR CurrentIndex = '{table_name}'[RowIndex]
VAR StartIndex = CurrentIndex - 30 -- Adjust window size (e.g. 30 rows)
RETURN
    AVERAGEX(
        FILTER(
            ALL('{table_name}'),
            '{table_name}'[RowIndex] >= StartIndex && '{table_name}'[RowIndex] <= CurrentIndex
        ),
        {dax_formula.split('=', 1)[1].strip() if '=' in dax_formula else dax_formula}
    )
""".strip(),
                "m_script": f"""
// Power Query M to add a Row Index to {table_name}:
let
    Source = #"{table_name}_Source",
    Sorted = Table.Sort(Source, {{"Date", Order.Ascending}}),
    AddedIndex = Table.AddIndexColumn(Sorted, "RowIndex", 1, 1, Int64.Type)
in
    AddedIndex
""".strip()
            }

        return None

    def _generate_date_table_m(self) -> str:
        """Create Date Table Power Query M script."""
        return """
// Date Table generator:
let
    StartDate = #date(2020, 1, 1),
    EndDate = #date(2030, 12, 31),
    NumberOfDays = Duration.Days(EndDate - StartDate) + 1,
    DateList = List.Dates(StartDate, NumberOfDays, #duration(1, 0, 0, 0)),
    DateTable = Table.FromList(DateList, Splitter.SplitByNothing(), {"Date"}),
    ChangedType = Table.TransformColumnTypes(DateTable, {{"Date", type date}}),
    AddYear = Table.AddColumn(ChangedType, "Year", each Date.Year([Date]), Int64.Type),
    AddMonth = Table.AddColumn(AddYear, "Month", each Date.Month([Date]), Int64.Type),
    AddMonthName = Table.AddColumn(AddMonth, "MonthName", each Date.MonthName([Date]), type text),
    AddDay = Table.AddColumn(AddMonthName, "Day", each Date.Day([Date]), Int64.Type)
in
    AddDay
""".strip()
