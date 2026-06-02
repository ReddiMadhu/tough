import sqlite3
import json
from pathlib import Path

db_path = "../migrations.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get migrations
cursor.execute("SELECT migration_id, status FROM migrations")
migrations = cursor.fetchall()
print("All migrations:")
for m in migrations:
    print(m)

if migrations:
    latest_mig = migrations[-1][0]
    print("\nTargeting migration ID:", latest_mig)
    
    # Path to intermediate model
    export_dir = Path("exports")
    model_file = export_dir / latest_mig / f"{latest_mig}_intermediate_model.json"
    if not model_file.exists():
        model_file = export_dir / latest_mig / f"model_{latest_mig}.json"
        
    print("Checking file at:", model_file.resolve())
    if model_file.exists():
        with open(model_file, "r", encoding="utf-8") as f:
            model = json.load(f)
        worksheets = model.get("worksheets", [])
        print(f"\nWorksheets count: {len(worksheets)}")
        for i, w in enumerate(worksheets):
            print(f"  {i+1}. Name: {w.get('name')}, Title: {w.get('title')}, Source: {w.get('source_liveboard')}")
    else:
        print("Model file not found.")
conn.close()
