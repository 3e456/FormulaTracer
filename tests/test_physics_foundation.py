from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from cpp_audit import MathematicalKnowledgeRegistry, TheorySpecification, synthesize_cross_language
from formulatracer.native import NativeContext


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "registry" / "scientific_foundations" / "physics-v1.json"


@pytest.fixture(scope="module")
def pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def native(operation: str, action: str, **payload):
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "D",
            "operation": operation, "action": action, **payload})["result"]


def test_foundation_pack_schema_and_native_validation(pack: dict) -> None:
    schema = json.loads((ROOT / "schemas" / "scientific-foundation-pack.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(pack)
    validated = native("SCIENTIFIC_FOUNDATIONS", "VALIDATE", pack=pack)
    assert validated["status"] == "FOUNDATION_PACK_VALID"
    assert validated["definitions"] >= 10 and validated["theorems"] >= 10


def test_mixed_partial_stokes_and_gauss_are_not_unconditional(pack: dict) -> None:
    for theorem_id in ("mixed_partial_symmetry", "stokes", "gauss_divergence"):
        decision = native("SCIENTIFIC_FOUNDATIONS", "CHECK_THEOREM", pack=pack,
                          theorem_id=theorem_id, proven_facts=[])
        assert decision["status"] == "THEOREM_CONDITIONS_UNRESOLVED"
        assert decision["rewrite_authorized"] is False
        assert decision["remaining_obligations"]


def test_discretization_quadrature_and_finite_volume_never_promote_to_exact(pack: dict) -> None:
    cases = {
        "central_difference_partial": ["local_smoothness", "spacing_nonzero", "truncation_bound_available"],
        "quadrature_geometric_integral": ["parameterization_regular", "quadrature_error_bound"],
        "finite_volume_flux": ["valid_mesh_control_volumes", "oriented_faces", "flux_consistency",
                               "stability_not_established"],
    }
    for realization_id, facts in cases.items():
        decision = native("SCIENTIFIC_FOUNDATIONS", "CHECK_REALIZATION", pack=pack,
                          realization_id=realization_id, proven_facts=facts)
        assert decision["status"] == "REALIZATION_ADMISSIBLE"
        assert decision["exact_eclass_merge_allowed"] is False


def test_dimension_and_frame_semantics_fail_closed() -> None:
    with NativeContext() as context:
        dimension = context.execute_kernel({"schema_version":"1.0","kernel":"A","operation":"UNITS",
            "action":"DIMENSION_LAPLACIAN","function_dimension":[["Theta",1]],
            "variable_dimension":[["L",1]]})["result"]
        frame = context.execute_kernel({"schema_version":"1.0","kernel":"D","operation":"REPRESENTATION",
            "action":"FRAME_ADD","left_frame":"World","right_frame":"Body"})["result"]
    assert dimension["exponents"] == [["L", -2], ["Theta", 1]]
    assert frame["status"] == "FRAME_MISMATCH" and frame["operation_authorized"] is False


def test_rotation_quaternion_and_transform_ambiguities_fail_closed() -> None:
    euler = native("REPRESENTATION", "CHECK_EULER_CONVENTION", axis_order="ZYX")
    gimbal = native("REPRESENTATION", "CHECK_EULER_CONVENTION", axis_order="ZYX",
                    mode="INTRINSIC", handedness="RIGHT", angle_unit="RADIAN", gimbal_lock=True)
    quaternion = native("REPRESENTATION", "QUATERNION_DOUBLE_COVER",
                        unit_norm_verified=False, antipodal_verified=True)
    transform = native("REPRESENTATION", "LAPLACE_FOURIER_RESTRICTION",
                       convention_resolved=True, imaginary_axis_in_roc=False)
    assert euler["status"] == "EULER_CONVENTION_UNRESOLVED"
    assert gimbal["status"] == "EULER_REPRESENTATION_SINGULAR"
    assert quaternion["equivalence_authorized"] is False
    assert transform["rewrite_authorized"] is False


def test_dask_unknown_backend_keeps_floating_reduction_unresolved() -> None:
    with NativeContext() as context:
        result = context.execute_kernel({"schema_version":"1.0","kernel":"C","operation":"PARALLEL_ANALYZE",
            "action":"ANALYZE","floating":True,
            "calls":[{"callable":"dask.array.sum","short":"sum","backend_status":"UNKNOWN"}]})["result"]
    assert result["status"] == "PARALLEL_SEMANTICS_UNRESOLVED"
    assert result["claims"]["BITWISE_REPRODUCIBLE"] == "NOT_ESTABLISHED"


def test_physics_knowledge_is_composed_into_existing_registry() -> None:
    registry = MathematicalKnowledgeRegistry.default()
    physics = registry.entries(category="VECTOR_CALCULUS")
    assert {item.knowledge_id for item in physics} >= {
        "physics_divergence_definition", "physics_laplacian_definition"
    }
    assert not registry.validate()


def test_cartesian_divergence_realization_round_trips_through_all_frontends() -> None:
    # High-level divergence is definitionally reduced to existing Add/FreeVariable
    # IR before lowering; the generated source is then independently re-read.
    theory = TheorySpecification("divergence", {"op":"Add","args":[
        {"op":"FreeVariable","name":"dF0_dx0"},
        {"op":"FreeVariable","name":"dF1_dx1"}]}, ["dF0_dx0", "dF1_dx1"])
    result = synthesize_cross_language(theory)
    assert set(result.results) == {"python", "rust", "cpp"}
    assert result.canonical_ir_status == "SAME_CANONICAL_MATHEMATICAL_IR"
    assert all(item.status == "ROUND_TRIP_VERIFIED" for item in result.results.values())
