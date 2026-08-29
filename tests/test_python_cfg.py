from __future__ import annotations

from pathlib import Path
import json

import jsonschema
import pytest

from cpp_audit import AuditMode, audit_python, build_python_cfg, execute_audit


def write_source(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cfg_case.py"; path.write_text(text, encoding="utf-8"); return path


def cfg(tmp_path: Path, body: str, output: str = "y"):
    return build_python_cfg(write_source(tmp_path, "def f(x):\n" + body), function="f", output=output)


def edge_kinds(graph) -> set[str]: return {edge.kind for edge in graph.edges}


def test_cfg_json_schema(tmp_path: Path):
    graph = cfg(tmp_path, "    if x > 0:\n        y=1\n    else:\n        y=2\n    return y\n")
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "python-control-flow-graph.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(graph.to_dict(), schema)


def test_while_and_loop_back_edge(tmp_path: Path):
    graph = cfg(tmp_path, "    y=0\n    i=0\n    while i < x:\n        y += i\n        i += 1\n    return y\n")
    assert {"LoopBodyEdge", "LoopExitEdge", "LoopBackEdge"} <= edge_kinds(graph)
    assert graph.summary["loop_count"] == 1
    assert graph.summary["termination_status"] == "TERMINATION_PROVEN_MONOTONIC_COUNTER"


def test_unproven_while_is_fail_closed(tmp_path: Path):
    graph = cfg(tmp_path, "    y=0\n    while x:\n        y += 1\n    return y\n")
    assert "TERMINATION_UNPROVEN" in graph.summary["statuses"]
    assert graph.summary["cfg_status"] == "CFG_PARTIALLY_RESOLVED"


def test_break_and_continue_edges(tmp_path: Path):
    graph = cfg(tmp_path, "    y=0\n    for i in range(x):\n        if i == 2:\n            continue\n        if i == 5:\n            break\n        y += i\n    return y\n")
    assert {"BreakEdge", "ContinueEdge"} <= edge_kinds(graph)


def test_early_and_multiple_returns_become_branch(tmp_path: Path):
    path = write_source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x if x > 0 else -x')\ndef f(x):\n    if x > 0:\n        return x\n    return -x\n")
    result = audit_python(path, function="f", output="y", verify_lean=False, mode="REPORT_ONLY")
    assert result.implementation["outputs"][0]["expression"]["op"] == "IfThenElse"
    assert result.comparison["match"]
    assert build_python_cfg(path, function="f", output="y").summary["cfg_status"] == "CFG_RESOLVED"


def test_nested_branch_and_merge_points(tmp_path: Path):
    graph = cfg(tmp_path, "    if x > 0:\n        if x > 2:\n            y=2\n        else:\n            y=1\n    else:\n        y=0\n    return y\n")
    assert graph.summary["branch_count"] == 2
    assert sum(block.kind == "MergePoint" for block in graph.blocks) >= 2
    assert "BRANCH_MERGE_RESOLVED" in graph.summary["statuses"]


def test_unknown_branch_merge_is_critical(tmp_path: Path):
    graph = cfg(tmp_path, "    y=0\n    if x > 0:\n        y=1\n    return y\n")
    assert "BRANCH_MERGE_UNRESOLVED" in graph.summary["statuses"]
    assert graph.summary["unresolved_control_flow"]


def test_loop_with_branch_is_preserved(tmp_path: Path):
    graph = cfg(tmp_path, "    y=0\n    for i in range(x):\n        if i > 1:\n            y += i\n        else:\n            y += 1\n    return y\n")
    assert graph.summary["loop_count"] == 1 and graph.summary["branch_count"] == 1


def test_conditional_accumulation_is_fold_with_predicate(tmp_path: Path):
    path = write_source(tmp_path, "def f(x, mask, n):\n    s=0\n    for i in range(n):\n        if mask[i]:\n            s += x[i]\n    return s\n")
    expression = audit_python(path, function="f", output="s", verify_lean=False,
                              mode="REPORT_ONLY").implementation["outputs"][0]["expression"]
    assert expression["op"] == "FoldLeft"
    assert expression["body"]["op"] == "IfThenElse"
    assert expression["body"]["else"] == {"op": "Constant", "value": 0}


def test_loop_control_effects_on_output_fail_closed(tmp_path: Path):
    graph = cfg(tmp_path, "    y=0\n    for i in range(x):\n        if i == 2:\n            continue\n        y += i\n    return y\n")
    assert graph.summary["cfg_status"] == "CFG_PARTIALLY_RESOLVED"
    assert "CONTROL_FLOW_PARTIALLY_RESOLVED" in graph.summary["statuses"]
    assert graph.summary["continue_count"] == 1


@pytest.mark.parametrize("expression, expected", [
    ("[v*v for v in x]", "Map"),
    ("{v*v for v in x}", "Map"),
    ("{v: v*v for v in x}", "Map"),
])
def test_comprehensions_lower_to_map(tmp_path: Path, expression: str, expected: str):
    path = write_source(tmp_path, f"def f(x):\n    y={expression}\n    return y\n")
    result = audit_python(path, function="f", output="y", verify_lean=False, mode="REPORT_ONLY")
    assert result.implementation["outputs"][0]["expression"]["op"] == expected


def test_conditional_comprehension_is_filter_then_map(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    y=[v*v for v in x if v > 0]\n    return y\n")
    expression = audit_python(path, function="f", output="y", verify_lean=False, mode="REPORT_ONLY").implementation["outputs"][0]["expression"]
    assert expression["op"] == "Map" and expression["iterable"]["op"] == "Filter"


def test_generator_sum_is_finite_fold_semantics(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    y=sum(v*v for v in x)\n    return y\n")
    expression = audit_python(path, function="f", output="y", verify_lean=False, mode="REPORT_ONLY").implementation["outputs"][0]["expression"]
    assert expression["op"] == "FoldLeft" and expression["operation"] == "Add"


def test_indexed_assignment_and_numpy_style_mutation(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    x[0] = x[0] + 1\n    y=x\n    return y\n")
    result = audit_python(path, function="f", output="y", verify_lean=False, mode="REPORT_ONLY")
    assert result.implementation["outputs"][0]["expression"]["op"] == "IndexedStateUpdate"
    graph = build_python_cfg(path, function="f", output="y")
    assert graph.mutations[0].kind == "IndexedStateUpdate"


def test_indexed_in_place_arithmetic(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    x[0] += 2\n    return x\n")
    result = audit_python(path, function="f", output="x", verify_lean=False, mode="REPORT_ONLY")
    assert result.implementation["outputs"][0]["expression"]["mutation"] == "indexed_in_place_arithmetic"


def test_numpy_indexed_mutation_keeps_previous_contract_ir(tmp_path: Path):
    path = write_source(tmp_path, "import numpy as np\ndef f(x):\n    arr=np.array(x)\n    arr[0]=2\n    return arr\n")
    expression = audit_python(path, function="f", output="arr", verify_lean=False, mode="REPORT_ONLY").implementation["outputs"][0]["expression"]
    assert expression["op"] == "IndexedStateUpdate"
    assert expression["previous_state"]["reference_contract"]["callable"] == "numpy.array"


def test_ellipsis_array_assignment_is_preserved(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    x[...] = 0\n    return x\n")
    expression = audit_python(path, function="f", output="x", verify_lean=False, mode="REPORT_ONLY").implementation["outputs"][0]["expression"]
    assert expression["op"] == "IndexedStateUpdate"
    assert expression["indices"][0] == {"op": "Constant", "value": "Ellipsis"}


def test_alias_resolved_mutation_targets_original(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    a=x\n    b=a\n    b[0]=2\n    return x\n")
    graph = build_python_cfg(path, function="f", output="x")
    assert graph.mutations[0].canonical_target == "x"
    assert graph.mutations[0].status == "MUTATION_RESOLVED"
    expression = audit_python(path, function="f", output="x", verify_lean=False, mode="REPORT_ONLY").implementation["outputs"][0]["expression"]
    assert expression["op"] == "IndexedStateUpdate" and expression["target"] == "x"


def test_alias_unresolved_negative_case(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    a=choose(x)\n    a[0]=2\n    return a\n")
    graph = build_python_cfg(path, function="f", output="a")
    assert graph.mutations[0].status == "POTENTIAL_ALIAS"
    assert graph.summary["cfg_status"] == "CFG_PARTIALLY_RESOLVED"


def test_unknown_mutation_target_negative_case(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    y=factory(x)\n    factory(x)[0]=2\n    return y\n")
    graph = build_python_cfg(path, function="f", output="y")
    assert graph.mutations[0].status == "MUTATION_TARGET_UNRESOLVED"
    assert graph.summary["unresolved_control_flow"][0]["code"] == "UNKNOWN_MUTATION_TARGET"


def test_list_append_and_extend_mutations(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    y=[]\n    y.append(x)\n    y.extend([x])\n    return y\n")
    graph = build_python_cfg(path, function="f", output="y")
    assert [item.kind for item in graph.mutations] == ["ListAppend", "ListExtend"]


def test_attribute_mutation_is_preserved(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    x.value=2\n    return x\n")
    graph = build_python_cfg(path, function="f", output="x")
    assert graph.mutations[0].kind == "AttributeStateUpdate"


def test_try_except_output_is_unresolved_exception_path(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    try:\n        y=10/x\n    except ValueError:\n        y=0\n    return y\n")
    graph = build_python_cfg(path, function="f", output="y")
    assert "ExceptionEdge" in edge_kinds(graph)
    assert graph.summary["exception_paths"][0]["code"] == "EXCEPTION_PATH_UNRESOLVED"


def test_try_finally_is_in_cfg(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    y=0\n    try:\n        y=x\n    finally:\n        y=y+1\n    return y\n")
    graph = build_python_cfg(path, function="f", output="y")
    assert any("finally" not in (block.statements[0]["source"] if block.statements else "") for block in graph.blocks)
    assert graph.summary["exception_path_count"] == 0


def test_unused_exception_path_excluded_from_critical_findings(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    try:\n        unused=10/x\n    except ValueError:\n        unused=0\n    y=x+1\n    return y\n")
    graph = build_python_cfg(path, function="f", output="y")
    assert not graph.summary["exception_paths"]


def test_enumerate_and_zip_loops_are_preserved(tmp_path: Path):
    path = write_source(tmp_path, "def f(x):\n    y=0\n    for i,v in enumerate(x):\n        y += v\n    for a,b in zip(x,x):\n        y += a*b\n    return y\n")
    graph = build_python_cfg(path, function="f", output="y")
    assert graph.summary["loop_count"] == 2
    assert "LOOP_SEMANTICS_PRESERVED" in graph.summary["statuses"]


def test_report_only_certificate_completes_with_unresolved_while(tmp_path: Path):
    path = write_source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x')\ndef f(x):\n    y=0\n    while x:\n        y += 1\n        x -= 1\n    return y\n")
    certificate = execute_audit(path, inputs={"x": 3}, function="f", output="y", mode=AuditMode.REPORT_ONLY, verify_lean=False)
    assert certificate.status == "VERIFICATION_FAILED"
    assert certificate.output["scalar"] == 3
    assert certificate.control_flow_summary["termination_status"] == "TERMINATION_UNPROVEN"


def test_synthetic_masked_mutation_e2e(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests" / "fixtures" / "synthetic_masked_accumulation.py"
    certificate = execute_audit(fixture, inputs={"values": [2, 5, 7, 11], "mask": [1, 0, 3, 0], "n": 4},
                                function="accumulate_masked_values", output="accepted_total",
                                verify_lean=True, lean_file=tmp_path / "masked.lean")
    assert certificate.status == "LEAN_KERNEL_VERIFIED"
    assert certificate.output["scalar"] == 9
    assert certificate.control_flow_summary["loop_count"] == 1
    assert certificate.control_flow_summary["mutation_count"] == 1
    assert certificate.comparison["match"]
