from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import jsonschema

from formulatracer import (
    AuditProfile,
    aggregate_localization_metrics,
    ConfigurationParameter,
    ConfigurationSource,
    DatasetSchema,
    ExtensionPackManifest,
    FieldSchema,
    FormulaTracer,
    IncrementalAuditCache,
    InputArtifact,
    load_extension_pack,
    SchemaChangeKind,
    build_cache_key,
    compare_dataset_schemas,
    plan_incremental_audit,
    profile_acceptance,
    resolve_configuration,
    run_provenance_assurance,
    SandboxPolicy,
    run_sandboxed,
    saturate_and_match,
    verify_audit_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
EXACT = ROOT / "examples" / "end_to_end_audit" / "exact.py"


def exact_result(**options):
    return FormulaTracer(EXACT, project_root=EXACT.parent).analyze(ranges={"x": (1, 2)}, **options)


def test_configuration_override_trace_and_secret_redaction() -> None:
    traces = resolve_configuration([
        ConfigurationParameter("alpha", 0.1, ConfigurationSource.DEFAULT_ARGUMENT.value),
        ConfigurationParameter("alpha", 0.2, ConfigurationSource.CONFIG_FILE.value, "config.toml"),
        ConfigurationParameter("alpha", 0.3, ConfigurationSource.CLI_ARGUMENT.value),
        ConfigurationParameter("token", "secret", ConfigurationSource.ENVIRONMENT_VARIABLE.value, sensitive=True),
    ])
    alpha = next(item for item in traces if item.name == "alpha")
    assert alpha.resolved_value == 0.3 and alpha.resolved_source == "CLI_ARGUMENT"
    assert [item.selected for item in alpha.steps] == [False, False, True]
    assert next(item for item in traces if item.name == "token").resolved_value == "<redacted>"


def test_schema_audit_distinguishes_all_semantic_changes() -> None:
    before = DatasetSchema("netcdf", (FieldSchema("yield", "float64", (10, 20), ("time", "region"),
        ("time", "region"), "kg", "NaN", "zlib"),), ("time", "region"), "netcdf4")
    after = DatasetSchema("netcdf", (
        FieldSchema("yield", "float32", (20, 10), ("region", "time"), ("time", "region"), "t", "mask", "raw"),
        FieldSchema("quality", "int8", (10,), ("time",))), ("time", "region"), "hdf5")
    changes = compare_dataset_schemas(before, after)
    kinds = {item["kind"] for item in changes}
    assert {SchemaChangeKind.FIELD_ADDED.value, SchemaChangeKind.DTYPE_CHANGED.value,
            SchemaChangeKind.SHAPE_CHANGED.value, SchemaChangeKind.DIMENSION_ORDER_CHANGED.value,
            SchemaChangeKind.UNIT_CHANGED.value,
            SchemaChangeKind.MISSING_VALUE_SEMANTICS_CHANGED.value,
            SchemaChangeKind.SERIALIZATION_ENCODING_CHANGED.value} <= kinds
    schema = json.loads((ROOT / "schemas" / "dataset-schema.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(before.to_dict())


def test_unified_provenance_lineage_environment_and_public_explanations(tmp_path: Path) -> None:
    data = tmp_path / "input.csv"; data.write_text("yield\n1\n", encoding="utf-8")
    input_schema = DatasetSchema("csv", (FieldSchema("yield", "float64", (1,), ("row",), unit="kg"),))
    artifact = InputArtifact.inspect(data, schema=input_schema, hash_content=True)
    result = exact_result(input_artifacts=[artifact], configuration=[
        ConfigurationParameter("alpha", 0.1, ConfigurationSource.DEFAULT_ARGUMENT.value),
        ConfigurationParameter("alpha", 0.2, ConfigurationSource.USER_OVERRIDE.value)])
    graph = result.provenance_graph()
    schema = json.loads((ROOT / "schemas" / "research-provenance.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(graph)
    kinds = {item["kind"] for item in graph["nodes"]}
    assert {"SOURCE_CODE", "CONFIGURATION", "PARAMETER", "ENVIRONMENT", "INPUT_ARTIFACT",
            "INPUT_FIELD", "IMPLEMENTATION_IR", "MATHEMATICAL_IR", "ALGORITHM_IR",
            "VERIFICATION_CLAIM"} <= kinds
    environment = result.provenance["environment"]
    assert environment["evidence_level"] == "ENVIRONMENT_OBSERVATION_NOT_PROOF"
    assert result.provenance["data_lineage"]["field_edges"]
    assert result.provenance["git"]["dirty"] in {True, False}
    explanation = result.explain()
    assert {"what_was_analyzed", "recognized_mathematics", "data_and_configuration", "verified",
            "unresolved", "baseline_changes", "likely_failure_causes", "next_actions"} <= explanation.keys()


def test_semantic_baseline_diff_detects_parameter_and_schema_change(tmp_path: Path) -> None:
    first_schema = DatasetSchema("csv", (FieldSchema("x", "float64"),))
    second_schema = DatasetSchema("csv", (FieldSchema("x", "float32"),))
    before = exact_result(input_artifacts=[InputArtifact.inspect(tmp_path / "a.csv", schema=first_schema)],
        configuration=[ConfigurationParameter("alpha", 1, ConfigurationSource.DEFAULT_ARGUMENT.value)])
    baseline = before.accept_baseline()
    after = exact_result(input_artifacts=[InputArtifact.inspect(tmp_path / "a.csv", schema=second_schema)],
        configuration=[ConfigurationParameter("alpha", 2, ConfigurationSource.USER_OVERRIDE.value)])
    difference = baseline.diff(after)
    kinds = {item["kind"] for item in difference.changes}
    assert {"PARAMETER_CHANGED", "INPUT_SCHEMA_CHANGED"} <= kinds
    assert before.explain(baseline)["baseline_changes"]["status"] == "AUDIT_UNCHANGED"


def test_cache_key_invalidates_source_contract_and_registry_changes(tmp_path: Path) -> None:
    result = exact_result(); key = build_cache_key(result); cache = IncrementalAuditCache(tmp_path / "cache")
    cache.store(key, {"status": "FULLY_VERIFIED"})
    hit = cache.lookup(key)
    assert hit.status == "CACHE_HIT" and hit.verified_reuse_allowed
    stale = type(key)(key.source_hashes, key.formulatracer_version, key.ir_version,
                      key.contract_version + "-changed", key.knowledge_registry_version)
    miss = cache.lookup(stale)
    assert miss.status == "CACHE_MISS" and not miss.verified_reuse_allowed
    target = tmp_path / "cache" / f"{key.digest}.json"
    payload = json.loads(target.read_text(encoding="utf-8")); payload["cache_key"]["ir_version"] = "old"
    target.write_text(json.dumps(payload), encoding="utf-8")
    invalid = cache.lookup(key)
    assert invalid.status == "CACHE_STALE" and not invalid.verified_reuse_allowed
    cache.store(key, {"status": "FULLY_VERIFIED"})
    payload = json.loads(target.read_text(encoding="utf-8")); payload["value"]["status"] = "FAILED"
    target.write_text(json.dumps(payload), encoding="utf-8")
    tampered = cache.lookup(key)
    assert tampered.status == "CACHE_INVALID" and tampered.reason == "CACHE_VALUE_INTEGRITY_MISMATCH"
    assert not tampered.verified_reuse_allowed


def test_incremental_plan_finds_affected_root_and_unknown_change_fails_closed() -> None:
    result = exact_result(); current = dict(result.provenance["used_source_hashes"])
    module = next(iter(current)); current[module] = "changed"
    plan = plan_incremental_audit(result, current)
    assert module in plan.changed_modules and plan.affected_roots and plan.affected_outputs
    unknown = plan_incremental_audit(result, {**current, "unknown.module": "new"})
    assert unknown.full_reanalysis_required


def test_object_api_incremental_exact_cache_reuse(tmp_path: Path) -> None:
    tracer = FormulaTracer(EXACT, project_root=EXACT.parent); previous = tracer.analyze(ranges={"x": (1, 2)})
    cache = IncrementalAuditCache(tmp_path / "cache"); cache.store(build_cache_key(previous), previous.to_dict())
    incremental = tracer.analyze_incremental(previous, cache=cache, ranges={"x": (1, 2)})
    assert incremental.status == "INCREMENTAL_CACHE_REUSED"
    assert incremental.release_gates["CRITICAL_CACHE_FALSE_ACCEPTANCE_OPEN"] == 0


def test_debugger_exact_span_ground_truth_and_safe_minimal_reproducer(tmp_path: Path) -> None:
    result = exact_result(); theory = deepcopy(result.outputs[0].formula); theory["op"] = "Subtract"
    result.outputs[0].residual["theory_expression"] = theory
    debug = result.debug(); finding = debug.findings[0]
    assert finding.localization_level == "EXACT_SOURCE_SPAN"
    metrics = debug.evaluate_localization({finding.finding_id: finding.source})
    assert metrics.exact_span == metrics.correct_semantic_node == 1 and metrics.false_localization == 0
    reproducer = debug.create_reproducer(finding.finding_id, tmp_path / "reproducer")
    assert reproducer.status == "DIVERGENCE_REPRODUCED" and not reproducer.original_project_modified
    assert Path(reproducer.source_file).is_file()


def test_real_mutation_localization_corpus_has_zero_false_localization() -> None:
    operator_path = ROOT / "examples" / "semantic_debugger" / "wrong_operator.py"
    operator = FormulaTracer(operator_path, project_root=operator_path.parent).analyze(ranges={"kg": (0, 1)}).debug()
    constant_path = ROOT / "examples" / "semantic_debugger" / "cross_file" / "model.py"
    constant = FormulaTracer(constant_path, project_root=constant_path.parent).analyze(ranges={"kg": (0, 1)}).debug()
    op_finding, constant_finding = operator.findings[0], constant.findings[0]
    metrics = aggregate_localization_metrics([
        (operator, {op_finding.finding_id: {"file": str(operator_path.resolve()), "begin_line": 6,
            "begin_column": 20, "end_line": 6, "end_column": 21, "role": "operator", "operator": "*"}}),
        (constant, {constant_finding.finding_id: {"file": str((constant_path.parent / 'constants.py').resolve()),
            "begin_line": 1, "begin_column": 9, "end_line": 1, "end_column": 12}}),
    ])
    assert metrics.total == metrics.exact_span == metrics.correct_semantic_node == 2
    assert metrics.false_localization == metrics.unresolved == 0


def test_bundle_integrity_pack_profiles_candidates_and_sensitivity(tmp_path: Path) -> None:
    result = exact_result(); bundle = result.create_bundle(tmp_path / "bundle")
    assert verify_audit_bundle(bundle.path)["verified"]
    native = json.loads((Path(bundle.path) / "native-audit-bundle.json").read_text(encoding="utf-8"))
    payload = native["payload"]
    assert native["integrity_status"] == "AUDIT_BUNDLE_INTEGRITY_VERIFIED"
    assert len(native["payload_hash"]) == 64
    assert payload["claims"] == result.end_to_end_claims
    assert payload["theory"] == [output.theory for output in result.outputs]
    assert payload["implementation"] == [output.implementation for output in result.outputs]
    assert payload["mathematical_ir"] == [output.formula for output in result.outputs]
    assert payload["error"] == [output.total_error_bound for output in result.outputs]
    assert payload["range"] == [output.true_value_enclosure for output in result.outputs]
    assert payload["evidence"] == result.proofs
    assert payload["provenance"] == result.provenance
    (Path(bundle.path) / "mathematical-ir.json").write_text("tampered", encoding="utf-8")
    invalid = verify_audit_bundle(bundle.path)
    assert not invalid["verified"] and any("BUNDLE_HASH_MISMATCH" in item for item in invalid["diagnostics"])
    unsafe = ExtensionPackManifest("bad", "KNOWLEDGE", "1", ({"relation_kind": "EXACT"},))
    assert unsafe.validate()
    safe = ExtensionPackManifest("safe", "DOMAIN", "1", ({"relation_kind": "TRANSFORMATION",
        "evidence": "reference", "domain_constraints": [], "type_constraints": []},))
    assert not safe.validate()
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(json.dumps({"pack_id": "safe", "pack_kind": "DOMAIN", "version": "1",
        "entries": [{"relation_kind": "TRANSFORMATION", "evidence": "reference",
                     "domain_constraints": [], "type_constraints": []}]}), encoding="utf-8")
    assert load_extension_pack(pack_path).pack_id == "safe"
    assert profile_acceptance(result.status, AuditProfile.STRICT)["accepted_for_workflow"]
    assert not profile_acceptance("PROJECT_UNRESOLVED", AuditProfile.STRICT)["accepted_for_workflow"]
    assert profile_acceptance("PROJECT_UNRESOLVED", AuditProfile.EXPLORATORY)["accepted_for_workflow"]
    assert not profile_acceptance("PROJECT_UNRESOLVED", AuditProfile.EXPLORATORY)["truth_value_changed"]
    assert result.test_candidates()
    assert isinstance(result.sensitivity(), list)


def test_generated_code_sandbox_is_runtime_evidence_not_proof() -> None:
    blocked = run_sandboxed([sys.executable, "-c", "print('must not execute')"])
    assert blocked.status == "RUNTIME_EVIDENCE_BLOCKED_BY_SANDBOX_POLICY"
    evidence = run_sandboxed([sys.executable, "-c", "print(6 * 7)"],
                             policy=SandboxPolicy(network_disabled=False))
    assert evidence.status == "RUNTIME_EVIDENCE_SUCCEEDED" and evidence.stdout.strip() == "42"
    assert evidence.evidence_level == "RUNTIME_EVIDENCE" and not evidence.proof_authority
    assert evidence.network_control == "NETWORK_ALLOWED"


def test_provenance_adversarial_assurance_and_schema() -> None:
    report = run_provenance_assurance(); payload = report.to_dict()
    schema = json.loads((ROOT / "schemas" / "provenance-assurance-report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert report.status == "PROVENANCE_ASSURANCE_PASSED"
    assert not any(report.release_gates.values()) and all(item.detected for item in report.cases)


def test_egraph_rewrite_preserves_many_to_many_origin_set() -> None:
    first = {"file": "model.py", "begin_line": 1, "begin_column": 1, "end_line": 1, "end_column": 2}
    second = {"file": "model.py", "begin_line": 1, "begin_column": 5, "end_line": 1, "end_column": 6}
    left = {"op": "Add", "args": [{"op": "FreeVariable", "name": "x", "source_span": first},
                                      {"op": "Constant", "value": 0, "source_span": second}]}
    right = {"op": "FreeVariable", "name": "x"}
    result = saturate_and_match(left, right, authorized_rule_ids=["algebra_add_zero"],
        motifs=["add"], facts=["algebraic_structure:MONOID"])
    origin_set = result.graph.classes[result.graph.find(result.requested_eclass_id)].origin_set
    assert first in origin_set and second in origin_set
