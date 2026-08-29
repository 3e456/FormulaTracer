import json
import os
from pathlib import Path
import subprocess

import pytest

from cpp_audit.native_differential import compare_case
from formulatracer.native import NativeContext, NativeLibrary, compare_ir, native_available


ROOT = Path(__file__).resolve().parents[1]
NATIVE_REQUIRED = pytest.mark.skipif(not native_available(), reason="native core not built")


@NATIVE_REQUIRED
def test_python_facade_uses_stable_c_abi_and_same_core_result():
    library = NativeLibrary()
    assert library._lib.ft_abi_version() == 1
    result = compare_ir({"op": "Constant", "value": 42, "radix": 16, "original_text": "0x2a"},
                        {"op": "Constant", "value": 42, "radix": 10})
    assert result.status == "EXACT_EQUALITY"
    assert result.relation == "EXACT_EQUALITY"
    assert result.relation.kind == "EXACT_EQUALITY"
    assert result.theory is not None and result.implementation is not None
    assert result.theory.to_tex() == result.implementation.to_tex() == "42"
    assert result.theory.semantic_hash == result.implementation.semantic_hash
    assert result.assumptions == ()
    assert result.error is None and result.range is None
    assert result.tex == "42"
    assert "FormulaTracer Verification Certificate" in result.to_tex()
    assert "BOUND\\_NOT\\_AVAILABLE" in result.to_tex()
    assert result.evidence == ({"kernel_verified": False, "kind": "NATIVE_SEMANTIC_COMPARISON",
                                "level": "FORMALLY_DERIVED"},)
    assert not result.evidence.kernel_verified
    assert result.to_dict()["status"] == "EXACT_EQUALITY"
    assert "検証状態" in result.explain(language="ja")


@NATIVE_REQUIRED
def test_mutated_operator_is_not_accepted_by_any_binding_path():
    original = {"op": "Add", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]}
    mutated = {"op": "Subtract", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]}
    result = compare_case("operator-mutation", original, mutated)
    assert result.semantic_match
    assert result.rust_status == "DIVERGED"
    assert not result.false_acceptance


@NATIVE_REQUIRED
def test_native_tex_component_parses_supported_subset_and_fails_closed_on_ambiguity():
    with NativeContext() as context, context.formula_from_tex(r"x+1") as formula, formula.verify() as result:
        assert result.value.status == "UNRESOLVED"
        assert result.value.relation == "UNRESOLVED"
    with NativeContext() as context:
        with pytest.raises(Exception, match="AMBIGUOUS_NOTATION"):
            context.formula_from_tex(r"x_i y_i")
    accepted = [
        r"\sum_{n=0}^{\infty} x_n",
        r"\prod_{i=1}^{N} x_i",
        r"\int_{0}^{1} f(x) \, dx",
        r"\lim_{x\to 0} f(x)",
        r"\frac{d}{dx} f(x)",
    ]
    with NativeContext() as context:
        for source in accepted:
            with context.formula_from_tex(source) as formula, formula.verify() as result:
                assert result.value.status == "UNRESOLVED"
                assert "NATIVE_COMPONENT_INCOMPLETE" not in result.value.diagnostics


@NATIVE_REQUIRED
def test_native_audit_bundle_is_derived_from_result_and_integrity_protected():
    expression = {"op": "Add", "args": [
        {"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]}
    with NativeContext() as context, context.formula_from_json(expression) as theory, \
            context.formula_from_json(expression) as implementation, \
            theory.verify_against(implementation) as result:
        bundle = result.to_audit_bundle(
            source_context={"source_hash": "abc"},
            environment={"core": "native"},
            artifact_lineage={"artifact": "certificate.tex"})
    assert bundle["result"]["status"] == "EXACT_EQUALITY"
    assert bundle["source_context"]["source_hash"] == "abc"
    assert len(bundle["payload_hash"]) == 64


@NATIVE_REQUIRED
def test_mathematical_function_scalar_substitution_numpy_and_domain_gate():
    expression = {"op": "Add", "args": [
        {"op": "Power", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 2}]},
        {"op": "FreeVariable", "name": "a"},
    ]}
    result = compare_ir(expression, expression)
    assert result.theory is not None
    function = result.theory.as_function()
    try:
        assert function(x=3, a=2) == 11.0
        substituted = function.substitute(a=2)
        try:
            assert substituted(x=4) == 18.0
            np = pytest.importorskip("numpy")
            values = substituted.to_callable(backend="numpy")(x=np.array([1.0, 2.0]))
            assert values.tolist() == [3.0, 6.0]
            assert substituted.inspect()["variables"] == ["x"]
        finally:
            substituted.close()
    finally:
        function.close()

    log_result = compare_ir({"op": "Log", "args": [{"op": "FreeVariable", "name": "x"}]},
                            {"op": "Log", "args": [{"op": "FreeVariable", "name": "x"}]})
    log_function = log_result.theory.as_function()
    try:
        with pytest.raises(Exception, match="UNRESOLVED"):
            log_function(x=-1)
    finally:
        log_function.close()


@NATIVE_REQUIRED
def test_native_rust_cli_and_c_abi_agree(tmp_path: Path):
    expression = {"op": "Multiply", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 2}]}
    left = tmp_path / "left.json"; right = tmp_path / "right.json"
    left.write_text(json.dumps(expression), encoding="utf-8"); right.write_text(json.dumps(expression), encoding="utf-8")
    suffix = ".exe" if os.name == "nt" else ""
    executable = ROOT / "target" / "debug" / f"formulatracer-native{suffix}"
    if not executable.exists():
        executable = ROOT / "target" / "debug" / "deps" / f"formulatracer-native{suffix}"
    completed = subprocess.run([executable, "compare", left, right], capture_output=True, text=True, check=True)
    assert completed.stdout.strip() == compare_ir(expression, expression).status == "EXACT_EQUALITY"


def test_cpp_wrapper_is_thin_and_contains_no_semantic_operators():
    header = (ROOT / "include" / "formulatracer.hpp").read_text(encoding="utf-8")
    assert "ft_formula_from_tex" in header and "ft_verify_pair" in header
    assert all(token not in header for token in ("canonicalize", "rewrite", "egraph", "ApproximationOf"))
