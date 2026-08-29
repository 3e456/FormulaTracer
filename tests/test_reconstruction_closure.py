from __future__ import annotations

import pytest

from formulatracer import reconstruct
from formulatracer.native import compare_ir, execute_native_kernel, native_available


pytestmark = pytest.mark.skipif(not native_available(), reason="native core not built")


def base(theory):
    return {
        "original_theory": theory,
        "reconstructed_theory": None,
        "structural_facts": {},
        "temporaries": [],
        "result_expression": None,
        "safety": {},
        "algorithm_ir": None,
        "provider_projection": None,
        "relation_chain": [],
        "assumptions": [],
        "proof_obligations": [],
        "exact_egraph_verified": False,
        "error": None,
        "range": None,
        "provenance": None,
    }


def test_python_projection_is_thin_and_exact():
    theory = {"op": "Add", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]}
    request = base(theory)
    request["reconstructed_theory"] = theory
    result = reconstruct(request)
    assert result.status == "EXACT"
    assert result.raw["evidence"][0]["structural_witness_proof_authority"] is False
    assert "再構成: EXACT" in result.explain("ja")


@pytest.mark.parametrize("field,replacement", [
    ("axis", 1),
    ("normalization", "unitary"),
    ("sign", 1),
    ("bound", "N+1"),
])
def test_semantic_mutations_are_not_quotiented(field, replacement):
    theory = {"op": "ProviderProjection", field: 0 if field != "sign" else -1}
    implementation = dict(theory); implementation[field] = replacement
    request = base(theory); request["reconstructed_theory"] = implementation
    result = reconstruct(request)
    assert result.status == "CORRECTLY_UNRESOLVED"
    assert result.unresolved_reason["code"] == "RELATION_NOT_ESTABLISHED"


def test_relation_chain_is_preserved_without_certifying_error():
    request = base({"op": "ContinuousFourierTransform"})
    request["reconstructed_theory"] = {"op": "FFT"}
    request["relation_chain"] = [
        {"kind": "SAMPLED_AS", "assumptions": ["sampling grid"], "provenance": ["test"], "error_evidence": None},
        {"kind": "ALGORITHMICALLY_REALIZED_BY", "assumptions": [], "provenance": ["test"], "error_evidence": None},
    ]
    result = reconstruct(request)
    assert result.status == "COMPOSITE_RELATION_RECONSTRUCTED"
    assert len(result.relation_chain) == 2
    assert result.raw["error"] is None


def test_unknown_call_effect_blocks_inline():
    theory = {"op": "FreeVariable", "name": "x"}
    request = base(theory)
    request["temporaries"] = [{"name": "t", "expression": theory, "uses": 1}]
    request["result_expression"] = {"op": "Temporary", "name": "t"}
    request["safety"] = {"unknown_call_effects": True}
    result = reconstruct(request)
    assert result.status == "CORRECTLY_UNRESOLVED"
    assert result.unresolved_reason["code"] == "INLINE_RECONSTRUCTION_UNRESOLVED"


def test_reconstruction_result_round_trips_through_native_audit_bundle():
    theory = {"op": "Constant", "value": 2}
    request = base(theory); request["reconstructed_theory"] = theory
    reconstruction = reconstruct(request).to_dict()
    verification = compare_ir(theory, theory).raw
    verification["reconstruction"] = reconstruction
    bundle = execute_native_kernel({
        "schema_version": "1.0", "kernel": "F", "operation": "AUDIT_BUNDLE",
        "result": verification, "source_context": {}, "environment": {},
        "artifact_lineage": {}, "reconstruction": reconstruction,
    })["result"]
    assert bundle["result"]["reconstruction"]["status"] == "EXACT"
    assert bundle["payload_hash"]

    # The certificate is derived from the same object, not independently classified.
    from formulatracer.native import NativeContext
    with NativeContext() as context, context.formula_from_json(theory) as left, \
            context.formula_from_json(theory) as right, left.verify_against(right) as native_result:
        raw = native_result.value.raw
        assert raw["reconstruction"] is None  # ordinary pair verification has no fabricated reconstruction
