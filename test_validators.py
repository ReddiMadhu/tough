"""Quick validation test for the new schema checker and naked column detector."""
from src.validation.validation_engine import ValidationEngine

ve = ValidationEngine()

# Test 1: Valid schema reference
p, e = ve.check_schema_references(
    "SUM('Sales'[Revenue])",
    {'Revenue': 'Sales'},
    {},
    set()
)
print(f"Test 1 (valid ref): passed={p}, errors={e}")

# Test 2: Invalid table
p, e = ve.check_schema_references(
    "SUM('FakeTable'[Revenue])",
    {'Revenue': 'Sales'},
    {},
    set()
)
print(f"Test 2 (bad table): passed={p}, errors={e}")

# Test 3: Naked column outside aggregation
p2, w = ve.check_naked_columns(
    "'Sales'[Revenue]",
    {'Revenue': 'Sales'},
    {},
    set()
)
print(f"Test 3 (naked col): passed={p2}, warnings={w}")

# Test 4: Column inside SUM (should pass)
p3, w2 = ve.check_naked_columns(
    "SUM('Sales'[Revenue])",
    {'Revenue': 'Sales'},
    {},
    set()
)
print(f"Test 4 (in SUM): passed={p3}, warnings={w2}")

# Test 5: Column inside SUMX iterator (should pass — row context is valid)
p4, w3 = ve.check_naked_columns(
    "SUMX('Sales', 'Sales'[Revenue] * 'Sales'[Quantity])",
    {'Revenue': 'Sales', 'Quantity': 'Sales'},
    {},
    set()
)
print(f"Test 5 (in SUMX): passed={p4}, warnings={w3}")

# Test 6: Measure reference (should pass without aggregation)
p5, w4 = ve.check_naked_columns(
    "DIVIDE([Total Revenue], [Total Cost], 0)",
    {'Revenue': 'Sales'},
    {},
    {'Total Revenue', 'Total Cost'}
)
print(f"Test 6 (measure ref): passed={p5}, warnings={w4}")

print("\nAll tests completed!")
