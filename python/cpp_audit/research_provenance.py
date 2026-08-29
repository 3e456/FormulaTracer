"""Unified research provenance, schema lineage, incremental audit, and explanations.

This module enriches :class:`ProjectAuditResult`; it does not create a second
analysis pipeline.  Observations (environment, git, runtime) are explicitly
non-proof evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from functools import lru_cache
from importlib import metadata
import json
import locale
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence


def _execute_native_kernel(request: dict[str, Any]) -> dict[str, Any]:
    # Local import keeps the public cpp_audit/formulatracer facade cycle-free.
    from formulatracer.native import execute_native_kernel
    return execute_native_kernel(request)


PROVENANCE_SCHEMA_VERSION = "1.0"
IR_SCHEMA_VERSION = "1.0"
FORMULATRACER_VERSION = "0.1.0"


def _serial(value: Any) -> Any:
    if is_dataclass(value): return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict): return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_serial(item) for item in value]
    if isinstance(value, Enum): return value.value
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(_serial(value), ensure_ascii=False, sort_keys=True, default=str,
                         separators=(",", ":")).encode()
    return sha256(payload).hexdigest()


class ProvenanceNodeKind(str, Enum):
    SOURCE = "SOURCE_CODE"
    CONFIGURATION = "CONFIGURATION"
    PARAMETER = "PARAMETER"
    ENVIRONMENT = "ENVIRONMENT"
    DEPENDENCY = "LIBRARY_DEPENDENCY"
    INPUT_ARTIFACT = "INPUT_ARTIFACT"
    INPUT_FIELD = "INPUT_FIELD"
    MATHEMATICAL_IR = "MATHEMATICAL_IR"
    IMPLEMENTATION_IR = "IMPLEMENTATION_IR"
    ALGORITHM_IR = "ALGORITHM_IR"
    GENERATED_CODE = "GENERATED_CODE"
    INTERMEDIATE_DATASET = "INTERMEDIATE_DATASET"
    OUTPUT_ARTIFACT = "OUTPUT_ARTIFACT"
    VERIFICATION_CLAIM = "VERIFICATION_CLAIM"
    TRANSFORMATION = "TRANSFORMATION"


class ProvenanceEdgeKind(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"
    DERIVED_FROM = "DERIVED_FROM"
    CONFIGURES = "CONFIGURES"
    READS = "READS"
    WRITES = "WRITES"
    TRANSFORMS = "TRANSFORMS"
    VERIFIES = "VERIFIES"
    SELECTS_PROVIDER = "SELECTS_PROVIDER"
    SERIALIZES = "SERIALIZES"
    OVERRIDES = "OVERRIDES"


@dataclass(frozen=True)
class ProvenanceNode:
    node_id: str
    kind: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None
    evidence_level: str = "OBSERVATION"
    proof_authority: bool = False
    origin_set: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ProvenanceEdge:
    edge_id: str
    kind: str
    source: str
    target: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchProvenanceGraph:
    nodes: list[ProvenanceNode] = field(default_factory=list)
    edges: list[ProvenanceEdge] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = PROVENANCE_SCHEMA_VERSION

    def add_node(self, kind: ProvenanceNodeKind | str, label: str, *, metadata: Mapping[str, Any] | None = None,
                 content_hash: str | None = None, evidence_level: str = "OBSERVATION",
                 proof_authority: bool = False, origin_set: Iterable[Mapping[str, Any]] = ()) -> str:
        kind_value = kind.value if isinstance(kind, Enum) else str(kind)
        node_id = "provenance:" + _digest([kind_value, label, content_hash, metadata])[:20]
        if node_id not in {item.node_id for item in self.nodes}:
            self.nodes.append(ProvenanceNode(node_id, kind_value, label, dict(metadata or {}), content_hash,
                                             evidence_level, proof_authority,
                                             tuple(dict(item) for item in origin_set)))
        return node_id

    def add_edge(self, kind: ProvenanceEdgeKind | str, source: str, target: str,
                 metadata: Mapping[str, Any] | None = None) -> str:
        kind_value = kind.value if isinstance(kind, Enum) else str(kind)
        edge_id = "provenance-edge:" + _digest([kind_value, source, target, metadata])[:20]
        if edge_id not in {item.edge_id for item in self.edges}:
            self.edges.append(ProvenanceEdge(edge_id, kind_value, source, target, dict(metadata or {})))
        return edge_id

    def validate(self) -> list[str]:
        ids = {item.node_id for item in self.nodes}; diagnostics = []
        if len(ids) != len(self.nodes): diagnostics.append("DUPLICATE_PROVENANCE_NODE")
        for edge in self.edges:
            if edge.source not in ids or edge.target not in ids:
                diagnostics.append(f"DANGLING_PROVENANCE_EDGE:{edge.edge_id}")
        return diagnostics

    def to_dict(self) -> dict[str, Any]:
        value = _serial(self); value["graph_hash"] = _digest(value); return value


class ConfigurationSource(str, Enum):
    DEFAULT_ARGUMENT = "DEFAULT_ARGUMENT"
    CONFIG_FILE = "CONFIG_FILE"
    CLI_ARGUMENT = "CLI_ARGUMENT"
    ENVIRONMENT_VARIABLE = "ENVIRONMENT_VARIABLE"
    USER_OVERRIDE = "USER_OVERRIDE"
    DERIVED_PARAMETER = "DERIVED_PARAMETER"


_CONFIG_PRECEDENCE = {
    ConfigurationSource.DEFAULT_ARGUMENT.value: 0,
    ConfigurationSource.CONFIG_FILE.value: 10,
    ConfigurationSource.ENVIRONMENT_VARIABLE.value: 20,
    ConfigurationSource.CLI_ARGUMENT.value: 30,
    ConfigurationSource.USER_OVERRIDE.value: 40,
    ConfigurationSource.DERIVED_PARAMETER.value: 50,
}


@dataclass(frozen=True)
class ConfigurationParameter:
    name: str
    value: Any
    source: str
    source_location: str | None = None
    sensitive: bool = False
    dependencies: tuple[str, ...] = ()

    def public_value(self) -> Any: return "<redacted>" if self.sensitive else self.value


@dataclass(frozen=True)
class ParameterResolutionStep:
    source: str
    value: Any
    selected: bool
    reason: str
    source_location: str | None = None


@dataclass(frozen=True)
class ParameterResolutionTrace:
    name: str
    resolved_value: Any
    resolved_source: str
    steps: tuple[ParameterResolutionStep, ...]
    status: str = "PARAMETER_RESOLVED"


def _reference_resolve_configuration(parameters: Iterable[ConfigurationParameter]) -> list[ParameterResolutionTrace]:
    grouped: dict[str, list[ConfigurationParameter]] = {}
    for item in parameters:
        ConfigurationSource(item.source)
        grouped.setdefault(item.name, []).append(item)
    traces = []
    for name, values in sorted(grouped.items()):
        ranked = sorted(enumerate(values), key=lambda item: (_CONFIG_PRECEDENCE[item[1].source], item[0]))
        winner = ranked[-1][1]
        steps = tuple(ParameterResolutionStep(item.source, item.public_value(), item is winner,
            "HIGHEST_PRECEDENCE_LAST_OVERRIDE" if item is winner else f"OVERRIDDEN_BY:{winner.source}",
            item.source_location) for _, item in ranked)
        traces.append(ParameterResolutionTrace(name, winner.public_value(), winner.source, steps))
    return traces


def resolve_configuration(parameters: Iterable[ConfigurationParameter]) -> list[ParameterResolutionTrace]:
    """Thin projection of the Rust-owned precedence and redaction decision."""
    raw = [_serial(item) for item in parameters]
    result = _execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "RESOLVE_CONFIGURATION", "parameters": raw})["result"]
    return [ParameterResolutionTrace(str(item["name"]), item.get("resolved_value"),
        str(item["resolved_source"]), tuple(ParameterResolutionStep(str(step["source"]),
            step.get("value"), bool(step.get("selected")), str(step.get("reason")),
            step.get("source_location")) for step in item.get("steps", [])),
        str(item.get("status", "PARAMETER_RESOLVED"))) for item in result]


@dataclass(frozen=True)
class FieldSchema:
    name: str
    dtype: str | None = None
    shape: tuple[int | None, ...] = ()
    dimensions: tuple[str, ...] = ()
    coordinates: tuple[str, ...] = ()
    unit: str | None = None
    missing_value_semantics: str | None = None
    encoding: str | None = None


@dataclass(frozen=True)
class DatasetSchema:
    format: str
    fields: tuple[FieldSchema, ...]
    dimensions: tuple[str, ...] = ()
    encoding: str | None = None
    schema_id: str | None = None

    def to_dict(self) -> dict[str, Any]: return _serial(self)


class SchemaChangeKind(str, Enum):
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_ADDED = "FIELD_ADDED"
    DTYPE_CHANGED = "DTYPE_CHANGED"
    SHAPE_CHANGED = "SHAPE_CHANGED"
    DIMENSION_CHANGED = "DIMENSION_CHANGED"
    DIMENSION_ORDER_CHANGED = "DIMENSION_ORDER_CHANGED"
    UNIT_CHANGED = "UNIT_CHANGED"
    MISSING_VALUE_SEMANTICS_CHANGED = "MISSING_VALUE_SEMANTICS_CHANGED"
    SERIALIZATION_ENCODING_CHANGED = "SERIALIZATION_ENCODING_CHANGED"


def _reference_compare_dataset_schemas(before: DatasetSchema, after: DatasetSchema) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    left, right = {item.name: item for item in before.fields}, {item.name: item for item in after.fields}
    for name in sorted(left.keys() - right): changes.append({"kind": SchemaChangeKind.FIELD_MISSING.value, "field": name})
    for name in sorted(right.keys() - left): changes.append({"kind": SchemaChangeKind.FIELD_ADDED.value, "field": name})
    comparisons = (("dtype", SchemaChangeKind.DTYPE_CHANGED), ("shape", SchemaChangeKind.SHAPE_CHANGED),
                   ("unit", SchemaChangeKind.UNIT_CHANGED),
                   ("missing_value_semantics", SchemaChangeKind.MISSING_VALUE_SEMANTICS_CHANGED),
                   ("encoding", SchemaChangeKind.SERIALIZATION_ENCODING_CHANGED))
    for name in sorted(left.keys() & right):
        old, new = left[name], right[name]
        if set(old.dimensions) != set(new.dimensions):
            changes.append({"kind": SchemaChangeKind.DIMENSION_CHANGED.value, "field": name,
                            "before": list(old.dimensions), "after": list(new.dimensions)})
        elif old.dimensions != new.dimensions:
            changes.append({"kind": SchemaChangeKind.DIMENSION_ORDER_CHANGED.value, "field": name,
                            "before": list(old.dimensions), "after": list(new.dimensions)})
        for attribute, kind in comparisons:
            if getattr(old, attribute) != getattr(new, attribute):
                changes.append({"kind": kind.value, "field": name,
                                "before": _serial(getattr(old, attribute)), "after": _serial(getattr(new, attribute))})
    if before.encoding != after.encoding:
        changes.append({"kind": SchemaChangeKind.SERIALIZATION_ENCODING_CHANGED.value,
                        "field": None, "before": before.encoding, "after": after.encoding})
    return changes


def compare_dataset_schemas(before: DatasetSchema, after: DatasetSchema) -> list[dict[str, Any]]:
    return list(_execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "COMPARE_DATASET_SCHEMAS", "before": before.to_dict(),
        "after": after.to_dict()})["result"])


@dataclass(frozen=True)
class InputArtifact:
    artifact_id: str
    source_type: str
    location: str
    content_hash: str | None
    size: int | None
    modified_timestamp: str | None
    schema: DatasetSchema | None = None
    hash_status: str = "HASH_NOT_REQUESTED"

    @classmethod
    def inspect(cls, location: str | Path, *, source_type: str = "FILE", schema: DatasetSchema | None = None,
                hash_content: bool = False, max_hash_bytes: int = 64 * 1024 * 1024) -> "InputArtifact":
        text = str(location); path = Path(location)
        digest = None; size = None; modified = None; status = "HASH_NOT_REQUESTED"
        if path.is_file():
            stat = path.stat(); size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()
            if hash_content and size <= max_hash_bytes:
                digest = sha256(path.read_bytes()).hexdigest(); status = "CONTENT_HASHED"
            elif hash_content: status = "HASH_SKIPPED_SIZE_LIMIT"
        elif "://" in text: status = "REMOTE_CONTENT_NOT_FETCHED"
        else: status = "INPUT_NOT_FOUND"
        return cls("input:" + _digest([text, digest, size])[:20], source_type, text, digest, size, modified,
                   schema, status)


@dataclass(frozen=True)
class EnvironmentSnapshot:
    os: str
    architecture: str
    python_version: str
    rust_toolchain: str | None
    cpp_toolchain: str | None
    libraries: dict[str, str]
    cpu: str | None
    gpu: str | None
    blas_backend: str | None
    locale: str | None
    timezone: str | None
    evidence_level: str = "ENVIRONMENT_OBSERVATION_NOT_PROOF"


@lru_cache(maxsize=64)
def _capture_environment_cached(package_names: tuple[str, ...]) -> EnvironmentSnapshot:
    versions = {}
    for package in package_names:
        try: versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError: versions[package] = "UNVERIFIED"
    try: current_locale = locale.getlocale()[0]
    except ValueError: current_locale = None
    rust, cpp = _toolchain_versions(os.environ.get("CXX", "c++"))
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES") or os.environ.get("ROCR_VISIBLE_DEVICES")
    blas = None
    if "numpy" in versions:
        try:
            import numpy as np
            config = getattr(np.__config__, "CONFIG", {})
            blas = str(config.get("Build Dependencies", {}).get("blas", {}).get("name") or "UNRESOLVED")
        except (ImportError, AttributeError, TypeError): blas = "UNRESOLVED"
    return EnvironmentSnapshot(platform.system() + " " + platform.release(), platform.machine(),
        platform.python_version(), rust, cpp, versions, platform.processor() or None, gpu, blas,
        current_locale, time.tzname[0] if time.tzname else None)


@lru_cache(maxsize=4)
def _toolchain_versions(cxx: str) -> tuple[str | None, str | None]:
    def tool_version(*commands: tuple[str, ...]) -> str | None:
        for command in commands:
            try:
                completed = subprocess.run(command, text=True, capture_output=True, timeout=3, check=False)
            except (OSError, subprocess.TimeoutExpired): continue
            if completed.returncode == 0:
                return (completed.stdout or completed.stderr).splitlines()[0].strip()
        return None
    return tool_version(("rustc", "--version")), tool_version((cxx, "--version"), ("cl",))


def capture_environment(packages: Iterable[str] = ()) -> EnvironmentSnapshot:
    """Capture process-static environment facts once per observed package set.

    The package set is part of the cache key. The snapshot remains observation,
    never proof evidence; callers receive a fresh library mapping so they cannot
    mutate the cached value.
    """
    names = tuple(sorted(set(str(item).split(".", 1)[0] for item in packages if item)))
    snapshot = _capture_environment_cached(names)
    return EnvironmentSnapshot(**{**asdict(snapshot), "libraries": dict(snapshot.libraries)})


@dataclass(frozen=True)
class GitSourceProvenance:
    repository: str | None
    commit_sha: str | None
    branch: str | None
    dirty: bool | None
    status: str


def capture_git_provenance(root: str | Path) -> GitSourceProvenance:
    path = Path(root)
    def run(*args: str) -> str | None:
        try:
            completed = subprocess.run(["git", *args], cwd=path, text=True, capture_output=True,
                                       timeout=5, check=False)
            return completed.stdout.strip() if completed.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired): return None
    repository = run("rev-parse", "--show-toplevel")
    if not repository: return GitSourceProvenance(None, None, None, None, "NOT_A_GIT_REPOSITORY")
    status = run("status", "--porcelain")
    return GitSourceProvenance(repository, run("rev-parse", "HEAD"), run("branch", "--show-current"),
                               bool(status), "GIT_PROVENANCE_CAPTURED")


@dataclass(frozen=True)
class DependencyProvenance:
    name: str
    version: str
    contract_version: str | None
    reference_provenance: str | None
    selected_provider: str | None = None


@dataclass(frozen=True)
class DatasetTransformation:
    transformation_id: str
    kind: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    field_mapping: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source_spans: tuple[dict[str, Any], ...] = ()


@dataclass
class DataLineage:
    transformations: list[DatasetTransformation]
    artifact_dependencies: list[dict[str, Any]]
    field_edges: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]: return _serial(self)


def _output_origins(output: Any) -> list[dict[str, Any]]:
    origins = []
    for item in getattr(output, "source_locations", []) or []:
        if isinstance(item, dict) and item not in origins: origins.append(dict(item))
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("source_span",):
                if isinstance(node.get(key), dict) and node[key] not in origins: origins.append(dict(node[key]))
            for item in node.get("source_spans", []):
                if isinstance(item, dict) and item not in origins: origins.append(dict(item))
            for value in node.values(): visit(value)
        elif isinstance(node, list):
            for value in node: visit(value)
    visit(getattr(output, "formula", None)); return origins


def _reference_build_data_lineage(result: Any, input_artifacts: Sequence[InputArtifact] = ()) -> DataLineage:
    transformations = []; dependencies = []; fields = []
    input_ids = tuple(item.artifact_id for item in input_artifacts)
    for output in result.outputs:
        output_ref = "output:" + str(output.output_id)
        sources = input_ids or tuple("symbol:" + str(item) for item in output.dependencies)
        transformation = DatasetTransformation("lineage:" + _digest([sources, output_ref, output.formula])[:20],
            "NUMERIC_TRANSFORMATION", sources, (output_ref,),
            {output.name: tuple(str(item) for item in output.dependencies)}, tuple(_output_origins(output)))
        transformations.append(transformation)
        for source in sources: fields.append({"source": source, "target": output_ref + "::" + output.name,
                                               "kind": "FIELD_DERIVED_FROM"})
        for artifact in result.artifacts:
            if artifact.payload_symbol == output.name or artifact.dataset_variable == output.name:
                target = "artifact:" + artifact.sink_id
                dependencies.append({"source": output_ref, "target": target, "kind": "ARTIFACT_DEPENDENCY",
                                     "serialization_status": artifact.serialization_boundary.status})
                fields.append({"source": output_ref + "::" + output.name,
                               "target": target + "::" + (artifact.dataset_variable or output.name),
                               "kind": "FIELD_SERIALIZED_TO"})
    return DataLineage(transformations, dependencies, fields)


def build_data_lineage(result: Any, input_artifacts: Sequence[InputArtifact] = ()) -> DataLineage:
    raw = _execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "BUILD_DATA_LINEAGE", "project": result.to_dict(),
        "input_artifacts": [_serial(item) for item in input_artifacts]})["result"]
    transformations = [DatasetTransformation(str(item["transformation_id"]), str(item["kind"]),
        tuple(str(value) for value in item.get("inputs", [])),
        tuple(str(value) for value in item.get("outputs", [])),
        {str(key): tuple(str(value) for value in values) for key, values in item.get("field_mapping", {}).items()},
        tuple(dict(value) for value in item.get("source_spans", [])))
        for item in raw.get("transformations", [])]
    return DataLineage(transformations, list(raw.get("artifact_dependencies", [])),
                       list(raw.get("field_edges", [])))


class AuditProfile(str, Enum):
    STRICT = "STRICT"
    RESEARCH = "RESEARCH"
    EXPLORATORY = "EXPLORATORY"


_PROFILE_ACCEPTANCE = {
    AuditProfile.STRICT.value: {
        "PROJECT_FULLY_VERIFIED", "END_TO_END_KERNEL_VERIFIED", "END_TO_END_ENCLOSURE_VERIFIED",
    },
    AuditProfile.RESEARCH.value: {
        "PROJECT_FULLY_VERIFIED", "PROJECT_VERIFIED_UNDER_ASSUMPTIONS",
        "END_TO_END_KERNEL_VERIFIED", "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS",
        "END_TO_END_ENCLOSURE_VERIFIED", "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS",
    },
    AuditProfile.EXPLORATORY.value: {
        "PROJECT_FULLY_VERIFIED", "PROJECT_VERIFIED_UNDER_ASSUMPTIONS", "PROJECT_PARTIALLY_VERIFIED",
        "PROJECT_UNRESOLVED", "END_TO_END_KERNEL_VERIFIED", "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS",
        "END_TO_END_ENCLOSURE_VERIFIED", "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS",
        "PARTIAL_END_TO_END_VERIFICATION", "END_TO_END_UNRESOLVED",
    },
}


def profile_acceptance(status: str | Enum, profile: AuditProfile | str) -> dict[str, Any]:
    selected = profile.value if isinstance(profile, Enum) else AuditProfile(profile).value
    claim_status = status.value if isinstance(status, Enum) else str(status)
    return {"profile": selected, "claim_status": claim_status,
            "accepted_for_workflow": claim_status in _PROFILE_ACCEPTANCE[selected],
            "truth_value_changed": False}


@dataclass(frozen=True)
class MissingEvidence:
    evidence_id: str
    reason: str
    affected_claims: tuple[str, ...]
    user_action: str
    blocked_subsystem: str


@dataclass(frozen=True)
class ResolutionSuggestion:
    code: str
    title: str
    missing_evidence: tuple[MissingEvidence, ...]


def explain_unresolved(result: Any) -> list[ResolutionSuggestion]:
    suggestions = []
    seen = set()
    obligations = list(getattr(result, "diagnostics", []))
    for output in result.outputs:
        obligations += list(output.remaining_obligations or []) + list(output.range_obligations or [])
        if output.range_status and "UNRESOLVED" in output.range_status:
            obligations.append({"code": "RANGE_UNRESOLVED", "output": output.name})
    for item in obligations:
        text = json.dumps(_serial(item), sort_keys=True, default=str)
        code = str(item.get("code") or item.get("diagnostic_code") or item.get("obligation") or "UNRESOLVED") if isinstance(item, dict) else "UNRESOLVED"
        key = (code, text)
        if key in seen: continue
        seen.add(key)
        lowered = text.lower()
        if "range" in lowered:
            reason, action, subsystem = "Required input/domain range evidence is missing.", "Provide ranges={name: (lower, upper)}.", "Interval/Range analysis"
        elif "ffi" in lowered:
            reason, action, subsystem = "Cross-language representation mapping is unresolved.", "Provide an FFI representation contract.", "FFI verification"
        elif "serial" in lowered or "schema" in lowered:
            reason, action, subsystem = "Artifact schema or serialization preservation evidence is missing.", "Provide expected DatasetSchema or serializer contract evidence.", "Artifact verification"
        elif "assumption" in lowered or "condition" in lowered:
            reason, action, subsystem = "A required mathematical assumption has not been discharged.", "Provide the stated domain/type/shape assumption or proof.", "Theory/e-graph verification"
        else:
            reason, action, subsystem = "The audit lacks evidence required by this obligation.", "Inspect the obligation payload and provide its requested contract or fact.", "Audit verification"
        affected = tuple(str(value) for value in ([item.get("output")] if isinstance(item, dict) and item.get("output") else []))
        evidence = MissingEvidence("missing:" + _digest(item)[:16], reason, affected, action, subsystem)
        suggestions.append(ResolutionSuggestion(code, code.replace("_", " ").title(), (evidence,)))
    return suggestions


def explain_result(result: Any, baseline_diff: Any = None) -> dict[str, Any]:
    recognized = sorted({str((output.formula or {}).get("op", "UNRESOLVED")) for output in result.outputs})
    graph = result.provenance.get("research_provenance_graph", {})
    return {"what_was_analyzed": {"modules": len(result.modules), "outputs": [item.name for item in result.outputs]},
            "recognized_mathematics": recognized,
            "data_and_configuration": {"inputs": result.provenance.get("input_artifacts", []),
                                       "parameters": result.provenance.get("configuration_resolution", [])},
            "verified": [item for item in result.proofs if "VERIFIED" in str(item)],
            "unresolved": [_serial(item) for item in explain_unresolved(result)],
            "baseline_changes": baseline_diff.to_dict() if hasattr(baseline_diff, "to_dict") else baseline_diff,
            "likely_failure_causes": [item.get("code") for item in result.diagnostics],
            "next_actions": [evidence.user_action for item in explain_unresolved(result) for evidence in item.missing_evidence],
            "provenance_coverage": provenance_coverage(graph)}


@dataclass(frozen=True)
class AcceptedAuditBaseline:
    baseline_id: str
    audit_hash: str
    accepted_status: str
    snapshot: dict[str, Any]
    accepted_at: str

    @classmethod
    def from_result(cls, result: Any) -> "AcceptedAuditBaseline":
        snapshot = result.to_dict()
        return cls("baseline:" + _digest(snapshot)[:20], _digest(snapshot), str(result.status), snapshot,
                   datetime.now().astimezone().isoformat())

    def diff(self, current: Any) -> Any:
        from .assurance_release import audit_diff
        class Snapshot:
            def __init__(self, value: dict[str, Any]): self.value = value
            def to_dict(self) -> dict[str, Any]: return self.value
        return audit_diff(Snapshot(self.snapshot), current)


def provenance_coverage(graph: Mapping[str, Any]) -> dict[str, Any]:
    kinds = {item.get("kind") for item in graph.get("nodes", []) if isinstance(item, dict)}
    required = {item.value for item in ProvenanceNodeKind}
    return {"covered_kinds": len(kinds & required), "required_kinds": len(required),
            "coverage_percent": round(100 * len(kinds & required) / len(required), 2),
            "missing_kinds": sorted(required - kinds)}


@dataclass(frozen=True)
class AuditCacheKey:
    source_hashes: tuple[tuple[str, str], ...]
    formulatracer_version: str
    ir_version: str
    contract_version: str
    knowledge_registry_version: str

    @property
    def digest(self) -> str: return _digest(self)


def build_cache_key(result: Any) -> AuditCacheKey:
    from .mathematical_knowledge import MathematicalKnowledgeRegistry
    knowledge = MathematicalKnowledgeRegistry.default()
    return AuditCacheKey(tuple(sorted(result.provenance.get("used_source_hashes", {}).items())),
        FORMULATRACER_VERSION, IR_SCHEMA_VERSION,
        str(result.provenance.get("library_contract_registry_hash", "UNRESOLVED")),
        _digest([knowledge.metrics(), [item.to_dict() for item in knowledge.entries()]]))


@dataclass(frozen=True)
class CacheLookupResult:
    status: str
    value: Any | None
    reason: str
    verified_reuse_allowed: bool


class IncrementalAuditCache:
    """Small content-addressed cache with exact-key, fail-closed reuse."""
    def __init__(self, root: str | Path): self.root = Path(root)

    def store(self, key: AuditCacheKey, value: Mapping[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{key.digest}.json"
        serialized_value = _serial(value)
        payload = {"cache_key": _serial(key), "cache_key_digest": key.digest,
                   "value_digest": _digest(serialized_value), "value": serialized_value}
        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return target

    def lookup(self, key: AuditCacheKey) -> CacheLookupResult:
        target = self.root / f"{key.digest}.json"
        if not target.is_file(): return CacheLookupResult("CACHE_MISS", None, "EXACT_KEY_NOT_FOUND", False)
        try: payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return CacheLookupResult("CACHE_INVALID", None, "CACHE_UNREADABLE", False)
        if payload.get("cache_key_digest") != key.digest or payload.get("cache_key") != _serial(key):
            return CacheLookupResult("CACHE_STALE", None, "CACHE_KEY_OR_VERSION_MISMATCH", False)
        if payload.get("value_digest") != _digest(payload.get("value")):
            return CacheLookupResult("CACHE_INVALID", None, "CACHE_VALUE_INTEGRITY_MISMATCH", False)
        return CacheLookupResult("CACHE_HIT", payload.get("value"), "ALL_KEY_COMPONENTS_MATCH", True)


@dataclass(frozen=True)
class IncrementalAuditPlan:
    changed_modules: tuple[str, ...]
    affected_modules: tuple[str, ...]
    affected_roots: tuple[str, ...]
    affected_outputs: tuple[str, ...]
    cache_status: str
    full_reanalysis_required: bool


@dataclass
class IncrementalAuditResult:
    status: str
    plan: IncrementalAuditPlan
    result: Any
    semantic_diff: Any
    cache_status: str
    release_gates: dict[str, int]
    elapsed_seconds: float


def current_source_hashes(previous: Any) -> dict[str, str]:
    values = {}
    for module in previous.modules:
        path = Path(module.path)
        if not path.is_file():
            continue
        # Frontends intentionally differ in whether their module identity is
        # based on raw bytes (C/C++) or decoded source text (Python/Rust).  On
        # Windows, decoded text also normalizes CRLF to LF.  Recompute both
        # representations and select the one used by the recorded module;
        # any real content change still produces a different hash.
        raw_hash = sha256(path.read_bytes()).hexdigest()
        try:
            text_hash = sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        except UnicodeError:
            text_hash = raw_hash
        recorded = str(getattr(module, "source_hash", ""))
        values[module.name] = recorded if recorded in {raw_hash, text_hash} else raw_hash
    return values


def run_incremental_audit(tracer: Any, previous: Any, *, cache: IncrementalAuditCache | None = None,
                          analyze_options: Mapping[str, Any] | None = None) -> IncrementalAuditResult:
    started = time.perf_counter(); hashes = current_source_hashes(previous)
    plan = plan_incremental_audit(previous, hashes); old_key = build_cache_key(previous)
    if not plan.changed_modules and cache is not None:
        lookup = cache.lookup(old_key)
        if lookup.verified_reuse_allowed:
            from .assurance_release import audit_diff
            unchanged = audit_diff(previous, previous)
            return IncrementalAuditResult("INCREMENTAL_CACHE_REUSED", plan, previous, unchanged,
                lookup.status, {"CRITICAL_CACHE_FALSE_ACCEPTANCE_OPEN": 0,
                                "CRITICAL_INCREMENTAL_REGRESSION_OPEN": 0}, time.perf_counter() - started)
    # Unknown files/dependency closure require a full analysis. Otherwise pass
    # affected output names to the existing object API; no alternate analyzer.
    targets = None if plan.full_reanalysis_required else [output.name for output in previous.outputs
              if output.output_id in set(plan.affected_outputs)]
    current = tracer.analyze(targets or None, **dict(analyze_options or {}))
    difference = previous.diff(current)
    if cache is not None: cache.store(build_cache_key(current), current.to_dict())
    # A changed proof payload is not necessarily a regression (it may be an
    # improvement or an equivalent re-proof).  The release gate only opens
    # when the externally reported verification state becomes weaker.
    strength = {
        "PROJECT_FAILED": 0, "END_TO_END_FAILED": 0,
        "PROJECT_UNRESOLVED": 1, "END_TO_END_UNRESOLVED": 1,
        "PROJECT_PARTIALLY_VERIFIED": 2, "PARTIAL_END_TO_END_VERIFICATION": 2,
        "PROJECT_VERIFIED_UNDER_ASSUMPTIONS": 3,
        "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS": 3,
        "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS": 3,
        "PROJECT_FULLY_VERIFIED": 4, "END_TO_END_KERNEL_VERIFIED": 4,
        "END_TO_END_ENCLOSURE_VERIFIED": 4,
    }
    before_raw = getattr(previous, "end_to_end_status", None) or previous.status
    after_raw = getattr(current, "end_to_end_status", None) or current.status
    before_status = before_raw.value if isinstance(before_raw, Enum) else str(before_raw)
    after_status = after_raw.value if isinstance(after_raw, Enum) else str(after_raw)
    proof_regressions = int(strength.get(after_status, -1) < strength.get(before_status, -1))
    return IncrementalAuditResult("INCREMENTAL_REAUDIT_COMPLETE", plan, current, difference,
        "CACHE_INVALIDATED" if plan.changed_modules else "CACHE_MISS",
        {"CRITICAL_CACHE_FALSE_ACCEPTANCE_OPEN": 0,
         "CRITICAL_INCREMENTAL_REGRESSION_OPEN": proof_regressions}, time.perf_counter() - started)


def plan_incremental_audit(previous: Any, current_source_hashes: Mapping[str, str]) -> IncrementalAuditPlan:
    old = previous.provenance.get("used_source_hashes", {})
    changed = {name for name in set(old) | set(current_source_hashes) if old.get(name) != current_source_hashes.get(name)}
    reverse: dict[str, set[str]] = {}
    for edge in previous.project_graph.edges:
        reverse.setdefault(str(edge.target), set()).add(str(edge.source))
    module_ids = {module.name: module.module_id for module in previous.modules}
    id_names = {module.module_id: module.name for module in previous.modules}
    affected = set(changed) | {module_ids[name] for name in changed if name in module_ids}
    queue = list(affected)
    while queue:
        current = queue.pop(0)
        for parent in reverse.get(current, ()):
            if parent not in affected: affected.add(parent); queue.append(parent)
    affected_names = affected | {id_names[item] for item in affected if item in id_names}
    roots = tuple(sorted(root.root_id for root in previous.roots if root.entry_module in affected_names or
                         any(dependency in affected_names or any(str(dependency).startswith(name + "::")
                             for name in affected_names) for dependency in root.dependency_slice)))
    outputs = tuple(sorted(output.output_id for root in previous.roots if root.root_id in roots for output in root.outputs))
    unknown = any(name not in module_ids for name in changed)
    return IncrementalAuditPlan(tuple(sorted(changed)), tuple(sorted(affected_names)), roots, outputs,
        "CACHE_INVALIDATED" if changed else "CACHE_KEY_UNCHANGED", unknown)


@dataclass(frozen=True)
class ExtensionPackManifest:
    pack_id: str
    pack_kind: str
    version: str
    entries: tuple[dict[str, Any], ...]

    def validate(self) -> list[str]:
        diagnostics = []
        if self.pack_kind not in {"KNOWLEDGE", "PROVIDER", "DOMAIN"}: diagnostics.append("UNSUPPORTED_PACK_KIND")
        for index, entry in enumerate(self.entries):
            for required in ("evidence", "relation_kind", "domain_constraints", "type_constraints"):
                if required not in entry: diagnostics.append(f"PACK_ENTRY_REQUIRED_FIELD_MISSING:{index}:{required}")
            if entry.get("relation_kind") in {"EXACT", "EXACT_UNDER_ASSUMPTIONS"} and not entry.get("evidence"):
                diagnostics.append(f"UNSAFE_EXACT_PACK_ENTRY:{index}")
        return diagnostics


def load_extension_pack(path: str | Path) -> ExtensionPackManifest:
    """Load a declarative pack without importing or executing pack code.

    JSON is always supported. YAML is accepted when PyYAML is installed; its
    safe loader is mandatory. Any validation diagnostic rejects the pack.
    """
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        payload = json.loads(text)
    elif source.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as error:
            raise ValueError("YAML_EXTENSION_PACK_REQUIRES_PYYAML") from error
        payload = yaml.safe_load(text)
    else:
        raise ValueError("UNSUPPORTED_EXTENSION_PACK_FORMAT")
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("INVALID_EXTENSION_PACK_STRUCTURE")
    manifest = ExtensionPackManifest(
        str(payload.get("pack_id", "")), str(payload.get("pack_kind", "")),
        str(payload.get("version", "")), tuple(dict(item) for item in payload["entries"]),
    )
    diagnostics = manifest.validate()
    if not manifest.pack_id or not manifest.version:
        diagnostics.append("PACK_ID_OR_VERSION_MISSING")
    if diagnostics:
        raise ValueError(";".join(diagnostics))
    return manifest


KnowledgePack = ExtensionPackManifest
ProviderPack = ExtensionPackManifest
DomainPack = ExtensionPackManifest


@dataclass(frozen=True)
class TestCaseCandidate:
    candidate_id: str
    kind: str
    inputs: dict[str, Any]
    rationale: str
    writes_user_repository: bool = False


def generate_test_candidates(result: Any) -> list[TestCaseCandidate]:
    candidates = []; seen = set()
    ranges = (result.provenance.get("range_specification") or {}).get("ranges", [])
    for item in ranges:
        name, lower, upper = item.get("name"), item.get("lower"), item.get("upper")
        for label, value in (("LOWER_BOUND", lower), ("UPPER_BOUND", upper), ("ZERO", 0), ("ONE", 1)):
            if name is None or value is None or (name, value) in seen: continue
            seen.add((name, value)); candidates.append(TestCaseCandidate(
                "test-candidate:" + _digest([name, value, label])[:16], label, {str(name): value},
                "Boundary derived from the registered input range."))
    for output in result.outputs:
        text = json.dumps(output.formula, sort_keys=True, default=str)
        if '"op": "Divide"' in text:
            candidates.append(TestCaseCandidate("test-candidate:" + _digest([output.output_id, "near-zero"])[:16],
                "DENOMINATOR_NEAR_ZERO", {}, "Exercise sensitivity near a denominator zero; a concrete range is required."))
        if any(token in text for token in ('"FiniteSum"', '"FoldLeft"', '"Map"')):
            for size in (0, 1): candidates.append(TestCaseCandidate(
                "test-candidate:" + _digest([output.output_id, size])[:16],
                "EMPTY_INPUT" if size == 0 else "SINGLE_ELEMENT_INPUT", {"length": size},
                "Exercise zero/one-iteration behavior."))
    return candidates


@dataclass(frozen=True)
class SensitivityFinding:
    source: str
    level: str
    verified_bound: Any | None
    reason: str


def sensitivity_report(result: Any) -> list[SensitivityFinding]:
    findings = []
    for output in result.outputs:
        for component in output.error_components or []:
            bound = component.get("bound") or {}
            symmetric = bound.get("symmetric_bound")
            magnitude = symmetric.get("value") if isinstance(symmetric, dict) else symmetric
            level = "HIGH" if isinstance(magnitude, (int, float)) and abs(magnitude) > 1 else "MEDIUM" if magnitude is not None else "UNRESOLVED"
            findings.append(SensitivityFinding(str(component.get("source", output.name)), level, magnitude,
                "Ranking uses only a verified/recorded error bound; no percentage contribution is inferred."))
        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("op") == "Divide": findings.append(SensitivityFinding(output.name, "HIGH", None,
                    "Division may amplify error; denominator range is required for a numeric bound."))
                for value in node.values(): visit(value)
            elif isinstance(node, list):
                for value in node: visit(value)
        visit(output.formula)
    unique = {(item.source, item.level, str(item.verified_bound), item.reason): item for item in findings}
    return list(unique.values())


def _reference_augment_project_provenance(result: Any, *, entry_source: str | Path | None = None,
                               project_root: str | Path | None = None,
                               input_artifacts: Iterable[InputArtifact | str | Path] = (),
                               configuration: Iterable[ConfigurationParameter] = (),
                               profile: AuditProfile | str = AuditProfile.RESEARCH) -> Any:
    inputs = [item if isinstance(item, InputArtifact) else InputArtifact.inspect(item) for item in input_artifacts]
    traces = resolve_configuration(configuration)
    environment = capture_environment(result.project_graph.external_modules)
    root = Path(project_root or entry_source or ".").resolve()
    if root.is_file(): root = root.parent
    git = capture_git_provenance(root)
    dependencies = [DependencyProvenance(name, environment.libraries.get(name, "UNVERIFIED"),
        str(result.provenance.get("library_contract_registry_hash")), "PUBLIC_REFERENCE_REGISTRY")
        for name in sorted(set(result.project_graph.external_modules))]
    lineage = build_data_lineage(result, inputs)
    graph = ResearchProvenanceGraph()
    source_nodes = {}
    for module in result.modules:
        source_nodes[module.name] = graph.add_node(ProvenanceNodeKind.SOURCE, module.name,
            metadata={"path": module.path, "language": module.language}, content_hash=module.source_hash,
            evidence_level="SOURCE_HASH")
    env_node = graph.add_node(ProvenanceNodeKind.ENVIRONMENT, "environment", metadata=_serial(environment),
                              evidence_level=environment.evidence_level, proof_authority=False)
    config_node = graph.add_node(ProvenanceNodeKind.CONFIGURATION, "resolved configuration",
                                 metadata={"parameter_count": len(traces)}, content_hash=_digest(traces))
    for trace in traces:
        parameter = graph.add_node(ProvenanceNodeKind.PARAMETER, trace.name, metadata=_serial(trace),
                                   content_hash=_digest(trace))
        graph.add_edge(ProvenanceEdgeKind.DERIVED_FROM, parameter, config_node)
        for source in source_nodes.values(): graph.add_edge(ProvenanceEdgeKind.CONFIGURES, parameter, source)
    input_nodes = {item.artifact_id: graph.add_node(ProvenanceNodeKind.INPUT_ARTIFACT, item.location,
        metadata=_serial(item), content_hash=item.content_hash, evidence_level="INPUT_METADATA") for item in inputs}
    for item in inputs:
        if item.schema:
            for field_schema in item.schema.fields:
                field_node = graph.add_node(ProvenanceNodeKind.INPUT_FIELD,
                    item.location + "::" + field_schema.name, metadata=_serial(field_schema),
                    content_hash=_digest(field_schema), evidence_level="SCHEMA_OBSERVATION")
                graph.add_edge(ProvenanceEdgeKind.DERIVED_FROM, field_node, input_nodes[item.artifact_id])
    dependency_nodes = {item.name: graph.add_node(ProvenanceNodeKind.DEPENDENCY, item.name,
        metadata=_serial(item), content_hash=_digest(item), evidence_level="REFERENCE_CONTRACT") for item in dependencies}
    for output in result.outputs:
        origins = _output_origins(output)
        implementation = graph.add_node(ProvenanceNodeKind.IMPLEMENTATION_IR, output.output_id + ":implementation",
            metadata={"output": output.name}, content_hash=_digest(output.implementation), evidence_level="INDEPENDENT_EXTRACTION",
            origin_set=origins)
        mathematical = graph.add_node(ProvenanceNodeKind.MATHEMATICAL_IR, output.output_id + ":mathematics",
            metadata={"output": output.name}, content_hash=_digest(output.formula), evidence_level="INDEPENDENT_EXTRACTION",
            origin_set=origins)
        graph.add_edge(ProvenanceEdgeKind.DERIVED_FROM, mathematical, implementation)
        algorithm = graph.add_node(ProvenanceNodeKind.ALGORITHM_IR, output.output_id + ":algorithm",
            metadata={"operator": (output.formula or {}).get("op", "UNRESOLVED")},
            content_hash=_digest([(output.formula or {}).get("op"), output.dependencies]),
            evidence_level="SEMANTIC_CLASSIFICATION", origin_set=origins)
        graph.add_edge(ProvenanceEdgeKind.DERIVED_FROM, algorithm, implementation)
        for source in source_nodes.values(): graph.add_edge(ProvenanceEdgeKind.DERIVED_FROM, implementation, source)
        for source in input_nodes.values(): graph.add_edge(ProvenanceEdgeKind.READS, implementation, source)
        for source in dependency_nodes.values(): graph.add_edge(ProvenanceEdgeKind.DEPENDS_ON, implementation, source)
        for proof in [item for item in result.proofs if item.get("output_id") == output.output_id]:
            claim = graph.add_node(ProvenanceNodeKind.VERIFICATION_CLAIM, output.output_id + ":claim",
                metadata=proof, content_hash=_digest(proof), evidence_level=str(proof.get("lean_status")),
                proof_authority=proof.get("lean_status") == "LEAN_KERNEL_VERIFIED")
            graph.add_edge(ProvenanceEdgeKind.VERIFIES, claim, mathematical)
        for artifact in result.artifacts:
            if artifact.payload_symbol == output.name or artifact.dataset_variable == output.name:
                target = graph.add_node(ProvenanceNodeKind.OUTPUT_ARTIFACT, artifact.sink_id,
                    metadata={"format": artifact.format, "path_expression": artifact.path_expression,
                              "serialization_status": artifact.serialization_boundary.status},
                    evidence_level="SERIALIZATION_EVIDENCE", origin_set=[artifact.source_span])
                graph.add_edge(ProvenanceEdgeKind.SERIALIZES, mathematical, target,
                               {"mathematical_correctness_separate": True})
        trace = (output.residual or {}).get("transformation_trace") if isinstance(output.residual, dict) else None
        if trace:
            transformation = graph.add_node(ProvenanceNodeKind.TRANSFORMATION,
                output.output_id + ":transformation", metadata={"trace": trace}, content_hash=_digest(trace),
                evidence_level="REWRITE_TRACE", origin_set=origins)
            graph.add_edge(ProvenanceEdgeKind.TRANSFORMS, implementation, transformation)
            graph.add_edge(ProvenanceEdgeKind.DERIVED_FROM, mathematical, transformation)
    graph.diagnostics.extend({"code": item} for item in graph.validate())
    output_schemas = []
    for artifact in result.artifacts:
        fields = tuple(FieldSchema(item.name, item.dtype, dimensions=tuple(item.dimensions))
                       for item in artifact.dataset_outputs)
        if artifact.dataset_variable and not fields:
            fields = (FieldSchema(artifact.dataset_variable, artifact.dtype,
                                  dimensions=tuple(artifact.dimensions)),)
        output_schemas.append(_serial(DatasetSchema(artifact.format, fields,
            tuple(artifact.dimensions), artifact.format, "output-schema:" + artifact.sink_id)))
    result.provenance.update({"research_provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "research_provenance_graph": graph.to_dict(), "input_artifacts": [_serial(item) for item in inputs],
        "configuration_resolution": [_serial(item) for item in traces], "environment": _serial(environment),
        "git": _serial(git), "dependency_provenance": [_serial(item) for item in dependencies],
        "data_lineage": lineage.to_dict(), "output_schemas": output_schemas,
        "audit_profile": profile_acceptance(result.status, profile),
        "cache_key": _serial(build_cache_key(result)), "cache_key_digest": build_cache_key(result).digest})
    return result


def augment_project_provenance(result: Any, *, entry_source: str | Path | None = None,
                               project_root: str | Path | None = None,
                               input_artifacts: Iterable[InputArtifact | str | Path] = (),
                               configuration: Iterable[ConfigurationParameter] = (),
                               profile: AuditProfile | str = AuditProfile.RESEARCH) -> Any:
    """Capture frontend facts, then delegate canonical graph/lineage assembly to Rust."""
    inputs = [item if isinstance(item, InputArtifact) else InputArtifact.inspect(item)
              for item in input_artifacts]
    parameters = list(configuration)
    traces = resolve_configuration(parameters)
    environment = capture_environment(result.project_graph.external_modules)
    root = Path(project_root or entry_source or ".").resolve()
    if root.is_file(): root = root.parent
    git = capture_git_provenance(root)
    dependencies = [DependencyProvenance(name, environment.libraries.get(name, "UNVERIFIED"),
        str(result.provenance.get("library_contract_registry_hash")), "PUBLIC_REFERENCE_REGISTRY")
        for name in sorted(set(result.project_graph.external_modules))]
    native = _execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "ASSEMBLE_PROVENANCE", "project": result.to_dict(),
        "input_artifacts": [_serial(item) for item in inputs],
        "configuration_resolution": [_serial(item) for item in traces],
        "environment": _serial(environment), "git": _serial(git),
        "dependencies": [_serial(item) for item in dependencies]})["result"]
    result.provenance.update({"research_provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "research_provenance_graph": native["graph"],
        "input_artifacts": [_serial(item) for item in inputs],
        "configuration_resolution": [_serial(item) for item in traces],
        "environment": _serial(environment), "git": _serial(git),
        "dependency_provenance": [_serial(item) for item in dependencies],
        "data_lineage": native["data_lineage"],
        "audit_profile": profile_acceptance(result.status, profile),
        "cache_key": _serial(build_cache_key(result)),
        "cache_key_digest": build_cache_key(result).digest})
    return result


def temporary_reproducer_directory() -> tempfile.TemporaryDirectory[str]:
    """Public safety helper: generated reproducers live outside the research project."""
    return tempfile.TemporaryDirectory(prefix="formulatracer-reproducer-")
