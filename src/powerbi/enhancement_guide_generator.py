"""
Model Enhancement Guide Generator - ThoughtSpot version.
Creates markdown guides for required model improvements.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger

from src.powerbi.model_enhancement_agent import EnhancementType


class EnhancementGuideGenerator:
    """
    Generate markdown documentation for model enhancements.
    """

    def generate_guide(self, enhancements: List[Dict[str, Any]], output_dir: Path) -> Optional[Path]:
        """
        Generate markdown file guide from enhancements.
        """
        if not enhancements:
            logger.info("No enhancements required")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        guide_path = output_dir / "MODEL_ENHANCEMENTS_REQUIRED.md"

        content = f"""# Power BI Model Enhancements Required
        
**Total Enhancements Suggested:** {len(enhancements)}

---

## 📋 Overview
Complex metrics migrated from ThoughtSpot often require structural enhancements at the Power BI data model layer.
This guide details custom columns, indices, and calendar configurations to complete the transition.

### Recommended Changes

"""
        for i, enh in enumerate(enhancements, 1):
            etype = enh.get("enhancement_type", "OTHER")
            calc_name = enh.get("related_calc_name", "Measure")
            content += f"""
### ⚙️ Enhancement {i}: {calc_name}
- **Type:** {etype}
- **Description:** {enh.get("description")}
- **Priority:** {enh.get("priority", "MEDIUM")}

"""
            if enh.get("m_script"):
                content += f"""
#### Power Query M Script:
```m
{enh.get("m_script")}
```
"""
            if enh.get("dax_code"):
                content += f"""
#### Target DAX implementation:
```dax
{enh.get("dax_code")}
```
"""
            content += "\n---\n"

        content += """
## 🎯 Quick Reference
### Adding Index Columns in Power Query
1. Open **Transform Data** in Power BI Desktop.
2. Select your fact/dimension table.
3. Click **Add Column** tab → **Index Column** → **From 1**.
4. Save and Apply.

### Setting Up a Date Table
1. Go to Power Query Advanced Editor → New Query → Blank Query.
2. Paste the provided M Script.
3. Mark the new table as a Date table.
"""

        guide_path.write_text(content, encoding="utf-8")
        logger.info(f"Generated model enhancement guide: {guide_path}")
        return guide_path
