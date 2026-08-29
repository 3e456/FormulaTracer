"""Build the Python semantic-owner dependency graph and strongly connected components."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "output" / "feature_freeze" / "python-semantic-inventory.json"
OUTPUT = ROOT / "output" / "native_migration" / "ownership-graph.json"


def imported_modules(path: Path, package: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[:-node.level]
                module = ".".join([*base, node.module or ""]).rstrip(".")
            else:
                module = node.module or ""
            if module:
                result.add(module)
    return result


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    active: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in active:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component = []
            while True:
                item = stack.pop()
                active.remove(item)
                component.append(item)
                if item == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components, key=lambda item: (min(item), len(item)))


def main() -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    owners = {item["module"]: item for item in inventory["modules"]
              if item["classification"] == "PYTHON_SEMANTIC_SOURCE_OF_TRUTH"}
    graph = {name: set() for name in owners}
    for name, record in owners.items():
        path = ROOT / record["path"]
        for imported in imported_modules(path, name):
            if imported in owners:
                graph[name].add(imported)
            else:
                prefix = imported + "."
                graph[name].update(candidate for candidate in owners if candidate.startswith(prefix))
    components = strongly_connected(graph)
    component_index = {module: index for index, component in enumerate(components) for module in component}
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "policy": "Kernel/SCC migration; module count is not a completion claim.",
        "nodes": [{"module": name, "kernel": record["semantic_kernel"],
                   "classification": record["classification"],
                   "retirement_status": "OPEN", "scc": component_index[name]}
                  for name, record in sorted(owners.items())],
        "edges": [{"source": source, "target": target}
                  for source in sorted(graph) for target in sorted(graph[source])],
        "strongly_connected_components": [
            {"scc": index, "modules": component,
             "kernels": sorted({owners[module]["semantic_kernel"] for module in component})}
            for index, component in enumerate(components)
        ],
        "by_kernel": {
            kernel: sorted(name for name, record in owners.items()
                           if record["semantic_kernel"] == kernel)
            for kernel in "ABCDEF"
        },
        "python_semantic_source_of_truth_modules": len(owners),
        "all_retired": not owners,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"nodes": len(payload["nodes"]), "edges": len(payload["edges"]),
                      "sccs": len(components), "by_kernel": {key: len(value) for key, value in payload["by_kernel"].items()}}, indent=2))


if __name__ == "__main__":
    main()
