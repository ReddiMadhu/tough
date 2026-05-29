"""dax_formatter.py — lightweight DAX formatting utilities."""
import re


def format_dax(dax: str) -> str:
    """
    Apply basic formatting to a DAX expression.
    - Normalize whitespace
    - Ensure measure name has = sign
    """
    if not dax:
        return dax
    # Collapse multiple spaces
    dax = re.sub(r"  +", "  ", dax)
    return dax.strip()


def extract_measure_name(dax: str) -> str:
    """Extract measure name from 'MeasureName = expr' format."""
    if " = " in dax:
        return dax.split(" = ")[0].strip().strip("'\"")
    return ""
