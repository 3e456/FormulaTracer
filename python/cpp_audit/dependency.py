"""Validation and output slicing for explicit Clang-derived dependency graphs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .core import SCHEMA_VERSION

EDGE_KINDS = {
    "DEFINES", "READS", "WRITES", "VALUE_DEPENDS_ON", "INDEX_DEPENDS_ON",
    "CONDITION_DEPENDS_ON", "LOOP_BOUND_DEPENDS_ON", "PREVIOUS_ACCUMULATOR_VALUE",
    "CONTROL_GUARDS", "RESULT_OF",
}


def _diagnostic(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _output_nodes(nodes: list[dict[str, Any]]) -> list[str]:
    result = []
    for node in nodes:
        semantic = node.get("attributes", {}).get("semantic_kind")
        symbol = node.get("resolved_symbol") or node.get("attributes", {}).get("resolved_symbol")
        if semantic in {"Store", "Return"} or symbol == "std::transform":
            result.append(node["id"])
    return sorted(result)


def build_dependency_graph(ir: dict[str, Any]) -> dict[str, Any]:
    """Validate graph structure without guessing missing dependency facts."""
    nodes = ir.get("nodes", [])
    edges = ir.get("dependency_edges", [])
    diagnostics: list[dict[str, Any]] = []
    node_by_id = {node.get("id"): node for node in nodes if node.get("id")}
    if len(node_by_id) != len(nodes):
        diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "node IDs must be present and unique"))
    edge_ids: set[str] = set()
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for edge in edges:
        edge_id = edge.get("edge_id")
        if not edge_id or edge_id in edge_ids:
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "edge IDs must be present and unique"))
        edge_ids.add(str(edge_id))
        if edge.get("kind") not in EDGE_KINDS:
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "unknown edge kind", edge_id=edge_id))
        source, target = edge.get("source_node_id"), edge.get("target_node_id")
        if source not in node_by_id or target not in node_by_id:
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "edge endpoint does not exist", edge_id=edge_id))
            continue
        incoming[target].append(edge)
        adjacency[source].append((target, edge))

    outputs = _output_nodes(nodes)
    if not outputs:
        diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "no Store or Return output node exists"))
    output_locations = {node_by_id[node_id].get("attributes", {}).get("output_base", "<return>")
                        for node_id in outputs}
    if len(output_locations) > 1:
        diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "ambiguous output location",
                                       detail_code="AMBIGUOUS_OUTPUT_LOCATION"))

    for node in nodes:
        semantic, node_id = node.get("attributes", {}).get("semantic_kind"), node.get("id")
        roles = {(edge.get("kind"), edge.get("argument_role")) for edge in incoming.get(node_id, [])}
        if semantic == "Store" and not ({kind for kind, _ in roles} >= {"WRITES", "VALUE_DEPENDS_ON"}):
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "Store needs write target and value", node_id=node_id))
        if semantic in {"BinaryOperation", "Comparison"} and not {"lhs", "rhs"}.issubset({role for _, role in roles}):
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "binary node needs lhs and rhs", node_id=node_id))
        if semantic == "Conditional" and "condition" not in {role for _, role in roles}:
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "Conditional needs condition dependency", node_id=node_id))
        if semantic == "Loop" and not {"index", "lower", "upper"}.issubset({role for _, role in roles}):
            diagnostics.append(_diagnostic("INVALID_DEPENDENCY_GRAPH", "Loop needs index, lower, and upper dependencies", node_id=node_id))

    # Tarjan SCC: dependency cycles are legal only when explicitly marked as an
    # accumulator recurrence or when a Loop node participates.
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}

    def strong_connect(vertex: str) -> None:
        nonlocal index
        indices[vertex] = low[vertex] = index; index += 1
        stack.append(vertex); on_stack.add(vertex)
        for target, _ in adjacency.get(vertex, []):
            if target not in indices:
                strong_connect(target); low[vertex] = min(low[vertex], low[target])
            elif target in on_stack:
                low[vertex] = min(low[vertex], indices[target])
        if low[vertex] != indices[vertex]: return
        component: list[str] = []
        while stack:
            item = stack.pop(); on_stack.remove(item); component.append(item)
            if item == vertex: break
        cyclic = len(component) > 1 or any(target == vertex for target, _ in adjacency.get(vertex, []))
        if not cyclic: return
        members = set(component)
        component_edges = [edge for source in members for target, edge in adjacency.get(source, []) if target in members]
        permitted = (any(edge.get("kind") == "PREVIOUS_ACCUMULATOR_VALUE" for edge in component_edges) or
                     any(node_by_id[item].get("attributes", {}).get("semantic_kind") == "Loop" for item in members))
        if not permitted:
            diagnostics.append(_diagnostic("UNSUPPORTED_DEPENDENCY_CYCLE",
                                           "cycle is not an explicit accumulator or Loop recurrence",
                                           node_ids=sorted(members)))

    for node_id in node_by_id:
        if node_id not in indices: strong_connect(node_id)
    status = "DEPENDENCY_GRAPH_INVALID" if diagnostics else "DEPENDENCY_GRAPH_BUILT"
    return {"schema_version": SCHEMA_VERSION, "status": status, "nodes": nodes, "edges": edges,
            "output_node_ids": outputs, "diagnostics": diagnostics}


def extract_output_slice(graph: dict[str, Any]) -> dict[str, Any]:
    """Walk dependency edges backwards from every resolved output."""
    if graph.get("status") != "DEPENDENCY_GRAPH_BUILT":
        return {"schema_version": SCHEMA_VERSION, "status": "EXPRESSION_EXTRACTION_FAILED",
                "output_node_ids": graph.get("output_node_ids", []), "node_ids": [], "edge_ids": [],
                "nodes": [], "edges": [], "diagnostics": graph.get("diagnostics", [])}
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph["edges"]: incoming[edge["target_node_id"]].append(edge)
    reached = set(graph["output_node_ids"])
    selected_edges: dict[str, dict[str, Any]] = {}
    pending = list(reached)
    while pending:
        target = pending.pop()
        for edge in incoming.get(target, []):
            selected_edges[edge["edge_id"]] = edge
            source = edge["source_node_id"]
            if source not in reached: reached.add(source); pending.append(source)
    diagnostics: list[dict[str, Any]] = []
    unresolved = [edge["edge_id"] for edge in selected_edges.values() if edge.get("confidence") != "RESOLVED"]
    if unresolved:
        diagnostics.append(_diagnostic("UNRESOLVED_OUTPUT_DEPENDENCY",
                                       "unresolved dependency reaches an audited output", edge_ids=sorted(unresolved)))
    unknown = [node_id for node_id in reached if node_by_id[node_id].get("effect") == "Unknown"]
    if unknown:
        diagnostics.append(_diagnostic("NON_NUMERIC_DEPENDENCY_IN_AUDITED_SLICE",
                                       "unknown effect reaches an audited output", node_ids=sorted(unknown)))
    status = "EXPRESSION_EXTRACTION_FAILED" if diagnostics else "OUTPUT_SLICE_EXTRACTED"
    return {"schema_version": SCHEMA_VERSION, "status": status,
            "output_node_ids": graph["output_node_ids"], "node_ids": sorted(reached),
            "edge_ids": sorted(selected_edges),
            "nodes": [node_by_id[node_id] for node_id in sorted(reached)],
            "edges": [selected_edges[edge_id] for edge_id in sorted(selected_edges)],
            "diagnostics": diagnostics}
