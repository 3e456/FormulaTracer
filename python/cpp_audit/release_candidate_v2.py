"""Multi-site mathematical assurance with a separately sealed RC-v2 holdout.

The corpus stores semantic fixtures and provenance only.  It does not retain
reference source, documentation text, or provider implementations.  Retrieval
is measured independently from rigorous adoption and unresolved families remain
unresolved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from .generation_planning import plan_generation
from .release_candidate import STRICT_MATCHES, ReferenceRecord


@dataclass(frozen=True)
class RCv2Case:
    case_id: str
    split: str
    family: str
    expression: dict[str, Any]
    expected_provider: str | None
    expected_relation: str
    formula_references: tuple[str, ...]
    algorithm_reference: str | None = None

    @property
    def semantic_fingerprint(self) -> str:
        semantic = {
            "family": self.family,
            "expression": self.expression,
            "expected_provider": self.expected_provider,
            "expected_relation": self.expected_relation,
        }
        return sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest()


def _c(value: Any) -> dict[str, Any]:
    return {"op": "Constant", "value": value}


def _v(name: str) -> dict[str, Any]:
    return {"op": "FreeVariable", "name": name}


def _b(name: str) -> dict[str, Any]:
    return {"op": "BoundVariable", "name": name}


def _call(name: str, *args: dict[str, Any]) -> dict[str, Any]:
    return {"op": "FunctionCall", "name": name, "args": list(args)}


def _sum(index: str, upper: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"op": "FiniteSum", "bound_index": index,
            "index_domain": {"lower": _c(0), "upper_exclusive": _v(upper)}, "body": body}


def reference_registry_v2() -> list[ReferenceRecord]:
    return [
        ReferenceRecord("dlmf-gamma", "DLMF §5.2 Gamma definitions", "NIST DLMF",
                        "https://dlmf.nist.gov/5.2", "PRIMARY_MATHEMATICAL_REFERENCE", "DLMF 1.2.7"),
        ReferenceRecord("dlmf-asymptotic", "DLMF §2.1 Definitions and Elementary Properties", "NIST DLMF",
                        "https://dlmf.nist.gov/2.1", "PRIMARY_MATHEMATICAL_REFERENCE", "DLMF 1.2.7"),
        ReferenceRecord("wolfram-gamma", "Gamma function identities", "Wolfram Research",
                        "https://functions.wolfram.com/GammaBetaErf/Gamma/",
                        "OFFICIAL_MATHEMATICAL_REFERENCE", "accessed online"),
        ReferenceRecord("boost-math", "Boost.Math", "Boost C++ Libraries",
                        "https://www.boost.org/library/latest/math/", "OFFICIAL_PROVIDER_REFERENCE", "1.92.0"),
        ReferenceRecord("netlib-lapack", "LAPACK Users' Guide", "Netlib",
                        "https://www.netlib.org/lapack/lug/", "PRIMARY_ALGORITHM_REFERENCE", "Third edition"),
        ReferenceRecord("netlib-blas", "BLAS", "Netlib",
                        "https://www.netlib.org/blas/", "OFFICIAL_PROVIDER_REFERENCE", "online reference"),
        ReferenceRecord("numpy-fft", "Discrete Fourier Transform", "NumPy",
                        "https://numpy.org/doc/stable/reference/routines.fft.html",
                        "OFFICIAL_PROVIDER_REFERENCE", "stable documentation"),
        ReferenceRecord("numpy-linalg", "Linear algebra", "NumPy",
                        "https://numpy.org/doc/stable/reference/routines.linalg.html",
                        "OFFICIAL_PROVIDER_REFERENCE", "stable documentation"),
        ReferenceRecord("scipy-integrate-v2", "Integration", "SciPy",
                        "https://docs.scipy.org/doc/scipy/reference/integrate.html",
                        "OFFICIAL_PROVIDER_REFERENCE", "current documentation"),
        ReferenceRecord("scipy-optimize", "Optimization and root finding", "SciPy",
                        "https://docs.scipy.org/doc/scipy/reference/optimize.html",
                        "OFFICIAL_PROVIDER_REFERENCE", "current documentation"),
    ]


def benchmark_cases_v2() -> list[RCv2Case]:
    weighted = lambda i, n, w, y: _sum(i, n, {"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": w, "indices": [_b(i)]},
        {"op": "IndexedValue", "name": y, "indices": [_b(i)]}]})
    taylor = lambda i, n, x: _sum(i, n, {"op": "Divide", "args": [
        {"op": "Power", "args": [_v(x), _b(i)]}, {"op": "Factorial", "args": [_b(i)]}]})
    dft = lambda i, n, x: _sum(i, n, {"op": "Multiply", "args": [
        {"op": "IndexedValue", "name": x, "indices": [_b(i)]}, _call("exp", _v("phase"))]})
    central = {"op": "Divide", "args": [{"op": "Subtract", "args": [
        _call("f", {"op": "Add", "args": [_v("x"), _v("h")]}),
        _call("f", {"op": "Subtract", "args": [_v("x"), _v("h")]})]},
        {"op": "Multiply", "args": [_c(2), _v("h")]}]}
    integral = {"op": "Integral", "variable": "t", "lower": _v("a"), "upper": _v("b"),
                "integrand": _call("f", _v("t"))}
    convolution = {"op": "Convolution", "args": [_v("f"), _v("g")]}
    unsupported = [
        ("gamma", _call("gamma", _v("z")), ("dlmf-gamma", "wolfram-gamma")),
        ("beta", _call("beta", _v("a"), _v("b")), ("dlmf-gamma", "boost-math")),
        ("asymptotic", {"op": "BigO", "expression": _v("x"), "variable": "x"}, ("dlmf-asymptotic",)),
        ("matrix_multiply", {"op": "MatMul", "args": [_v("A"), _v("B")]}, ("netlib-blas", "numpy-linalg")),
        ("svd", {"op": "SVD", "matrix": _v("A")}, ("netlib-lapack", "numpy-linalg")),
        ("root_finding", {"op": "Root", "function": _v("f")}, ("scipy-optimize",)),
        ("probability", {"op": "Expectation", "random_variable": _v("X")}, ("dlmf-asymptotic",)),
        ("piecewise", {"op": "Piecewise", "cases": [[{"op": "GreaterThan", "args": [_v("x"), _c(0)]}, _v("x")]], "otherwise": _c(0)}, ("dlmf-asymptotic",)),
        ("integer_modulo", {"op": "Modulo", "args": [_v("x"), _c(256)]}, ("dlmf-asymptotic",)),
        ("bitvector", {"op": "BitAnd", "args": [_v("x"), _c(255)], "width": 8}, ("dlmf-asymptotic",)),
        ("units", {"op": "Quantity", "value": _v("x"), "unit": "m/s"}, ("dlmf-asymptotic",)),
        ("laplace", {"op": "IntegralTransform", "transform": "Laplace", "function": _v("f")}, ("dlmf-asymptotic",)),
    ]
    cases = [
        RCv2Case("v2-dev-dft", "development", "fourier", dft("n", "N", "x"), "numpy.fft.fft", "ALGORITHMICALLY_REALIZED_BY", ("numpy-fft",), "numpy-fft"),
        RCv2Case("v2-dev-series", "development", "series", taylor("k", "K", "x"), "scipy.special.expn_series", "TRUNCATED_TO", ("dlmf-asymptotic", "boost-math"), "boost-math"),
        RCv2Case("v2-dev-quadrature", "development", "quadrature", weighted("i", "N", "w", "y"), "numpy.dot.quadrature", "EXACT_UNDER_ASSUMPTIONS", ("scipy-integrate-v2", "netlib-blas"), "netlib-blas"),
        RCv2Case("v2-validation-difference", "validation", "finite_difference", central, "numpy.central_difference", "DISCRETIZATION", ("dlmf-asymptotic",)),
        RCv2Case("v2-validation-integral", "validation", "integral", integral, "scipy.integrate.quad", "APPROXIMATION_OF", ("scipy-integrate-v2",), "scipy-integrate-v2"),
        RCv2Case("v2-validation-convolution", "validation", "convolution", convolution, "scipy.signal.fftconvolve", "ALGORITHMICALLY_REALIZED_BY", ("numpy-fft",), "numpy-fft"),
    ]
    for number, (family, expression, references) in enumerate(unsupported):
        split = "final_holdout_v2" if number >= 7 else "validation"
        cases.append(RCv2Case(f"v2-{split}-{family}", split, family, expression, None,
                              "UNRESOLVED_OR_OUT_OF_SCOPE", references))
    cases.extend([
        RCv2Case("v2-holdout-fourier-renamed", "final_holdout_v2", "fourier", dft("sample", "L", "signal"), "numpy.fft.fft", "ALGORITHMICALLY_REALIZED_BY", ("numpy-fft",)),
        RCv2Case("v2-holdout-weighted-renamed", "final_holdout_v2", "quadrature", weighted("node", "P", "weight", "sample"), "numpy.dot.quadrature", "EXACT_UNDER_ASSUMPTIONS", ("scipy-integrate-v2", "netlib-blas")),
        RCv2Case("v2-holdout-negative", "final_holdout_v2", "negative_control", {"op": "Add", "args": [_v("a"), _v("b")]}, None, "NOT_EQUIVALENT", ("dlmf-asymptotic",)),
    ])
    return cases


def _evaluate(case: RCv2Case, plan: Any | None = None) -> dict[str, Any]:
    plan = plan or plan_generation(case.expression, search="broad", candidate_budget=100)
    if case.expected_provider is None:
        promoted = [item for item in plan.candidates if item.contract.lowering != "direct" and
                    item.verification_status in STRICT_MATCHES]
        return {"case_id": case.case_id, "split": case.split, "family": case.family,
                "provider_rank": None, "retrieval_status": "NOT_APPLICABLE",
                "verification_status": "FALSE_ACCEPTANCE" if promoted else "FAIL_CLOSED",
                "relation_status": "FALSE_ACCEPTANCE" if promoted else case.expected_relation,
                "semantic_fingerprint": case.semantic_fingerprint}
    candidate = next((item for item in plan.candidates if item.contract.provider_id == case.expected_provider), None)
    if candidate is None:
        return {"case_id": case.case_id, "split": case.split, "family": case.family,
                "provider_rank": None, "retrieval_status": "PROVIDER_RETRIEVAL_MISS",
                "verification_status": "NOT_VERIFIED", "relation_status": "RECONSTRUCTION_UNRESOLVED",
                "semantic_fingerprint": case.semantic_fingerprint}
    strict = candidate.verification_status in STRICT_MATCHES
    return {"case_id": case.case_id, "split": case.split, "family": case.family,
            "provider_rank": candidate.rank, "retrieval_status": "RETRIEVED",
            "verification_status": candidate.verification_status,
            "relation_status": case.expected_relation if strict else "RECONSTRUCTION_UNRESOLVED",
            "semantic_fingerprint": case.semantic_fingerprint}


def _recall(outcomes: Iterable[dict[str, Any]], cases: Iterable[RCv2Case], k: int) -> dict[str, Any]:
    expected = {case.case_id for case in cases if case.expected_provider}
    applicable = [outcome for outcome in outcomes if outcome["case_id"] in expected]
    hits = sum(outcome["provider_rank"] is not None and outcome["provider_rank"] <= k for outcome in applicable)
    return {"hits": hits, "total": len(applicable), "value": hits / len(applicable) if applicable else None}


def run_release_candidate_v2(output_dir: str | Path, *, execute_holdout: bool = True) -> dict[str, Any]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    cases = benchmark_cases_v2()
    holdout = [case for case in cases if case.split == "final_holdout_v2"]
    visible = [case for case in cases if case.split != "final_holdout_v2"]
    holdout_fingerprint = sha256("".join(case.semantic_fingerprint for case in holdout).encode()).hexdigest()
    manifest = {"schema_version": "2.0", "created": str(date.today()),
                "policy": "sealed before execution; post-execution case-specific repair forbidden",
                "holdout_fingerprint": holdout_fingerprint,
                "splits": {split: [{"case_id": c.case_id, "semantic_fingerprint": c.semantic_fingerprint}
                                    for c in cases if c.split == split]
                           for split in ("development", "validation", "final_holdout_v2")}}
    manifest_path = target / "benchmark-manifest-v2.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("holdout_fingerprint") != holdout_fingerprint:
            raise RuntimeError("RC_V2_HOLDOUT_MANIFEST_CHANGED")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    visible_plans = {case.case_id: plan_generation(case.expression, search="broad", candidate_budget=100)
                     for case in visible}
    outcomes = [_evaluate(case, visible_plans[case.case_id]) for case in visible]
    execution_path = target / "holdout-v2-execution.json"
    holdout_status = "SEALED_NOT_EXECUTED"
    if execute_holdout:
        if execution_path.exists():
            record = json.loads(execution_path.read_text(encoding="utf-8"))
            if record.get("holdout_fingerprint") != holdout_fingerprint:
                raise RuntimeError("RC_V2_HOLDOUT_RESULT_FINGERPRINT_MISMATCH")
            holdout_outcomes = record["outcomes"]
            holdout_status = "REUSED_IMMUTABLE_RESULT"
        else:
            holdout_outcomes = [_evaluate(case) for case in holdout]
            execution_path.write_text(json.dumps({"schema_version": "2.0", "executed": str(date.today()),
                "holdout_fingerprint": holdout_fingerprint, "outcomes": holdout_outcomes}, indent=2) + "\n", encoding="utf-8")
            holdout_status = "EXECUTED_AND_SEALED"
        outcomes.extend(holdout_outcomes)
    false_acceptance = sum(item["verification_status"] == "FALSE_ACCEPTANCE" for item in outcomes)
    resolved = sum(item["relation_status"] not in {"RECONSTRUCTION_UNRESOLVED", "UNRESOLVED_OR_OUT_OF_SCOPE"} for item in outcomes)
    report = {"schema_version": "2.0", "status": "ASSURANCE_PASS_WITH_UNRESOLVED" if false_acceptance == 0 else "ASSURANCE_FAIL",
              "reference_sites": len({record.organization for record in reference_registry_v2()}),
              "reference_records": len(reference_registry_v2()), "formula_cases": len(cases),
              "algorithm_cases": sum(case.algorithm_reference is not None for case in cases),
              "outcomes": outcomes, "retrieval": {f"recall_at_{k}": _recall(outcomes, cases, k) for k in (1, 5, 10, 20)},
              "reconstruction": {"resolved": resolved, "unresolved": len(outcomes) - resolved,
                                  "completion_rate": resolved / len(outcomes) if outcomes else None,
                                  "false_acceptance": false_acceptance},
              "holdout": {"status": holdout_status, "fingerprint": holdout_fingerprint, "cases": len(holdout)},
              "external_source_retained": 0,
              "evidence_boundary": "retrieval and runtime observations are not proof; unsupported families fail closed"}
    (target / "reference-registry-v2.json").write_text(json.dumps([asdict(item) for item in reference_registry_v2()], indent=2) + "\n", encoding="utf-8")
    (target / "release-candidate-v2-summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Derivative artifacts do not mutate sealed holdout inputs or outcomes.
    # Missing reconstruction products are retained as null with an explicit reason.
    from .reconstruction_artifacts import write_reconstruction_artifacts
    plans = dict(visible_plans)
    plans.update({case.case_id: plan_generation(case.expression, search="broad", candidate_budget=100)
                  for case in holdout})
    write_reconstruction_artifacts(
        cases, outcomes, plans, target.parent / "reconstruction",
        reference_versions={record.reference_id: record.version_or_revision
                            for record in reference_registry_v2()},
    )
    return report
