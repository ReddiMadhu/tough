import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).resolve().parent))

from src.orchestrator import MigrationOrchestrator
from api.config import config

def test_migration():
    demo_dir = Path("demo_data")
    file_names = [
        "Table_Customers.tml",
        "Table_Products.tml",
        "Table_Sales.tml",
        "Model_SalesAnalysis.tml",
        "Liveboard_ExecutiveDashboard.tml"
    ]
    file_paths = [str(demo_dir / f) for f in file_names]
    
    print("Files to migrate:", file_paths)
    
    orchestrator = MigrationOrchestrator(
        db_path=config.DATABASE_PATH,
        export_dir=config.EXPORT_DIR
    )
    
    migration_id = "test_run_12345"
    orchestrator.execute(migration_id, file_paths)
    print("Migration finished successfully!")

if __name__ == "__main__":
    test_migration()
