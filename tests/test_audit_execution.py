from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from cpp_audit import (AuditMode, ConstantDependencyGraph, execute_audit,
                       extract_constant_graph, render_latex_certificate,
                       summarize_value, write_certificate)
from cpp_audit.audit_execution import ConstantNode
from cpp_audit.core import AuditError


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_weighted_reduction.py"
SYNTHETIC_INPUTS = {"samples": [[2, 3], [4, 5]], "weights": [1000, 2000]}


def source(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "calculation.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_literal_constant_and_unused_slice_exclusion():
    graph = extract_constant_graph("def f(x):\n    unused = 99\n    y = x * 2\n    return y\n", function="f", output="y")
    assert [node.kind for node in graph.nodes] == ["LITERAL_CONSTANT"]
    assert graph.nodes[0].resolved_value == 2


def test_named_and_default_constants():
    graph = extract_constant_graph("def f(x, scale=4):\n    offset = 3\n    y = x * scale + offset\n    return y\n", function="f", output="y")
    assert {node.symbol: node.kind for node in graph.nodes} == {"scale": "DEFAULT_ARGUMENT", "offset": "NAMED_CONSTANT"}


def test_config_and_file_constants_keep_provenance():
    text = "def f(config, table, x):\n    y = x * config['factor'] + table['bias']\n    return y\n"
    graph = extract_constant_graph(text, function="f", output="y",
        config_constants={"config['factor']": {"symbol": "factor", "value": 0.25, "source": "settings.toml"}},
        file_parameters={"table['bias']": {"symbol": "bias", "value": 2, "source": "parameters.json"}})
    assert {node.kind for node in graph.nodes} == {"CONFIG_CONSTANT", "FILE_LOADED_PARAMETER"}
    assert {node.source["source"] for node in graph.nodes} == {"settings.toml", "parameters.json"}


def test_derived_constant_graph_and_exact_value():
    text = "def f(x):\n    b = 2\n    c = 3.5\n    a = b * c\n    e = 14\n    d = a / e\n    y = x * d\n    return y\n"
    graph = extract_constant_graph(text, function="f", output="y")
    d = next(node for node in graph.nodes if node.symbol == "d")
    assert d.dependencies == ["a", "e"]
    assert d.exact_rational == {"numerator": 1, "denominator": 2}
    assert {tuple(edge.values()) for edge in graph.edges} >= {("b", "a"), ("c", "a"), ("a", "d"), ("e", "d")}


def test_multi_step_definition_is_not_collapsed():
    graph = extract_constant_graph("def f(x):\n    s=1000\n    days=365\n    a=s/days\n    y=x*a\n    return y\n", function="f", output="y")
    a = next(node for node in graph.nodes if node.symbol == "a")
    assert a.definition["op"] == "Divide"
    assert a.exact_rational == {"numerator": 200, "denominator": 73}
    assert a.expanded_exact_rational == {"numerator": 1000, "denominator": 365}
    assert a.approximate_value == pytest.approx(1000 / 365)


def test_float_literal_separates_mathematical_and_runtime_views():
    graph = extract_constant_graph("def f(x):\n    c=3.5\n    y=x*c\n    return y\n", function="f", output="y")
    c = next(node for node in graph.nodes if node.symbol == "c")
    assert c.exact_rational == {"numerator": 7, "denominator": 2}
    assert c.approximate_value == 3.5
    assert c.exactness == "EXACT_RATIONAL_WITH_FLOAT_PRESENTATION"


def test_constant_dependency_cycle_rejected():
    with pytest.raises(AuditError, match="CONSTANT_DEPENDENCY_CYCLE"):
        extract_constant_graph("def f(x):\n    a=b\n    b=a\n    y=x*a\n    return y\n", function="f", output="y")


def test_graph_model_rejects_manual_cycle():
    blank = {"op": "Constant", "value": 1}
    nodes = [ConstantNode("a", "DERIVED_CONSTANT", blank, ["b"], 1, {"numerator": 1, "denominator": 1}, {"numerator": 1, "denominator": 1}, None, "EXACT_RATIONAL", {}),
             ConstantNode("b", "DERIVED_CONSTANT", blank, ["a"], 1, {"numerator": 1, "denominator": 1}, {"numerator": 1, "denominator": 1}, None, "EXACT_RATIONAL", {})]
    with pytest.raises(AuditError, match="CONSTANT_DEPENDENCY_CYCLE"):
        ConstantDependencyGraph(nodes, [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]).validate()


def test_scalar_and_array_summaries():
    assert summarize_value("x", 3, "test")["scalar"] == 3
    array = summarize_value("x", [[1, 2], [3, 4]], "test")
    assert array["shape"] == [2, 2]
    assert array["summary"]["minimum"] == 1 and len(array["sha256"]) == 64


def test_large_array_is_not_fully_embedded():
    summary = summarize_value("x", list(range(100)), "test")
    assert "values" not in summary and len(summary["summary"]["sample"]) == 8


def test_synthetic_fixture_separates_theory_and_implementation():
    certificate = execute_audit(SYNTHETIC_FIXTURE, inputs=SYNTHETIC_INPUTS, function="calculate_weighted_score",
                                output="weighted_score", verify_lean=False)
    assert certificate.theory["ir"] is not certificate.implementation
    assert certificate.comparison["match"]
    assert certificate.output["values"] == [8.0, 14.0]


def test_symbol_correspondence_and_library_provenance():
    certificate = execute_audit(SYNTHETIC_FIXTURE, inputs=SYNTHETIC_INPUTS, function="calculate_weighted_score",
                                output="weighted_score", verify_lean=False)
    assert certificate.comparison["mapping"]["symbols"]["dim(samples,1)"] == "I"
    contract = certificate.library_contracts[0]
    assert contract["callable"] == "numpy.sum"
    assert contract["provenance"]["reference_status"] == "LEAN_VERIFIED_MAPPING"
    assert next(claim for claim in certificate.lean["claims"] if claim["claim"] == "LIBRARY_SEMANTIC_MAPPING")["status"] == "REFERENCE_CONTRACT_ONLY"


def test_latex_has_required_sections_and_symbolic_constant():
    certificate = execute_audit(SYNTHETIC_FIXTURE, inputs=SYNTHETIC_INPUTS, function="calculate_weighted_score",
                                output="weighted_score", verify_lean=False)
    latex = render_latex_certificate(certificate)
    for heading in ("Audit Target", "Inputs", "Given Constants", "Derived Constants", "Theory Formula",
                    "Numeric Representation", "Floating-Point Equivalence", "Parallel Numerical Semantics", "Implementation Formula", "Symbol Correspondence", "Output / Result",
                    "Library Contracts Used", "Lean Verification", "Overall Verification Status"):
        assert heading in latex
    assert r"scale\_denominator = 1000" in latex
    assert r"scale" in latex
    assert r"weights_{i}" in latex


def test_json_certificate_generation_and_schema(tmp_path: Path):
    certificate = execute_audit(SYNTHETIC_FIXTURE, inputs=SYNTHETIC_INPUTS, function="calculate_weighted_score",
                                output="weighted_score", verify_lean=False)
    json_path, tex_path = tmp_path / "certificate.json", tmp_path / "certificate.tex"
    write_certificate(certificate, json_path=json_path, latex_path=tex_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "audit-certificate.schema.json").read_text(encoding="utf-8"))
    constant_schema = json.loads((ROOT / "schemas" / "constant-dependency-graph.schema.json").read_text(encoding="utf-8"))
    numeric_schema = json.loads((ROOT / "schemas" / "numeric-type-semantics.schema.json").read_text(encoding="utf-8"))
    ieee_schema = json.loads((ROOT / "schemas" / "ieee754-semantics.schema.json").read_text(encoding="utf-8"))
    parallel_schema = json.loads((ROOT / "schemas" / "parallel-semantics.schema.json").read_text(encoding="utf-8"))
    transformation_schema = json.loads((ROOT / "schemas" / "transformation-application.schema.json").read_text(encoding="utf-8"))
    registry = (Registry().with_resource(constant_schema["$id"], Resource.from_contents(constant_schema))
                .with_resource(numeric_schema["$id"], Resource.from_contents(numeric_schema))
                .with_resource(ieee_schema["$id"], Resource.from_contents(ieee_schema))
                .with_resource(parallel_schema["$id"], Resource.from_contents(parallel_schema))
                .with_resource(transformation_schema["$id"], Resource.from_contents(transformation_schema)))
    jsonschema.Draft202012Validator(schema, registry=registry).validate(payload)
    assert payload["verification_certificate"]["source_hash"] == payload["target"]["source_sha256"]
    assert tex_path.read_text(encoding="utf-8").startswith("\\documentclass")


def test_report_only_completes_on_theory_mismatch(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x + 1')\ndef f(x):\n    y=x*2\n    return y\n")
    certificate = execute_audit(path, inputs={"x": 4}, function="f", output="y",
                                mode=AuditMode.REPORT_ONLY, verify_lean=False)
    assert certificate.status == "VERIFICATION_FAILED"
    assert certificate.output["scalar"] == 8


def test_config_constant_execution_and_assumption(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x * factor')\ndef f(x, config):\n    y=x*config['factor']\n    return y\n")
    certificate = execute_audit(path, inputs={"x": 8, "config": {"factor": 0.25}}, function="f", output="y",
        config_constants={"config['factor']": {"symbol": "factor", "value": 0.25, "source": "settings.toml"}}, verify_lean=False)
    assert certificate.comparison["match"]
    assert certificate.output["scalar"] == 2.0
    assert certificate.lean["assumptions"] == ["factor"]


def test_derived_constant_lean_kernel_proof(tmp_path: Path):
    path = source(tmp_path, "import cpp_audit as audit\n@audit.theory(output='y', expression='y = x * a')\ndef f(x):\n    b=2\n    c=3.5\n    a=b*c\n    y=x*a\n    return y\n")
    lean_file = tmp_path / "certificate.lean"
    certificate = execute_audit(path, inputs={"x": 4}, function="f", output="y",
                                verify_lean=True, lean_file=lean_file)
    assert certificate.lean["kernel_verified"]
    assert any(name.startswith("derived_constant") for name in certificate.lean["theorem_names"])
    assert "((2)*(7))" in lean_file.read_text(encoding="utf-8")


def test_synthetic_script_e2e_kernel_verified(tmp_path: Path):
    certificate = execute_audit(SYNTHETIC_FIXTURE, inputs=SYNTHETIC_INPUTS, function="calculate_weighted_score",
                                output="weighted_score", verify_lean=True, lean_file=tmp_path / "synthetic.lean",
                                source_provenance={"kind": "independent_synthetic_fixture"})
    assert certificate.status == "LEAN_KERNEL_VERIFIED"
    assert certificate.lean["kernel_verified"]
    assert "extracted_expression_matches_theory" in certificate.verification_certificate["verified_theorem_names"]
    assert any(name.startswith("derived_constant") for name in certificate.verification_certificate["verified_theorem_names"])
    assert next(claim for claim in certificate.lean["claims"] if claim["claim"] == "LIBRARY_SEMANTIC_MAPPING")["status"] == "KERNEL_VERIFIED"
