"""
Filter Parameter Converter - ThoughtSpot TML filters to Power BI DAX conversions
"""
import re
from typing import Dict, Any, List


class FilterParameterConverter:
    """
    Converts ThoughtSpot TML filter parameters to DAX filter expressions.
    """

    def __init__(self):
        pass

    def convert_filter(self, table: str, column: str, operator: str, values: List[Any]) -> str:
        """
        Convert a filter definition to DAX FILTER expression.
        """
        dax_col = f"'{table}'[{column}]"
        op_upper = operator.upper()

        if op_upper == "IN":
            val_strs = [self._format_value(v) for v in values]
            return f"{dax_col} IN {{ {', '.join(val_strs)} }}"
        elif op_upper == "NOT_IN":
            val_strs = [self._format_value(v) for v in values]
            return f"NOT({dax_col} IN {{ {', '.join(val_strs)} }})"
        elif op_upper == "BETWEEN":
            if len(values) >= 2:
                v1 = self._format_value(values[0])
                v2 = self._format_value(values[1])
                return f"{dax_col} >= {v1} && {dax_col} <= {v2}"
        elif op_upper == "EQ" or op_upper == "EQUAL":
            v = self._format_value(values[0]) if values else "BLANK()"
            return f"{dax_col} = {v}"
        elif op_upper == "NEQ" or op_upper == "NOT_EQUAL":
            v = self._format_value(values[0]) if values else "BLANK()"
            return f"{dax_col} <> {v}"
        elif op_upper == "GT":
            v = self._format_value(values[0]) if values else "BLANK()"
            return f"{dax_col} > {v}"
        elif op_upper == "GE" or op_upper == "GREATER_OR_EQUAL":
            v = self._format_value(values[0]) if values else "BLANK()"
            return f"{dax_col} >= {v}"
        elif op_upper == "LT":
            v = self._format_value(values[0]) if values else "BLANK()"
            return f"{dax_col} < {v}"
        elif op_upper == "LE" or op_upper == "LESS_OR_EQUAL":
            v = self._format_value(values[0]) if values else "BLANK()"
            return f"{dax_col} <= {v}"

        # Default fallback
        v = self._format_value(values[0]) if values else "BLANK()"
        return f"{dax_col} = {v}"

    def _format_value(self, val: Any) -> str:
        if isinstance(val, str):
            return f'"{val}"'
        elif val is None:
            return "BLANK()"
        return str(val)
