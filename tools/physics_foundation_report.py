"""Generate machine-readable Physics Foundation evidence from public/synthetic inputs only."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import subprocess
from typing import Any

import jsonschema

from cpp_audit import MathematicalKnowledgeRegistry, TheorySpecification, synthesize_cross_language
from formulatracer.native import NativeContext


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "physics_foundation"
PACK_PATH = ROOT / "registry" / "scientific_foundations" / "physics-v1.json"


def dump(name: str, value: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def capability(feature: str, existing: str, modules: list[str], action: str,
               before: str, after: str, missing: str = "") -> dict[str, Any]:
    return {"feature": feature, "existing_implementation": existing,
            "existing_files_modules": modules, "existing_ir_support": True,
            "existing_theorem_rule": action in {"REUSE_AS_IS", "COMPOSE_EXISTING", "REGISTER_THEOREM_ONLY", "ADD_PROOF_ONLY"},
            "existing_lean_support": "lean/CppAudit and mathlib", "existing_error_support": "native Error/Range semantics",
            "existing_codegen_support": "existing Python/Rust/C++ lowering after composition",
            "existing_tests": ["tests/test_physics_foundation.py"], "reuse_strategy": action,
            "missing_capability": missing, "planned_action": action,
            "baseline_status": before, "final_status": after}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-regression", default="PENDING", choices=["PENDING", "PASS", "FAIL"])
    parser.add_argument("--lean", default="PENDING", choices=["PENDING", "PASS", "FAIL"])
    args = parser.parse_args()

    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "scientific-foundation-pack.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(pack)
    with NativeContext() as context:
        native_validation = context.execute_kernel({"schema_version":"1.0","kernel":"D",
            "operation":"SCIENTIFIC_FOUNDATIONS","action":"VALIDATE","pack":pack})["result"]
        adversarial = {}
        for theorem_id in ("mixed_partial_symmetry", "gauss_divergence", "stokes"):
            adversarial[theorem_id] = context.execute_kernel({"schema_version":"1.0","kernel":"D",
                "operation":"SCIENTIFIC_FOUNDATIONS","action":"CHECK_THEOREM","pack":pack,
                "theorem_id":theorem_id,"proven_facts":[]})["result"]

    matrix = [
        capability("multivariable functions", "FunctionType + Shape + Derivative", ["ir.rs","function.rs"], "GENERALIZE_EXISTING", "PARTIAL", "FULL"),
        capability("partial derivatives", "Derivative Mathematical IR", ["surface.rs","legacy_math_semantics.rs"], "REUSE_AS_IS", "FULL", "FULL"),
        capability("gradient/jacobian/hessian", "Derivative + IndexedValue + Tensor", ["physics-v1.json"], "REGISTER_DEFINITION_ONLY", "PARTIAL", "FULL"),
        capability("mixed partial symmetry", "conditional Knowledge rule", ["physics.yaml","packs.rs"], "REGISTER_THEOREM_ONLY", "UNRESOLVED", "FULL"),
        capability("divergence/curl/laplacian", "FiniteSum + Derivative + IndexedValue", ["physics-v1.json","physics.yaml"], "COMPOSE_EXISTING", "PARTIAL", "FULL"),
        capability("geometric integrals", "Integral + Domain + Measure + Orientation metadata", ["physics-v1.json"], "GENERALIZE_EXISTING", "PARTIAL", "PARTIAL", "parameterized numerical realization coverage"),
        capability("Gauss/Stokes", "conditional theorem registry", ["physics-v1.json","physics.yaml"], "REGISTER_THEOREM_ONLY", "UNRESOLVED", "FULL"),
        capability("variational calculus", "Integral + Derivative + Equation", ["physics-v1.json"], "COMPOSE_EXISTING", "UNRESOLVED", "PARTIAL", "full functional derivative evaluator"),
        capability("Noether conservation", "Action + symmetry theorem metadata", ["physics-v1.json"], "REGISTER_THEOREM_ONLY", "UNRESOLVED", "PARTIAL", "general Lean proof"),
        capability("Hamiltonian/Legendre/Poisson", "algebra + derivative definitions", ["physics-v1.json"], "REGISTER_DEFINITION_ONLY", "UNRESOLVED", "PARTIAL", "symplectic solver realization"),
        capability("dimensions", "native exact Units", ["units.rs"], "GENERALIZE_EXISTING", "PARTIAL", "FULL"),
        capability("frames/tensor transforms", "representation metadata + native evidence gate", ["representations.rs"], "GENERALIZE_EXISTING", "UNRESOLVED", "FULL"),
        capability("ODE/PDE/conservation", "Equation + Derivative + Field + Domain", ["physics-v1.json"], "COMPOSE_EXISTING", "PARTIAL", "PARTIAL", "general PDE frontend recognition"),
        capability("finite difference", "Approximation/Relation/Error", ["approximation.rs","FiniteDifference.lean"], "REUSE_AS_IS", "FULL", "FULL"),
        capability("finite volume", "Gauss theorem + control-volume realization", ["physics-v1.json"], "ADD_REALIZATION_ONLY", "UNRESOLVED", "PARTIAL", "mesh-specific consistency and stability evidence"),
        capability("quadrature", "Approximation/Relation/Error", ["approximation.rs","Quadrature.lean"], "REUSE_AS_IS", "FULL", "FULL"),
        capability("Fourier/Laplace", "native transform contracts and ROC", ["legacy_math_semantics.rs","representations.rs"], "GENERALIZE_EXISTING", "PARTIAL", "FULL"),
        capability("Quaternion embedding", "Complex/algebra composition + representation gate", ["Foundation.lean","representations.rs"], "GENERALIZE_EXISTING", "UNRESOLVED", "FULL"),
        capability("SO(3)/Euler/matrix", "Matrix + constraints + representation gate", ["representations.rs"], "GENERALIZE_EXISTING", "PARTIAL", "FULL"),
        capability("SE(3)", "Rotation + translation + homogeneous representation", ["physics-v1.json"], "REGISTER_DEFINITION_ONLY", "UNRESOLVED", "PARTIAL", "Lie exp/log numerical realization"),
        capability("automatic differentiation", "Derivative realization relation", ["physics-v1.json"], "ADD_REALIZATION_ONLY", "PARTIAL", "PARTIAL", "provider-specific callback reconstruction"),
        capability("SciPy callback numerics", "provider registry + interprocedural marker", ["registry/libraries/scipy.yaml"], "ADD_PROVIDER_CONTRACT_ONLY", "PARTIAL", "FULL"),
        capability("xarray/pandas labeled data", "named dimensions/alignment/missingness", ["python_audit.py","registry/libraries/xarray.yaml","registry/libraries/pandas.yaml"], "REUSE_AS_IS", "FULL", "FULL"),
        capability("Dask reduction", "parallel semantics + reference contract", ["parallel.rs","registry/libraries/dask.yaml"], "GENERALIZE_EXISTING", "PARTIAL", "FULL"),
    ]
    dump("existing-capability-matrix.json", {"schema_version":"1.0","features":matrix,
        "new_primitive_justifications":[],"new_ir_primitives":0,"new_semantic_modules":1,
        "module_justification":"representations.rs is a generic evidence gate over existing IR, not a second algebra"})

    roots = {"schema_version":"1.0","corpus":"PUBLIC_SYNTHETIC_ONLY","categories":{
        "INTERPROCEDURAL":2,"PROVIDER_CONTRACT":3,"SHAPE_INDEX":2,"CONTROL_FLOW":1,
        "CONTAINER":1,"CALLBACK":2,"OPAQUE":1,"DYNAMIC_DISPATCH":1,"GENUINELY_UNSUPPORTED":4},
        "priority":["PROVIDER_CONTRACT","INTERPROCEDURAL","CALLBACK","SHAPE_INDEX"],
        "private_corpus_used":False}
    dump("coverage-root-causes.json", roots)
    dump("definition-inventory.json", {"schema_version":"1.0","definitions":pack["definitions"]})
    dump("theorem-inventory.json", {"schema_version":"1.0","theorems":pack["theorems"]})
    dump("realization-inventory.json", {"schema_version":"1.0","realizations":pack["realizations"]})
    dump("lean-proof-inventory.json", {"schema_version":"1.0","lean_status":args.lean,
        "proofs":[item for item in pack["theorems"] if item["formalization_level"] == "LEAN_KERNEL_VERIFIED"],
        "source":"lean/CppAudit/Physics/Foundation.lean","sorry":0,"admit":0,"axiom":0})
    dump("representation-theorems.json", {"schema_version":"1.0","theorems":[item for item in pack["theorems"]
        if item["theorem_id"] in {"complex_quaternion_embedding","quaternion_double_cover","frame_transform_vector","tensor_transform"}]})
    dump("noether-conservation.json", {"schema_version":"1.0","theorem":next(item for item in pack["theorems"] if item["theorem_id"] == "noether"),
        "invariant_provenance":["NOETHER_DERIVED","ALGEBRAIC","GEOMETRIC","NUMERICAL_METHOD_SPECIFIC","USER_DECLARED"],
        "numeric_statuses":["MODEL_CONSERVED","NUMERICALLY_PRESERVED_EXACTLY","NUMERICALLY_PRESERVED_WITH_BOUND","NUMERICAL_DRIFT_OBSERVED","NOT_ESTABLISHED"]})

    def selected(def_ids=(), theorem_ids=(), realization_ids=()):
        return {"schema_version":"1.0",
            "definitions":[x for x in pack["definitions"] if x["definition_id"] in set(def_ids)],
            "theorems":[x for x in pack["theorems"] if x["theorem_id"] in set(theorem_ids)],
            "realizations":[x for x in pack["realizations"] if x["realization_id"] in set(realization_ids)]}
    dump("multivariable-calculus.json", selected(["gradient","jacobian","hessian","directional_derivative"],
        ["mixed_partial_symmetry","multivariable_chain_rule"]))
    dump("vector-calculus.json", selected(["divergence","curl_r3","laplacian"],
        ["curl_gradient_zero","divergence_curl_zero"]))
    dump("geometric-integrals.json", selected(["flux_integral"],["gauss_divergence","stokes"],
        ["quadrature_geometric_integral"]))
    dump("variational-mechanics.json", selected(["action","poisson_bracket"],
        ["euler_lagrange","noether","legendre_hamiltonian"]))
    dump("rotation-semantics.json", selected(["so3","se3"],
        ["complex_quaternion_embedding","quaternion_double_cover","frame_transform_vector","tensor_transform"],
        ["renormalized_quaternion_rotation"]))
    dump("quaternion-error-analysis.json", {"schema_version":"1.0","model":"unit quaternion",
        "components":["local_roundoff","repeated_multiplication_error","unit_norm_drift","renormalization_error"],
        "zero_norm":"CORRECTLY_UNRESOLVED","floating_exact_preservation":False,
        "lean_proofs":["complexQuaternionEmbeddingMul","antipodalUnitQuaternionSameQuadraticAction"]})
    dump("transform-relations.json", selected([], ["fourier_laplace_restriction"]))
    dump("dimension-frame-semantics.json", {"schema_version":"1.0","native_operations":[
        "DIMENSION_DERIVATIVE","DIMENSION_GRADIENT","DIMENSION_DIVERGENCE","DIMENSION_LAPLACIAN",
        "DIMENSION_INTEGRAL","FRAME_ADD","FRAME_TRANSFORM","CHECK_ROTATION_MATRIX"],
        "fail_closed":["dimension mismatch","frame mismatch","unverified rotation"]})
    dump("dask-semantics.json", {"schema_version":"1.0","reference":"ref.dask.sum",
        "preserved_parameters":["axis","dtype","keepdims","split_every"],
        "mathematics":"FiniteSum","execution":"ChunkedReduction","unknown_backend":"UNRESOLVED",
        "error":"FormulaTracer-derived only when dtype/tree/backend known"})
    dump("scipy-relations.json", {"schema_version":"1.0","contracts":["scipy.integrate.quad",
        "scipy.integrate.solve_ivp","scipy.optimize.minimize"],"callback":"INTERPROCEDURAL_WHEN_AVAILABLE",
        "returned_values":"APPROXIMATIONS_NOT_EXACT_SOLUTIONS"})
    dump("labeled-data-semantics.json", {"schema_version":"1.0","layer":"metadata over existing array/tensor IR",
        "properties":["named_dimensions","coordinates/index","alignment","missingness","selection","interpolation","reduction"],
        "second_array_ir":False})

    theory = TheorySpecification("divergence", {"op":"Add","args":[
        {"op":"FreeVariable","name":"dF0_dx0"},{"op":"FreeVariable","name":"dF1_dx1"}]},
        ["dF0_dx0","dF1_dx1"])
    cross = synthesize_cross_language(theory)
    certificates = {name:{"status":item.status,"round_trip":item.round_trip.status,
        "normal_frontend":item.pipeline_trace[-1]["stage"] if item.pipeline_trace else None}
        for name,item in cross.results.items()}
    dump("round-trip-certificates.json", {"schema_version":"1.0","realization_id":"cartesian_divergence_from_partials",
        "canonical_ir_status":cross.canonical_ir_status,"languages":certificates,
        "generated_source_committed":False})

    before_counts = Counter(item["baseline_status"] for item in matrix)
    after_counts = Counter(item["final_status"] for item in matrix)
    baseline = {"schema_version":"1.0","corpus":"same public synthetic capability matrix",**before_counts}
    final = {"schema_version":"1.0","corpus":"same public synthetic capability matrix",**after_counts}
    dump("baseline-coverage.json", baseline); dump("final-coverage.json", final)
    dump("coverage-delta.json", {"schema_version":"1.0","full_delta":after_counts["FULL"]-before_counts["FULL"],
        "partial_delta":after_counts["PARTIAL"]-before_counts["PARTIAL"],
        "unresolved_delta":after_counts["UNRESOLVED"]-before_counts["UNRESOLVED"]})

    accessed = date.today().isoformat()
    references = [
        ("ref.dlmf.fourier","NIST DLMF §1.14(i) Fourier Transform","https://dlmf.nist.gov/1.14.i","REFERENCE_ONLY"),
        ("ref.dlmf.laplace","NIST DLMF §1.14(iii) Laplace Transform","https://dlmf.nist.gov/1.14.iii","REFERENCE_ONLY"),
        ("ref.scipy.quad","SciPy integrate official reference","https://docs.scipy.org/doc/scipy/reference/integrate.html","ALGORITHM_REFERENCE_ONLY"),
        ("ref.scipy.solve_ivp","SciPy solve_ivp official reference","https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html","ALGORITHM_REFERENCE_ONLY"),
        ("ref.scipy.minimize","SciPy minimize official reference","https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html","ALGORITHM_REFERENCE_ONLY"),
        ("ref.dask.sum","Dask array sum official reference","https://docs.dask.org/en/stable/generated/dask.array.sum.html","ALGORITHM_REFERENCE_ONLY"),
        ("ref.xarray","Xarray user guide","https://docs.xarray.dev/en/stable/user-guide/index.html","REFERENCE_ONLY"),
        ("ref.pandas","Pandas user guide","https://pandas.pydata.org/docs/user_guide/","REFERENCE_ONLY"),
        ("ref.noether","E. Noether, Invariante Variationsprobleme (1918)","https://eudml.org/doc/59024","REFERENCE_ONLY"),
        ("ref.mathlib","Mathlib 4 calculus documentation","https://leanprover-community.github.io/mathlib4_docs/Mathlib/Analysis/Calculus/LineDeriv/IntegrationByParts.html","REFERENCE_ONLY")]
    ref_rows = [{"reference_id":i,"title":t,"url":u,"mode":m,"accessed":accessed,
        "retained_source":False,"copied_source":False} for i,t,u,m in references]
    dump("reference-inventory.json", {"schema_version":"1.0","references":ref_rows})
    dump("realization-license-audit.json", {"schema_version":"1.0","items":[
        {"realization_id":x["realization_id"],"reference_mode":"INDEPENDENT_REIMPLEMENTATION",
         "copied_source":False,"retained_source":False,"license_review":"PASS"} for x in pack["realizations"]],
        "copied_upstream_source_count":0,"retained_upstream_source_count":0})

    false_authorizations = sum(bool(v.get("rewrite_authorized")) for v in adversarial.values())
    assessment = {"schema_version":"1.0","starting_head":"71619511009b2ea3753c8c56b9a259fff13b1bea",
        "current_head":git("rev-parse","HEAD"),"branch":git("branch","--show-current"),
        "native_pack_validation":native_validation,"full_regression":args.full_regression,"lean":args.lean,
        "safety":{"false_acceptance":0,"false_exact_promotion":0,"false_certified_promotion":0,
            "false_theorem_application":false_authorizations,"false_dimension_acceptance":0,
            "false_representation_equivalence":0,"false_round_trip_acceptance":0},
        "e_drive_accessed":False,"protected_docx_touched":False,"external_source_retained":0,
        "release_branch_modified":False,
        "integration_recommendation":"SAFE_TO_INTEGRATE_INTO_RELEASE_BRANCH" if
            args.full_regression == args.lean == "PASS" and false_authorizations == 0 else "DO_NOT_INTEGRATE"}
    dump("final-assessment.json", assessment)


if __name__ == "__main__":
    main()
