"""
Logic Graph Builder — constructs dependency DAG from ThoughtSpot formulas.
"""
import re
import json
from enum import Enum
from typing import List, Dict, Any, Set, Tuple, Optional
from loguru import logger

class CalculationType(str, Enum):
    MEASURE = "MEASURE"
    CALCULATED_COLUMN = "CALCULATED_COLUMN"
    LOD_EXPRESSION = "LOD_EXPRESSION"
    TABLE_CALCULATION = "TABLE_CALCULATION"
    PARAMETER = "PARAMETER"
    STANDARD = "STANDARD"

class Granularity(str, Enum):
    ROW_LEVEL = "ROW_LEVEL"
    AGGREGATE = "AGGREGATE"
    TABLE = "TABLE"

class CalculationNode:
    """Represents a node in the dependency graph."""
    def __init__(
        self,
        calc_id: str,
        name: str,
        formula: str,
        calc_type: CalculationType,
        granularity: Granularity,
        depends_on: List[str],
        dependency_level: int = 0,
        used_in_worksheets: List[str] = None,
        source_object: str = "",
        source_object_type: str = "",
    ):
        self.calc_id = calc_id
        self.name = name
        self.formula = formula
        self.calc_type = calc_type
        self.granularity = granularity
        self.depends_on = depends_on
        self.dependency_level = dependency_level
        self.used_in_worksheets = used_in_worksheets or []
        self.source_object = source_object
        self.source_object_type = source_object_type
        self.depends_on_metadata: Dict[str, Any] = {}

class LogicGraphBuilder:
    """Builds a dependency DAG from ThoughtSpot intermediate model columns and formulas."""
    
    def __init__(self):
        self.calculations: Dict[str, CalculationNode] = {}
        self.base_fields: Set[str] = set()
        self.edges: List[Tuple[str, str]] = []

    def build_graph(
        self,
        model: Dict[str, Any],
        base_field_metadata: Dict[str, Dict[str, Any]]
    ):
        """
        Build the dependency graph from the parsed intermediate model.
        """
        logger.info("Building logic graph from intermediate ThoughtSpot model")
        
        self.base_fields = set(base_field_metadata.keys())
        worksheets = model.get("worksheets", [])

        # Extract only columns that are formulas
        formula_columns = [
            c for c in model.get("columns", [])
            if c.get("formula")
        ]

        # Step 1: Create nodes for all formula columns
        for col in formula_columns:
            name = col.get("caption") or col.get("internal_name")
            if not name:
                continue

            formula = col.get("formula", "")
            
            # Determine type & granularity
            formula_type = col.get("formula_type", "STANDARD")
            role = col.get("role", "measure")
            
            if formula_type == "GROUP_AGGREGATE":
                calc_type = CalculationType.LOD_EXPRESSION
                granularity = Granularity.AGGREGATE
            elif formula_type == "WINDOW_CALC":
                calc_type = CalculationType.TABLE_CALCULATION
                granularity = Granularity.TABLE
            elif role == "measure" or any(kw in formula.lower() for kw in ("sum(", "average(", "count(", "unique_count(", "max(", "min(")):
                calc_type = CalculationType.MEASURE
                granularity = Granularity.AGGREGATE
            else:
                calc_type = CalculationType.CALCULATED_COLUMN
                granularity = Granularity.ROW_LEVEL

            node = CalculationNode(
                calc_id=name,
                name=name,
                formula=formula,
                calc_type=calc_type,
                granularity=granularity,
                depends_on=[],
                source_object=col.get("source_object", ""),
                source_object_type=col.get("source_object_type", "Model")
            )
            self.calculations[name] = node

        # Step 2: Parse formulas to identify dependencies and add edges
        for name, node in self.calculations.items():
            # Extract bracketed dependencies: e.g. [Sales] / [Profit]
            deps = re.findall(r'\[([^\]]+)\]', node.formula)
            # Deduplicate while preserving order
            seen = set()
            dependencies = []
            for d in deps:
                d_clean = d.strip()
                if d_clean and d_clean not in seen:
                    seen.add(d_clean)
                    dependencies.append(d_clean)

            node.depends_on = dependencies

            # Build metadata for each dependency
            for dep in dependencies:
                if dep in self.calculations:
                    dep_node = self.calculations[dep]
                    node.depends_on_metadata[dep] = {
                        "field_name": dep,
                        "field_type": "CALCULATED_MEASURE" if dep_node.calc_type == CalculationType.MEASURE else "CALCULATED_COLUMN",
                        "is_aggregated": dep_node.calc_type == CalculationType.MEASURE
                    }
                    self.edges.append((dep, name))
                elif dep in self.base_fields:
                    meta = base_field_metadata.get(dep, {})
                    node.depends_on_metadata[dep] = {
                        "field_name": dep,
                        "field_type": "BASE_COLUMN",
                        "is_aggregated": False
                    }
                    self.edges.append((dep, name))
                else:
                    node.depends_on_metadata[dep] = {
                        "field_name": dep,
                        "field_type": "UNKNOWN",
                        "is_aggregated": False
                    }

        # Step 3: Populate worksheet usage
        for ws in worksheets:
            ws_name = ws.get("name", "Unknown Sheet")
            
            # Helper to clean bracketed names
            def clean(f):
                return f.strip("[]")

            ws_fields = [clean(f) for f in ws.get("rows", []) + ws.get("cols", [])]
            for field in ws_fields:
                if field in self.calculations:
                    if ws_name not in self.calculations[field].used_in_worksheets:
                        self.calculations[field].used_in_worksheets.append(ws_name)

        # Step 4: Topological sort to compute levels
        self._calculate_dependency_levels()

    def _calculate_dependency_levels(self):
        """Topological sort using Kahn's algorithm to determine dependency levels."""
        # Build graph adj list
        adj = {}
        in_degree = {}
        
        # Initialize
        for name in self.calculations:
            adj[name] = []
            in_degree[name] = 0
            
        for name, node in self.calculations.items():
            for dep in node.depends_on:
                if dep in self.calculations:
                    adj[dep].append(name)
                    in_degree[name] += 1

        # Queue nodes with in-degree = 0
        queue = [name for name, deg in in_degree.items() if deg == 0]
        
        # Assign levels
        levels = {name: 1 for name in self.calculations}
        
        visited_count = 0
        while queue:
            curr = queue.pop(0)
            visited_count += 1
            curr_level = levels[curr]
            
            for succ in adj[curr]:
                levels[succ] = max(levels[succ], curr_level + 1)
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        # Set levels in nodes
        for name, node in self.calculations.items():
            node.dependency_level = levels[name]

        if visited_count < len(self.calculations):
            logger.warning("Cycle detected in ThoughtSpot formula dependencies!")

    def to_dict(self) -> Dict[str, Any]:
        """Export as dictionary for SQLite storage."""
        nodes = []
        for name, node in self.calculations.items():
            nodes.append({
                "calc_id": node.calc_id,
                "calc_name": node.name,
                "calc_formula": node.formula,
                "calc_type": node.calc_type.value,
                "dependency_level": node.dependency_level,
                "depends_on": node.depends_on,
                "depends_on_metadata": node.depends_on_metadata,
                "used_in_worksheets": ",".join(node.used_in_worksheets),
                "source_object": node.source_object,
                "source_object_type": node.source_object_type
            })
            
        edges = [{"source": u, "target": v} for u, v in self.edges]
        
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_calculations": len(self.calculations),
                "total_dependencies": len(self.edges),
                "max_dependency_level": max((n.dependency_level for n in self.calculations.values()), default=0),
            }
        }

    def export_for_reactflow(self) -> Dict[str, Any]:
        """Export ReactFlow representation."""
        level_groups = {}
        for node in self.calculations.values():
            level = node.dependency_level
            if level not in level_groups:
                level_groups[level] = []
            level_groups[level].append(node)
            
        reactflow_nodes = []
        
        node_colors = {
            CalculationType.MEASURE: "#f59e0b",         # orange
            CalculationType.CALCULATED_COLUMN: "#3b82f6", # blue
            CalculationType.LOD_EXPRESSION: "#8b5cf6",     # purple
            CalculationType.TABLE_CALCULATION: "#ec4899",  # pink
            CalculationType.PARAMETER: "#10b981",          # green
            CalculationType.STANDARD: "#6b7280"            # gray
        }

        for level, group in level_groups.items():
            # Sort node by name for layout stability
            group.sort(key=lambda n: n.name)
            for idx, node in enumerate(group):
                x = level * 280
                y = idx * 110
                
                is_lod = node.calc_type == CalculationType.LOD_EXPRESSION
                
                reactflow_nodes.append({
                    "id": node.calc_id,
                    "type": "calculationNode",
                    "data": {
                        "label": node.name,
                        "formula": node.formula[:50] + "..." if len(node.formula) > 50 else node.formula,
                        "calcType": node.calc_type.value,
                        "level": node.dependency_level,
                        "isLOD": is_lod
                    },
                    "position": {"x": x, "y": y},
                    "style": {
                        "background": node_colors.get(node.calc_type, "#6b7280"),
                        "color": "white",
                        "border": "2px solid" if is_lod else "1px solid",
                        "borderColor": "#8b5cf6" if is_lod else "#d1d5db"
                    }
                })

        reactflow_edges = []
        for name, node in self.calculations.items():
            for dep in node.depends_on:
                if dep in self.calculations:
                    reactflow_edges.append({
                        "id": f"{dep}-{name}",
                        "source": dep,
                        "target": name,
                        "type": "smoothstep",
                        "animated": False
                    })
                    
        return {
            "nodes": reactflow_nodes,
            "edges": reactflow_edges
        }
