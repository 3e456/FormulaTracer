"""Reference-first semantic contracts for scientific Python libraries.

Registry files describe public API meaning, not implementation algorithms.  A
contract is usable only when its version selector matches (or when the audited
version is unknown, which is recorded explicitly).  Inventory-derived entries
are candidates and are never returned as verified contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
import fnmatch
import json
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from .core import AuditError


class SemanticFamily(str, Enum):
    REDUCTION = "Reduction"
    ELEMENTWISE_FUNCTION = "ElementwiseFunction"
    ELEMENTWISE_PREDICATE = "ElementwisePredicate"
    SHAPE_TRANSFORM = "ShapeTransform"
    REPRESENTATION_MAPPING = "RepresentationMapping"
    NUMERIC_CAST = "NumericCast"
    INDEX_SELECTION = "IndexSelection"
    AXIS_MAPPING = "AxisMapping"
    TENSOR_CONTRACTION = "TensorContraction"
    CONDITIONAL_SELECTION = "ConditionalSelection"
    STATISTICS = "Statistics"
    INTERPOLATION = "Interpolation"
    LINEAR_ALGEBRA_RELATION = "LinearAlgebraRelation"
    GRAPH_ALGORITHM = "GraphAlgorithm"
    SPATIAL_GEOMETRY = "SpatialGeometry"
    RANDOM_SAMPLE = "RandomSample"
    DISTRIBUTION = "Distribution"
    ALGORITHM_INVOCATION = "AlgorithmInvocation"
    PARALLEL_EXECUTION = "ParallelExecution"
    TABLE_MAPPING = "TableMapping"
    GROUPING = "Grouping"
    AGGREGATION = "Aggregation"
    ALIGNMENT = "Alignment"


class ReferenceStatus(str, Enum):
    REFERENCE_EXTRACTED = "REFERENCE_EXTRACTED"
    REFERENCE_REVIEWED = "REFERENCE_REVIEWED"
    REFERENCE_TEST_VALIDATED = "REFERENCE_TEST_VALIDATED"
    LEAN_VERIFIED_MAPPING = "LEAN_VERIFIED_MAPPING"


class TypeEvidence(str, Enum):
    REFERENCE_DETERMINED = "REFERENCE_DETERMINED"
    INPUT_TYPE_DETERMINED = "INPUT_TYPE_DETERMINED"
    STATICALLY_CONSTRAINED = "STATICALLY_CONSTRAINED"
    ANNOTATION_DETERMINED = "ANNOTATION_DETERMINED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


RESOLUTION_PRIORITY = {
    "REFERENCE_SIMPLE_MAPPING": 1,
    "REFERENCE_DETAILED_CONTRACT": 2,
    "REGISTERED_CONTRACT": 3,
}


@dataclass(frozen=True)
class ReferenceProvenance:
    package: str
    version_range: str
    qualified_callable: str
    official_reference: str
    reference_status: str
    verified_date: str


@dataclass(frozen=True)
class ContractBinding:
    package: str
    version_range: str
    callable: str
    family: str
    bind: dict[str, Any]
    equivalence_scope: dict[str, list[str]]
    provenance: ReferenceProvenance
    return_type: dict[str, Any] | None = None
    resolution_kind: str = "REFERENCE_SIMPLE_MAPPING"
    execution: dict[str, Any] | None = None
    version_check: str = "VERSION_UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateBinding:
    package: str
    version: str | None
    callable: str
    family: str
    bind: dict[str, Any]
    status: str = "NEEDS_REVIEW"
    source_classification: str = "NEEDS_CONTRACT"
    call_count: int = 0
    usage_file_count: int = 0


@dataclass(frozen=True)
class ReferenceHarvestResolution:
    """Resolution attached to a harvested public API without promoting it.

    Reviewed registry contracts always win.  Reference-derived mappings remain
    candidates until a human-reviewed registry entry exists.
    """

    callable: str
    resolution_kind: str
    family: str | None
    status: str
    priority: int


@dataclass(frozen=True)
class ValueTypeInfo:
    """Python-side type metadata used only for contract resolution, never Lean."""

    kinds: tuple[str, ...]
    evidence: str
    container: str | None = None
    dimensions: tuple[str, ...] = ()
    labels: bool | None = None
    dtype_class: str | None = None
    lazy: bool | None = None
    backend: str | None = None
    source: str | None = None

    @property
    def determined(self) -> bool:
        return len(self.kinds) == 1 and self.evidence not in {
            TypeEvidence.AMBIGUOUS.value, TypeEvidence.UNKNOWN.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def version_matches(version: str | None, selector: str) -> bool:
    """Match exact/wildcard versions and small comma-separated comparison ranges."""
    if version is None:
        return True
    selector = selector.strip()
    if selector in {"", "*"}:
        return True
    actual = _version_tuple(version)
    if any(selector.startswith(op) for op in (">", "<", "=")) or "," in selector:
        for condition in (item.strip() for item in selector.split(",") if item.strip()):
            operator = next((op for op in (">=", "<=", "==", ">", "<") if condition.startswith(op)), None)
            if operator is None:
                return False
            wanted = _version_tuple(condition[len(operator):])
            if not wanted:
                return False
            width = max(len(actual), len(wanted))
            left, right = actual + (0,) * (width - len(actual)), wanted + (0,) * (width - len(wanted))
            if not {">=": left >= right, "<=": left <= right, "==": left == right,
                    ">": left > right, "<": left < right}[operator]:
                return False
        return True
    return fnmatch.fnmatchcase(version, selector)


def _expand_simple_bindings(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    aliases = {
        "reduction": SemanticFamily.REDUCTION.value,
        "unary": SemanticFamily.ELEMENTWISE_FUNCTION.value,
        "predicate": SemanticFamily.ELEMENTWISE_PREDICATE.value,
        "shape": SemanticFamily.SHAPE_TRANSFORM.value,
        "representation": SemanticFamily.REPRESENTATION_MAPPING.value,
        "cast": SemanticFamily.NUMERIC_CAST.value,
        "selection": SemanticFamily.INDEX_SELECTION.value,
        "axis": SemanticFamily.AXIS_MAPPING.value,
        "contraction": SemanticFamily.TENSOR_CONTRACTION.value,
        "conditional": SemanticFamily.CONDITIONAL_SELECTION.value,
        "statistics": SemanticFamily.STATISTICS.value,
        "interpolation": SemanticFamily.INTERPOLATION.value,
        "linear_algebra": SemanticFamily.LINEAR_ALGEBRA_RELATION.value,
        "graph": SemanticFamily.GRAPH_ALGORITHM.value,
        "spatial": SemanticFamily.SPATIAL_GEOMETRY.value,
        "random": SemanticFamily.RANDOM_SAMPLE.value,
        "algorithm": SemanticFamily.ALGORITHM_INVOCATION.value,
        "parallel": SemanticFamily.PARALLEL_EXECUTION.value,
        "table": SemanticFamily.TABLE_MAPPING.value,
        "grouping": SemanticFamily.GROUPING.value,
        "aggregation": SemanticFamily.AGGREGATION.value,
        "alignment": SemanticFamily.ALIGNMENT.value,
    }
    bind_keys = {
        "reduction": "reducer", "unary": "function", "predicate": "predicate",
        "shape": "transform", "representation": "mapping", "cast": "cast",
        "selection": "selection", "axis": "mapping", "contraction": "contraction",
        "conditional": "selection", "statistics": "statistic", "interpolation": "method",
        "linear_algebra": "relation", "graph": "algorithm", "spatial": "relation",
        "random": "distribution", "algorithm": "algorithm", "parallel": "operation",
        "table": "mapping", "grouping": "grouping", "aggregation": "aggregation",
        "alignment": "alignment",
    }
    for short_family, groups in (data.get("simple_bindings") or {}).items():
        if short_family not in aliases:
            raise AuditError(f"LIBRARY_CONTRACT_UNKNOWN_FAMILY: {short_family}")
        for semantic, callables in groups.items():
            for callable_name in callables:
                yield {"callable": callable_name, "family": aliases[short_family],
                       "bind": {bind_keys[short_family]: semantic}}


class LibraryContractRegistry:
    TYPE_BASES = {"geopandas.GeoDataFrame": "pandas.DataFrame",
                  "geopandas.GeoSeries": "pandas.Series"}
    TYPE_PRESERVING_FAMILIES = {
        SemanticFamily.SHAPE_TRANSFORM.value, SemanticFamily.REPRESENTATION_MAPPING.value,
        SemanticFamily.NUMERIC_CAST.value, SemanticFamily.INDEX_SELECTION.value,
        SemanticFamily.CONDITIONAL_SELECTION.value, SemanticFamily.TABLE_MAPPING.value,
        SemanticFamily.ALIGNMENT.value, SemanticFamily.ELEMENTWISE_FUNCTION.value,
        SemanticFamily.ELEMENTWISE_PREDICATE.value,
    }
    RECEIVER_RETURN_FAMILIES = {
        SemanticFamily.SHAPE_TRANSFORM.value, SemanticFamily.NUMERIC_CAST.value,
        SemanticFamily.INDEX_SELECTION.value, SemanticFamily.CONDITIONAL_SELECTION.value,
        SemanticFamily.TABLE_MAPPING.value, SemanticFamily.ELEMENTWISE_FUNCTION.value,
        SemanticFamily.ELEMENTWISE_PREDICATE.value,
    }
    def __init__(self, roots: str | Path | Iterable[str | Path]):
        values = [roots] if isinstance(roots, (str, Path)) else list(roots)
        self.roots = [Path(value) for value in values]
        self.bindings: dict[str, list[ContractBinding]] = {}
        self._load()

    @classmethod
    def default(cls) -> "LibraryContractRegistry":
        return cls(Path(__file__).resolve().parents[2] / "registry" / "libraries")

    @classmethod
    def coverage_expansion(cls) -> "LibraryContractRegistry":
        """Reviewed registry plus opt-in reference coverage candidates.

        Keeping the overlay explicit preserves the historical verified-registry
        cardinality and prevents harvested/reference-only entries from silently
        becoming verified contracts.
        """
        root = Path(__file__).resolve().parents[2] / "registry"
        return cls([root / "libraries", root / "library_coverage"])

    def _load(self) -> None:
        for root in self.roots:
            if not root.exists():
                continue
            paths = [root] if root.is_file() else sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
            for path in paths:
                self._load_file(path)

    def _load_file(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("package"), str):
            raise AuditError(f"LIBRARY_CONTRACT_INVALID: {path}")
        package, version_range = data["package"], str(data.get("version", "*"))
        defaults = data.get("equivalence_scope") or {"preserve": ["mathematical_relation"],
                                                       "ignore": ["implementation_algorithm"]}
        references = data.get("references") or {}
        entries = [*(data.get("bindings") or []), *_expand_simple_bindings(data)]
        for raw in entries:
            callable_name = raw.get("callable")
            family = raw.get("family")
            if not callable_name or family not in {item.value for item in SemanticFamily}:
                raise AuditError(f"LIBRARY_CONTRACT_INVALID_BINDING: {path}: {callable_name}")
            reference = raw.get("reference") or references.get(callable_name) or data.get("reference")
            if not reference and data.get("reference_template"):
                reference = str(data["reference_template"]).format(callable=callable_name)
            if not reference:
                raise AuditError(f"LIBRARY_CONTRACT_REFERENCE_REQUIRED: {callable_name}")
            status = str(raw.get("reference_status", data.get("reference_status", "REFERENCE_EXTRACTED")))
            if status not in {item.value for item in ReferenceStatus}:
                raise AuditError(f"LIBRARY_CONTRACT_REFERENCE_STATUS_INVALID: {callable_name}")
            verified = str(raw.get("verified_date", data.get("verified_date", "")))
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified):
                raise AuditError(f"LIBRARY_CONTRACT_VERIFIED_DATE_REQUIRED: {callable_name}")
            resolution_kind = str(raw.get("resolution_kind", data.get("resolution_kind", "REFERENCE_SIMPLE_MAPPING")))
            if resolution_kind not in RESOLUTION_PRIORITY:
                raise AuditError(f"LIBRARY_CONTRACT_RESOLUTION_KIND_INVALID: {callable_name}")
            provenance = ReferenceProvenance(package, version_range, callable_name, str(reference), status, verified)
            bind = dict(raw.get("bind") or {})
            return_type = raw.get("return_type")
            if return_type is None and bind.get("result_type"):
                return_type = {"kind": bind["result_type"],
                               "evidence": TypeEvidence.REFERENCE_DETERMINED.value}
            owner = callable_name.rsplit(".", 1)[0]
            if (return_type is None and family in self.RECEIVER_RETURN_FAMILIES
                    and owner.count(".") >= 1):
                return_type = {"kind": "receiver", "evidence": TypeEvidence.REFERENCE_DETERMINED.value}
            if return_type is not None:
                if not isinstance(return_type, dict):
                    raise AuditError(f"LIBRARY_CONTRACT_RETURN_TYPE_INVALID: {callable_name}")
                evidence = str(return_type.get("evidence", TypeEvidence.REFERENCE_DETERMINED.value))
                if evidence not in {item.value for item in TypeEvidence}:
                    raise AuditError(f"LIBRARY_CONTRACT_TYPE_EVIDENCE_INVALID: {callable_name}")
                return_type = {**return_type, "evidence": evidence}
            binding = ContractBinding(
                package=package, version_range=version_range, callable=callable_name, family=family,
                bind=bind, equivalence_scope=dict(raw.get("equivalence_scope") or defaults),
                provenance=provenance, return_type=return_type, resolution_kind=resolution_kind,
                execution=raw.get("execution"),
            )
            self.bindings.setdefault(callable_name, []).append(binding)
        for values in self.bindings.values():
            values.sort(key=lambda item: RESOLUTION_PRIORITY[item.resolution_kind])

    def resolve(self, callable_name: str, version: str | None = None) -> ContractBinding | None:
        for binding in self.bindings.get(callable_name, []):
            if version_matches(version, binding.version_range):
                return ContractBinding(**{**binding.__dict__,
                    "version_check": "VERSION_MATCHED" if version is not None else "VERSION_UNKNOWN"})
        return None

    def known_callable(self, callable_name: str) -> bool:
        return callable_name in self.bindings

    def registered_callables(self) -> set[str]:
        return set(self.bindings)

    @staticmethod
    def _type_info(kinds: Iterable[str], evidence: str, context: dict[str, Any] | None = None) -> ValueTypeInfo:
        context = context or {}
        return ValueTypeInfo(
            tuple(dict.fromkeys(str(kind) for kind in kinds if kind)), evidence,
            container=context.get("container"), dimensions=tuple(context.get("dimensions") or ()),
            labels=context.get("labels"), dtype_class=context.get("dtype_class"),
            lazy=context.get("lazy"), backend=context.get("backend"), source=context.get("source"),
        )

    def _return_type(self, binding: ContractBinding, receiver: ValueTypeInfo | None,
                     input_types: list[str], context: dict[str, Any]) -> ValueTypeInfo:
        contract = binding.return_type
        if contract:
            kind = contract.get("kind")
            if kind == "conditional":
                matches = []
                for case in contract.get("cases", []):
                    wanted = str((case.get("when") or {}).get("input_type", ""))
                    if input_types and wanted in input_types:
                        matches.append(str(case.get("returns", "")))
                if matches:
                    evidence = (TypeEvidence.INPUT_TYPE_DETERMINED.value if len(set(matches)) == 1
                                else TypeEvidence.AMBIGUOUS.value)
                    return self._type_info(matches, evidence, context)
                possible = [str(case.get("returns", "")) for case in contract.get("cases", [])]
                return self._type_info(possible, TypeEvidence.AMBIGUOUS.value, context)
            if kind == "receiver" and receiver:
                return self._type_info(receiver.kinds, receiver.evidence, {**receiver.to_dict(), **context})
            if kind:
                return self._type_info([str(kind)], str(contract.get("evidence")), context)
        if receiver and binding.family in self.TYPE_PRESERVING_FAMILIES:
            return self._type_info(receiver.kinds, receiver.evidence, {**receiver.to_dict(), **context})
        return self._type_info([], TypeEvidence.UNKNOWN.value, context)

    def resolve_chain(self, callable_name: str, versions: dict[str, str] | None = None,
                      type_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Decompose flattened chains while propagating evidence-backed receiver types."""
        versions = versions or {}
        type_context = dict(type_context or {})
        normalized = callable_name.replace("rasterio.features.features.", "rasterio.features.")
        mechanisms = list(type_context.get("mechanisms") or [])

        def resolved(name: str) -> ContractBinding | None:
            return self.resolve(name, versions.get(name.split(".", 1)[0]))

        parts = normalized.split(".")
        operations: list[dict[str, Any]] = []
        input_types = [str(item) for item in type_context.get("input_types", [])]
        root_type = type_context.get("receiver_type") or type_context.get("root_type")
        if root_type:
            consumed = int(type_context.get("namespace_segments", 2))
            current = self._type_info([str(root_type)], str(type_context.get(
                "evidence", TypeEvidence.INPUT_TYPE_DETERMINED.value)), type_context)
            if "NAMESPACE_CORRECTION" not in mechanisms and ".".join(parts[:consumed]) != str(root_type):
                mechanisms.append("NAMESPACE_CORRECTION")
        else:
            direct = resolved(normalized)
            if direct:
                current = self._return_type(direct, None, input_types, type_context)
                direct_mechanisms = ["RETURN_TYPE_PROPAGATION"] if current.kinds else []
                if direct.bind.get("property"):
                    direct_mechanisms.append("PROPERTY_PROPAGATION")
                return {"status": "SUPPORTED", "callable": callable_name,
                        "operations": [direct.to_dict()], "unresolved_segments": [],
                        "type_info": current.to_dict(), "mechanisms": direct_mechanisms}
            first: ContractBinding | None = None
            consumed = 0
            for index in range(len(parts) - 1, 0, -1):
                candidate = resolved(".".join(parts[:index]))
                if candidate:
                    first, consumed = candidate, index
                    break
            if first is None:
                return {"status": "NEEDS_CONTRACT", "callable": callable_name, "operations": [],
                        "unresolved_segments": parts, "reason": "UNKNOWN_RECEIVER_TYPE",
                        "type_info": self._type_info([], TypeEvidence.UNKNOWN.value, type_context).to_dict(),
                        "mechanisms": mechanisms}
            operations.append(first.to_dict())
            if first.bind.get("property"):
                mechanisms.append("PROPERTY_PROPAGATION")
            owner = first.callable.rsplit(".", 1)[0]
            receiver = (self._type_info([owner], TypeEvidence.REFERENCE_DETERMINED.value, type_context)
                        if first.family in self.TYPE_PRESERVING_FAMILIES and owner.count(".") >= 1 else None)
            current = self._return_type(first, receiver, input_types, type_context)
            if current.kinds:
                mechanisms.append("RETURN_TYPE_PROPAGATION")

        if type_context.get("result_type"):
            current = self._type_info([str(type_context["result_type"])], str(type_context.get(
                "evidence", TypeEvidence.INPUT_TYPE_DETERMINED.value)), type_context)
            if "RETURN_TYPE_PROPAGATION" not in mechanisms:
                mechanisms.append("RETURN_TYPE_PROPAGATION")

        for offset, segment in enumerate(parts[consumed:], start=consumed):
            if not current.kinds:
                return {"status": "NEEDS_CONTRACT", "callable": callable_name, "operations": operations,
                        "unresolved_segments": parts[offset:], "reason": "UNKNOWN_RECEIVER_TYPE",
                        "type_info": current.to_dict(), "mechanisms": mechanisms}
            if len(current.kinds) > 1 and current.evidence == TypeEvidence.AMBIGUOUS.value:
                return {"status": "NEEDS_CONTRACT", "callable": callable_name, "operations": operations,
                        "unresolved_segments": parts[offset:], "reason": "AMBIGUOUS_RECEIVER_TYPE",
                        "type_info": current.to_dict(), "mechanisms": mechanisms}
            alternatives: list[tuple[str, ContractBinding]] = []
            for kind in current.kinds:
                binding = resolved(f"{kind}.{segment}")
                if binding is None:
                    base = self.TYPE_BASES.get(kind)
                    binding = resolved(f"{base}.{segment}") if base else None
                if binding:
                    alternatives.append((kind, binding))
            if not alternatives:
                reason = ("AMBIGUOUS_RECEIVER_TYPE" if len(current.kinds) > 1
                          else f"UNREGISTERED_CHAIN_OPERATION:{segment}")
                return {"status": "NEEDS_CONTRACT", "callable": callable_name, "operations": operations,
                        "unresolved_segments": parts[offset:], "reason": reason,
                        "type_info": current.to_dict(), "mechanisms": mechanisms}
            if len(alternatives) != len(current.kinds):
                current = self._type_info([kind for kind, _ in alternatives],
                                          TypeEvidence.STATICALLY_CONSTRAINED.value, type_context)
                mechanisms.append("RECEIVER_TYPE_CONSTRAINT")
            semantic_shapes = {(item.family, json.dumps(item.bind, sort_keys=True)) for _, item in alternatives}
            if len(alternatives) > 1 and len(semantic_shapes) > 1:
                return {"status": "NEEDS_CONTRACT", "callable": callable_name, "operations": operations,
                        "unresolved_segments": parts[offset:], "reason": "AMBIGUOUS_RECEIVER_TYPE",
                        "type_info": current.to_dict(), "mechanisms": mechanisms}
            binding = alternatives[0][1]
            operations.append(binding.to_dict())
            mechanisms.append("RECEIVER_PROPAGATION")
            if binding.bind.get("property"):
                mechanisms.append("PROPERTY_PROPAGATION")
            current = self._return_type(binding, current, input_types, type_context)
        return {"status": "SUPPORTED", "callable": callable_name, "operations": operations,
                "unresolved_segments": [], "type_info": current.to_dict(),
                "mechanisms": list(dict.fromkeys(mechanisms))}


def infer_candidate_family(callable_name: str) -> tuple[str, dict[str, Any]]:
    short = callable_name.rsplit(".", 1)[-1].lower()
    if short in {"sum", "prod", "mean", "min", "max", "std", "var", "any", "all"}:
        return SemanticFamily.REDUCTION.value, {"reducer": short}
    if short in {"reshape", "ravel", "flatten", "squeeze", "expand_dims", "transpose", "stack", "concatenate"}:
        return SemanticFamily.SHAPE_TRANSFORM.value, {"transform": short}
    if short in {"astype", "asarray", "array"}:
        return SemanticFamily.REPRESENTATION_MAPPING.value, {"mapping": short}
    if short in {"isfinite", "isnan", "isinf"}:
        return SemanticFamily.ELEMENTWISE_PREDICATE.value, {"predicate": short}
    if short in {"sin", "cos", "tan", "exp", "log", "sqrt", "abs", "floor", "ceil", "round"}:
        return SemanticFamily.ELEMENTWISE_FUNCTION.value, {"function": short}
    if short in {"query", "query_ball_point", "query_ball_tree"}:
        return SemanticFamily.GRAPH_ALGORITHM.value, {"algorithm": "nearest_neighbor_query"}
    if short in {"uniform", "normal", "integers", "choice", "permutation"}:
        return SemanticFamily.RANDOM_SAMPLE.value, {"distribution": short}
    if short in {"groupby"}:
        return SemanticFamily.GROUPING.value, {"grouping": short}
    if short in {"merge", "join", "concat", "align", "reindex"}:
        return SemanticFamily.ALIGNMENT.value, {"alignment": short}
    if short in {"fillna", "dropna", "reset_index", "set_index", "pivot_table"}:
        return SemanticFamily.TABLE_MAPPING.value, {"mapping": short}
    return SemanticFamily.ALGORITHM_INVOCATION.value, {"algorithm": short}


def inventory_non_numeric_reason(callable_name: str) -> str | None:
    """Conservative corrections for flattened metadata, plotting, string, and output-I/O chains."""
    patterns = {
        ".attrs.": "METADATA_MAPPING_NOT_NUMERIC",
        ".sizes.": "SHAPE_METADATA_ACCESS_NOT_NUMERIC",
        ".data_vars.": "DATASET_METADATA_ACCESS_NOT_NUMERIC",
        ".hvplot": "VISUALIZATION_NOT_NUMERIC",
        ".to_sql": "OUTPUT_IO_NOT_NUMERIC",
        ".str.": "STRING_OPERATION_NOT_NUMERIC",
    }
    for pattern, reason in patterns.items():
        if pattern in callable_name:
            return reason
    if callable_name in {"numpy.savez_compressed", "numpy.ndarray.decode", "numpy.ndarray.rstrip",
                         "numpy.issubclass_", "dask.array.attrs.items"}:
        return "IO_STRING_OR_TYPE_METADATA_NOT_NUMERIC"
    return None


def _inventory_type_evidence_document(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else Path(__file__).resolve().parents[2] / "registry" / "inventory_type_evidence.yaml"
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_inventory_type_evidence(path: str | Path | None = None) -> list[dict[str, Any]]:
    data = _inventory_type_evidence_document(path)
    rules = data.get("rules") or []
    if not isinstance(rules, list):
        raise AuditError(f"INVENTORY_TYPE_EVIDENCE_INVALID: {path}")
    allowed = {item.value for item in TypeEvidence}
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("callable") or rule.get("evidence") not in allowed:
            raise AuditError(f"INVENTORY_TYPE_EVIDENCE_INVALID: {path}")
    return rules


def inventory_type_context(callable_name: str, rules: Iterable[dict[str, Any]]) -> dict[str, Any]:
    matches = [rule for rule in rules if fnmatch.fnmatchcase(callable_name, str(rule["callable"]))]
    if not matches:
        return {}
    matches.sort(key=lambda rule: ("*" in str(rule["callable"]), -len(str(rule["callable"]))))
    rule = matches[0]
    return {key: value for key, value in rule.items() if key != "callable"}


def generate_inventory_candidates(inventory: str | Path, registry: LibraryContractRegistry | None = None,
                                  classifications: tuple[str, ...] = ("NEEDS_CONTRACT", "NATIVE_SOURCE_AVAILABLE",
                                                                      "OPAQUE_NATIVE"),
                                  type_evidence: str | Path | None = None) -> dict[str, Any]:
    data = json.loads(Path(inventory).read_text(encoding="utf-8"))
    registry = registry or LibraryContractRegistry.default()
    versions = {str(item.get("package")): str(item.get("version")) for item in data.get("packages", [])
                if item.get("package") and item.get("version")}
    evidence_rules = load_inventory_type_evidence(type_evidence)
    candidates: list[dict[str, Any]] = []
    for row in data.get("apis", []):
        if not row.get("numeric") or row.get("package") == "internal":
            continue
        callable_name = str(row.get("qualified_callable", ""))
        if row.get("numeric_classification") not in classifications:
            continue
        chain = registry.resolve_chain(callable_name, versions,
                                       inventory_type_context(callable_name, evidence_rules))
        if chain["status"] == "SUPPORTED":
            continue
        if inventory_non_numeric_reason(callable_name):
            continue
        family, bind = infer_candidate_family(callable_name)
        candidate = asdict(CandidateBinding(str(row.get("package")), row.get("version"), callable_name,
                                            family, bind, source_classification=str(row.get("numeric_classification")),
                                            call_count=int(row.get("call_count", 0)),
                                            usage_file_count=int(row.get("usage_file_count", 0))))
        candidate["resolved_operations"] = chain["operations"]
        candidate["unresolved_segments"] = chain["unresolved_segments"]
        candidate["reason"] = chain.get("reason", "REFERENCE_REVIEW_REQUIRED")
        candidate["type_info"] = chain.get("type_info")
        candidate["resolution_mechanisms"] = chain.get("mechanisms", [])
        candidates.append(candidate)
    candidates.sort(key=lambda item: (-item["call_count"], -item["usage_file_count"], item["callable"]))
    return {"schema_version": "0.1", "generated_date": date.today().isoformat(),
            "status": "NEEDS_REVIEW", "source_inventory": str(Path(inventory)),
            "candidates": candidates}


def write_inventory_candidates(inventory: str | Path, output: str | Path,
                               registry: LibraryContractRegistry | None = None,
                               type_evidence: str | Path | None = None) -> dict[str, Any]:
    payload = generate_inventory_candidates(inventory, registry, type_evidence=type_evidence)
    Path(output).write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return payload


def analyze_inventory_coverage(inventory: str | Path,
                               registry: LibraryContractRegistry | None = None,
                               type_evidence: str | Path | None = None) -> dict[str, Any]:
    data = json.loads(Path(inventory).read_text(encoding="utf-8"))
    registry = registry or LibraryContractRegistry.default()
    versions = {str(item.get("package")): str(item.get("version")) for item in data.get("packages", [])
                if item.get("package") and item.get("version")}
    evidence_document = _inventory_type_evidence_document(type_evidence)
    evidence_rules = load_inventory_type_evidence(type_evidence)
    baseline_needs = set(evidence_document.get("baseline_needs_contract") or [])
    rows, packages = [], {}
    for row in data.get("apis", []):
        if not row.get("numeric") or row.get("package") == "internal":
            continue
        callable_name = str(row.get("qualified_callable", ""))
        context = inventory_type_context(callable_name, evidence_rules)
        chain = registry.resolve_chain(callable_name, versions, context)
        non_numeric_reason = inventory_non_numeric_reason(callable_name)
        if chain["status"] == "SUPPORTED":
            classification, reason = "SUPPORTED", "REFERENCE_CONTRACT_CHAIN_RESOLVED"
        elif non_numeric_reason:
            classification, reason = "NON_NUMERIC", non_numeric_reason
        elif row.get("numeric_classification") == "OPAQUE_NATIVE":
            classification, reason = "OPAQUE_NATIVE", chain.get("reason", "NATIVE_SEMANTICS_UNRESOLVED")
        else:
            classification, reason = "NEEDS_CONTRACT", chain.get("reason", "REFERENCE_REVIEW_REQUIRED")
        item = {"package": row.get("package"), "version": row.get("version"),
                "qualified_callable": row.get("qualified_callable"), "call_count": row.get("call_count"),
                "usage_file_count": row.get("usage_file_count"),
                "source_classification": row.get("numeric_classification"),
                "classification": classification,
                "reason": reason, "resolved_operations": [op["callable"] for op in chain["operations"]],
                "unresolved_segments": chain["unresolved_segments"],
                "type_info": chain.get("type_info"), "type_context": context,
                "resolution_mechanisms": chain.get("mechanisms", [])}
        rows.append(item)
        summary = packages.setdefault(str(row.get("package")), {"total": 0, "SUPPORTED": 0,
                                                                  "NEEDS_CONTRACT": 0, "OPAQUE_NATIVE": 0,
                                                                  "NON_NUMERIC": 0})
        summary["total"] += 1
        summary[classification] += 1
    for summary in packages.values():
        summary["contract_scope_total"] = summary["total"] - summary["NON_NUMERIC"]
        summary["coverage"] = (summary["SUPPORTED"] / summary["contract_scope_total"]
                               if summary["contract_scope_total"] else 1.0)
    counts = {name: sum(row["classification"] == name for row in rows)
              for name in ("SUPPORTED", "NEEDS_CONTRACT", "OPAQUE_NATIVE", "NON_NUMERIC")}
    resolved_rows = [row for row in rows if row["classification"] == "SUPPORTED"
                     and row["qualified_callable"] in baseline_needs]
    metrics = {
        "return_type_resolved": sum("RETURN_TYPE_PROPAGATION" in row["resolution_mechanisms"]
                                    for row in resolved_rows),
        "receiver_propagation_resolved": sum("RECEIVER_PROPAGATION" in row["resolution_mechanisms"]
                                             for row in resolved_rows),
        "property_propagation_resolved": sum("PROPERTY_PROPAGATION" in row["resolution_mechanisms"]
                                             for row in resolved_rows),
        "ambiguous_remaining": sum(row.get("type_info", {}).get("evidence") == TypeEvidence.AMBIGUOUS.value
                                   for row in rows if row["classification"] == "NEEDS_CONTRACT"),
        "unknown_remaining": sum(row.get("type_info", {}).get("evidence") == TypeEvidence.UNKNOWN.value
                                 for row in rows if row["classification"] == "NEEDS_CONTRACT"),
        "namespace_corrections": sum("NAMESPACE_CORRECTION" in row["resolution_mechanisms"]
                                     for row in resolved_rows),
        "dask_xarray_namespace_corrections": sum(
            row["package"] == "dask"
            and row.get("type_context", {}).get("receiver_type") == "xarray.DataArray"
            and "NAMESPACE_CORRECTION" in row["resolution_mechanisms"]
            for row in rows if row["classification"] == "SUPPORTED"),
        "baseline_needs_contract": len(baseline_needs),
        "resolved_from_baseline": len(resolved_rows),
    }
    return {"schema_version": "0.1", "generated_date": date.today().isoformat(),
            "source_inventory": str(Path(inventory)), "registered_api_count": len(registry.registered_callables()),
            "counts": counts, "resolution_metrics": metrics, "packages": packages, "apis": rows}


def write_inventory_coverage(inventory: str | Path, output: str | Path,
                             registry: LibraryContractRegistry | None = None,
                             type_evidence: str | Path | None = None) -> dict[str, Any]:
    payload = analyze_inventory_coverage(inventory, registry, type_evidence)
    Path(output).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def integrate_reference_harvest(
    report: dict[str, Any], registry: LibraryContractRegistry | None = None,
) -> dict[str, Any]:
    """Attach registry precedence and coverage to an official-reference harvest.

    This function deliberately does not mutate ``registry.bindings``.  A
    harvested mapping is evidence for review, not a verified contract.
    """
    registry = registry or LibraryContractRegistry.default()
    version = str(report.get("library", {}).get("package_version") or "") or None
    existing_families = {item.value for item in SemanticFamily}
    counts = {"REGISTERED_CONTRACT": 0, "REFERENCE_SIMPLE_MAPPING": 0,
              "REFERENCE_DETAILED_CONTRACT": 0}
    target_counts = dict(counts)
    non_target_kinds = {"IO_BOUNDARY", "METADATA", "NON_NUMERIC"}
    for record in report.get("inventory", []):
        callable_name = str(record.get("qualified_name", ""))
        registered = registry.resolve(callable_name, version)
        if registered is not None:
            resolution = ReferenceHarvestResolution(
                callable_name, "REGISTERED_CONTRACT", registered.family,
                "VERIFIED_REGISTRY_CONTRACT", RESOLUTION_PRIORITY["REGISTERED_CONTRACT"])
            record["semantic_family"] = registered.family
            record["mathematical_ir"] = {"family": registered.family, **registered.bind}
        elif record.get("semantic_family") in existing_families:
            resolution = ReferenceHarvestResolution(
                callable_name, "REFERENCE_SIMPLE_MAPPING", str(record["semantic_family"]),
                "NEEDS_REVIEW", RESOLUTION_PRIORITY["REFERENCE_SIMPLE_MAPPING"])
        else:
            resolution = ReferenceHarvestResolution(
                callable_name, "REFERENCE_DETAILED_CONTRACT", None,
                "NEEDS_REVIEW", RESOLUTION_PRIORITY["REFERENCE_DETAILED_CONTRACT"])
        record["registry_resolution"] = asdict(resolution)
        counts[resolution.resolution_kind] += 1
        if record.get("contract_kind") not in non_target_kinds:
            target_counts[resolution.resolution_kind] += 1
    target = int(report.get("coverage", {}).get("TOTAL_CONTRACT_TARGET", 0))
    report["registry_integration"] = {
        "verified_registry_contract_count": counts["REGISTERED_CONTRACT"],
        "reference_simple_mapping_candidate_count": counts["REFERENCE_SIMPLE_MAPPING"],
        "reference_detailed_review_count": counts["REFERENCE_DETAILED_CONTRACT"],
        "target_resolution_counts": target_counts,
        "verified_registry_total": len(registry.registered_callables()),
        "resolution_priority": RESOLUTION_PRIORITY,
        "candidates_are_not_registry_bindings": True,
    }
    report["coverage"].update({
        "REGISTERED_CONTRACT_MATCH": target_counts["REGISTERED_CONTRACT"],
        "REFERENCE_SIMPLE_MAPPING_CANDIDATE": target_counts["REFERENCE_SIMPLE_MAPPING"],
        "REFERENCE_DETAILED_CONTRACT_CANDIDATE": target_counts["REFERENCE_DETAILED_CONTRACT"],
        "SEMANTIC_CONTRACT_COVERAGE": target_counts["REGISTERED_CONTRACT"] / target if target else 1.0,
        "DETAILED_REVIEW_COVERAGE": target_counts["REGISTERED_CONTRACT"] / target if target else 1.0,
    })
    return report
