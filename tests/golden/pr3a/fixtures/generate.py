"""Regenerate deterministic PR3A golden artifacts from graph fixtures."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from cpp_audit.dependency import build_dependency_graph, extract_output_slice
from cpp_audit.expression import extract_expression, render_expression
from tests.graph_fixtures import base_ir, edge, node
from tests.test_dependency_graph import explicit_fold_ir, if_ir, map_ir

ROOT = Path(__file__).resolve().parent


def _with_source(ir: dict[str, Any], source: str) -> dict[str, Any]:
    result = deepcopy(ir); result["translation_unit"] = source
    for collection in (result["nodes"], result["dependency_edges"]):
        for item in collection: item["source_span"]["file"] = source
    return result


def artifacts(name: str, ir: dict[str, Any]) -> dict[str, str]:
    source = f"tests/golden/pr3a/fixtures/{name}/source.cpp"
    implementation = _with_source(ir, source)
    graph = build_dependency_graph(implementation)
    output_slice = extract_output_slice(graph)
    expression = extract_expression(implementation)
    return {
        "implementation-ir.json": json.dumps(implementation, indent=2, sort_keys=True) + "\n",
        "dependency-graph.json": json.dumps(graph, indent=2, sort_keys=True) + "\n",
        "output-slice.json": json.dumps(output_slice, indent=2, sort_keys=True) + "\n",
        "expected-expression-ir.json": json.dumps(expression, indent=2, sort_keys=True) + "\n",
        "expected-equation.tex": render_expression(expression, "latex"),
        "expected-equation.txt": render_expression(expression, "unicode"),
        "expected-report.md": render_expression(expression, "markdown"),
    }


def main() -> None:
    cases = {"map": map_ir(), "if_then_else": if_ir(), "fold_left": explicit_fold_ir()}
    for name, ir in cases.items():
        directory = ROOT / name
        for filename, content in artifacts(name, ir).items():
            (directory / filename).write_text(content, encoding="utf-8")


if __name__ == "__main__": main()
