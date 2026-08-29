from __future__ import annotations

import json
from pathlib import Path

from cpp_audit.reference_registry import (
    CandidateDisposition,
    DeprecationStatus,
    assess_candidate,
    build_review_registry,
    parse_reference_page,
    resolve_signature,
    version_verification_status,
)


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "registry" / "generated" / "public_api"
OVERRIDES = ROOT / "registry" / "public_api_reference_review_overrides.yaml"
ENVIRONMENT_INVENTORY = ROOT / "numeric_library_inventory.json"


def load(name: str) -> dict:
    return json.loads((GENERATED / name).read_text(encoding="utf-8"))


def test_detailed_review_class_expansion_is_complete() -> None:
    artifact = load("detailed_review_classes.json")
    assert len(artifact["classes"]) == 21
    assert sum(item["member_count"] for item in artifact["classes"]) == 5330
    assert all(item["member_count"] == len(item["member_apis"]) for item in artifact["classes"])
    assert all(item["verification_boundary"] == "STRUCTURAL_INVOCATION_ONLY_NOT_API_SPECIFIC_EQUIVALENCE"
               for item in artifact["classes"])


def test_detailed_templates_preserve_package_specific_reference_meaning() -> None:
    classes = {item["class_id"]: item for item in load("detailed_review_classes.json")["classes"]}
    assert "dtype" in classes["detailed_numpy_function"]["preserve_scope"]
    assert "coordinates" in classes["detailed_xarray_method"]["preserve_scope"]
    assert "stopping_criteria" in classes["detailed_scipy_function"]["preserve_scope"]
    assert "scheduler_sensitive_metadata" in classes["detailed_dask_method"]["preserve_scope"]


def test_cross_library_reduction_semantic_class_binding() -> None:
    classes = {item["id"]: item for item in load("semantic_equivalence_registry.json")["classes"]}
    members = classes["reduction_add"]["members"]
    assert "numpy.sum" in members
    assert "numpy.ndarray.sum" in members
    assert "xarray.DataArray.sum" in members
    assert "dask.array.sum" in members


def test_alias_graph_is_unambiguous_and_acyclic() -> None:
    graph = load("alias_graph.json")
    assert graph["edge_count"] == 158
    assert graph["ambiguous"] == {}
    assert graph["cycles"] == []
    assert graph["status"] == "VALID"


def test_formal_contract_inventory_alignment_is_fully_classified() -> None:
    alignment = load("formal_contract_inventory_alignment.json")
    assert alignment["formal_contract_total"] == 396
    assert sum(alignment["counts"].values()) == 396
    assert alignment["counts"]["ALIGNED_DIRECT"] == 366
    assert all(item["reason"] for item in alignment["entries"])


def test_deprecated_page_parsing_and_signature() -> None:
    page = b'''<dl><dt id="demo.old">demo.old(x, *, axis=None)</dt></dl>
    <div class="deprecated"><p>Deprecated since version 2.4: use demo.new instead;
    removal in version 3.0.</p></div>'''
    facts = parse_reference_page(page, "demo.old")
    assert facts.deprecated_status == DeprecationStatus.DEPRECATED.value
    assert facts.deprecated_since == "2.4"
    assert facts.removal_version_if_documented == "3.0"
    assert facts.replacement_if_documented == "demo.new"
    assert facts.signature == "(x, *, axis=None)"


def test_unknown_deprecation_fails_closed() -> None:
    facts = parse_reference_page(b'<dl><dt id="demo.fn">demo.fn(x)</dt></dl>', "demo.fn")
    assert facts.deprecated_status == DeprecationStatus.UNKNOWN.value


def test_signature_fallback_order_and_unknown() -> None:
    official = b'<dl><dt id="demo.fn">demo.fn(x, y=1)</dt></dl>'
    assert resolve_signature("demo.fn", official_page=official, stub_signature="(wrong)") == (
        "(x, y=1)", "OFFICIAL_REFERENCE_SIGNATURE")
    assert resolve_signature("demo.fn", stub_signature="(x: int) -> int")[1] == "STUB_SIGNATURE"
    assert resolve_signature("demo.fn") == ("SIGNATURE_UNKNOWN", "SIGNATURE_UNKNOWN")


def test_version_mismatch_and_unverified_are_explicit() -> None:
    assert version_verification_status("REFERENCE_VERSION_COMPATIBLE_MINOR") == "VERSION_PARTIALLY_VERIFIED"
    assert version_verification_status("REFERENCE_VERSION_MISMATCH") == "VERSION_UNVERIFIED"
    assert version_verification_status("REFERENCE_URL_VERSION_PINNED") == "VERSION_VERIFIED"


def test_candidate_dispositions_remain_fail_closed() -> None:
    summary = load("review_registry_summary.json")
    assert summary["existing_family_candidate_count"] == 4020
    assert sum(summary["candidate_dispositions"].values()) == 4020
    assert summary["candidate_dispositions"] == {
        "AMBIGUOUS": 0, "FORMALIZED": 3877, "NOT_APPLICABLE": 139,
        "REFERENCE_INSUFFICIENT": 4, "REJECTED": 0, "REVIEW_PENDING": 0,
    }
    assert summary["candidate_dispositions"]["AMBIGUOUS"] == 0


def test_offline_review_regeneration_hash_is_stable() -> None:
    before = {path.name: load(path.name)["provenance"]["reviewed_inventory_sha256"]
              for path in GENERATED.glob("*-*.json")}
    build_review_registry(GENERATED, overrides_path=OVERRIDES,
                          environment_inventory_path=ENVIRONMENT_INVENTORY)
    after = {path.name: load(path.name)["provenance"]["reviewed_inventory_sha256"]
             for path in GENERATED.glob("*-*.json")}
    assert before == after


def test_dask_execution_overlay_and_random_classes() -> None:
    dask = load("dask-2026.3.0.json")
    reduction = next(item for item in dask["inventory"] if item["qualified_name"] == "dask.array.sum")
    assert reduction["semantic_class_id"] == "reduction_add"
    assert reduction["execution_ir"]["lazy"] is True
    numpy = load("numpy-2.4.4.json")
    normal = next(item for item in numpy["inventory"] if item["qualified_name"] == "numpy.random.normal")
    assert normal["semantic_class_id"] == "distributionrelation_normal"
    assert normal["execution_ir"]["sequence_identity"] == "SEQUENCE_IDENTICAL_NOT_CLAIMED"


def test_semantic_registry_validates_schema() -> None:
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "schemas" / "semantic-equivalence-registry.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(load("semantic_equivalence_registry.json"))


def candidate_templates() -> dict[str, dict]:
    return {item["template_id"]: item for item in load("candidate_reference_contracts.json")["templates"]}


def test_class_level_promotion_and_cross_library_normalization() -> None:
    templates = candidate_templates()
    reduction = templates["reference_reduction_add"]
    assert {"numpy.sum", "xarray.DataArray.sum", "dask.array.sum"} <= set(reduction["member_apis"])
    assert reduction["formalization_status"] == CandidateDisposition.FORMALIZED.value
    assert reduction["binding_expansion"] == "CLASS_TEMPLATE_TO_MEMBER_API"
    overlay = reduction["execution_semantics"]["overlays"][0]
    assert overlay["applicable_packages"] == ["dask"]
    assert overlay["mathematical_claim"] == "MATHEMATICAL_EQUIVALENCE"
    assert overlay["floating_point_claim"] == "FLOATING_REDUCTION_ORDER_DIFFERS"


def test_scipy_solver_and_statistical_relations_are_latex_ready() -> None:
    templates = candidate_templates()
    minimize = templates["reference_optimizationrelation_minimize"]
    assert "arg\\,min" in minimize["canonical_semantics"]["latex_template"]
    assert {"bounds", "constraints", "tolerance"} <= set(minimize["preserve_scope"])
    test = templates["reference_statisticalinference_ttest_1samp"]
    assert "H_0" in test["canonical_semantics"]["latex_template"]
    assert "alternative" in test["preserve_scope"]


def test_numpy_pandas_and_xarray_templates_preserve_semantics() -> None:
    templates = candidate_templates()
    reduction = templates["reference_reduction_add"]
    assert {"axis", "dtype", "where", "initial"} <= set(reduction["preserve_scope"])
    grouping = templates["reference_groupingalignment_groupby"]
    assert {"group_keys", "dropna", "sort", "observed"} <= set(grouping["preserve_scope"])
    alignment = templates["reference_alignment_reindex"]
    assert {"dimension_names", "coordinates", "indexes", "join", "fill_value", "container_type"} <= set(alignment["preserve_scope"])


def test_random_distribution_contract_does_not_claim_sequence_identity() -> None:
    normal = candidate_templates()["reference_distributionrelation_normal"]
    assert {"distribution", "parameters", "shape", "population", "replace", "weights"} <= set(normal["preserve_scope"])
    assert "internal_sampling_algorithm" in normal["ignore_scope"] or "internal_implementation" in normal["ignore_scope"]
    numpy = load("numpy-2.4.4.json")
    record = next(item for item in numpy["inventory"] if item["qualified_name"] == "numpy.random.normal")
    assert record["execution_ir"]["sequence_identity"] == "SEQUENCE_IDENTICAL_NOT_CLAIMED"


def test_signature_unknown_can_be_sufficient_but_required_unknown_blocks() -> None:
    summary = load("review_registry_summary.json")["signature_semantic_sufficiency"]
    assert summary["unknown_but_acceptable"] > 3000
    fake = {
        "qualified_name": "numpy.sum", "package": "numpy", "object_kind": "function",
        "signature_status": "SIGNATURE_UNKNOWN",
    }
    status, _, reason = assess_candidate(fake, "Reduction", signature_required=True)
    assert status == CandidateDisposition.REFERENCE_INSUFFICIENT.value
    assert reason == "SIGNATURE_REQUIRED_BUT_UNKNOWN"


def test_reference_insufficient_has_source_fallback_ledger() -> None:
    ledger = load("source_inspection_candidates.json")
    assert len(ledger["candidates"]) == 4
    assert all(item["source_inspection_status"] == "CANDIDATE_NOT_PERFORMED" for item in ledger["candidates"])
    assert all(item["precedence"] == "OFFICIAL_REFERENCE_REMAINS_AUTHORITATIVE" for item in ledger["candidates"])


def test_environment_version_provenance_and_inventory_outside_contracts() -> None:
    summary = load("review_registry_summary.json")
    # Public artifacts deliberately do not retain a workstation inventory.
    assert summary["environment_version"] == {
        "ENVIRONMENT_VERSION_UNVERIFIED": 12,
        "ENVIRONMENT_VERSION_VERIFIED": 0,
        "source_inventory_sha256": None,
    }
    assert summary["version"] == {
        "VERSION_PARTIALLY_VERIFIED": 4, "VERSION_UNVERIFIED": 2, "VERSION_VERIFIED": 6,
    }
    alignment = load("formal_contract_inventory_alignment.json")
    outside = [item for item in alignment["entries"] if item["status"] == "INVENTORY_EXTERNAL"]
    assert len(outside) == 16
    assert all(item["reason"] for item in outside)


def test_candidate_contract_registry_validates_schema() -> None:
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "schemas" / "candidate-reference-contracts.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(load("candidate_reference_contracts.json"))
