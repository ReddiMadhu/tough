import sqlite3

db_path = "../migrations.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Find migrations matching prefix
cursor.execute("SELECT migration_id, status, formulas_count FROM migrations WHERE migration_id LIKE '%c5244784592e%'")
migrations = cursor.fetchall()
print("Matching migrations:")
for m in migrations:
    print(m)

# If found, print all conversions
if migrations:
    target_id = migrations[0][0]
    cursor.execute("SELECT measure_name, original_formula, dax_formula, confidence FROM ts_conversions WHERE migration_id = ?", (target_id,))
    conversions = cursor.fetchall()
    print(f"\nConversions count in DB for {target_id}: {len(conversions)}")
    for i, c in enumerate(conversions):
        print(f"{i+1}. Name: {c[0]}")
        print(f"   Original: {c[1]}")
        print(f"   DAX: {c[2]}")
        print(f"   Confidence: {c[3]}")
conn.close()
