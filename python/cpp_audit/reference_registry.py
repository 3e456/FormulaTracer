"""Reviewed class templates and registry objects for harvested public APIs.

This module never promotes a name-based proposal to an API-specific verified
contract.  It formalizes safe class boundaries, records review dispositions,
and preserves the verified Library Contract Registry as the highest authority.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import fnmatch
import hashlib
import inspect
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable

import yaml

from ._compat import StrEnum
from .library_contracts import LibraryContractRegistry, SemanticFamily
from .reference_harvester import (ContractKind, FAMILY_CANONICALIZATION, HARVESTER_VERSION,
                                  classify_contract)


REVIEW_REGISTRY_VERSION = "1.1.0"
NON_TARGET_KINDS = {ContractKind.IO_BOUNDARY.value, ContractKind.METADATA.value,
                    ContractKind.NON_NUMERIC.value}


class DeprecationStatus(StrEnum):
    CURRENT = "CURRENT"
    DEPRECATED = "DEPRECATED"
    UNKNOWN = "UNKNOWN"


class VersionVerificationStatus(StrEnum):
    VERIFIED = "VERSION_VERIFIED"
    PARTIALLY_VERIFIED = "VERSION_PARTIALLY_VERIFIED"
    UNVERIFIED = "VERSION_UNVERIFIED"


class CandidateDisposition(StrEnum):
    FORMALIZED = "FORMALIZED"
    REVIEW_PENDING = "REVIEW_PENDING"
    REFERENCE_INSUFFICIENT = "REFERENCE_INSUFFICIENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class ReferencePageFacts:
    deprecated_status: str = DeprecationStatus.UNKNOWN.value
    deprecated_since: str | None = None
    removal_version_if_documented: str | None = None
    replacement_if_documented: str | None = None
    signature: str = "SIGNATURE_UNKNOWN"
    signature_evidence: str = "SIGNATURE_UNKNOWN"


class _ReferencePageParser(HTMLParser):
    def __init__(self, qualified_name: str) -> None:
        super().__init__()
        self.qualified_name = qualified_name
        self.signature_chunks: list[str] = []
        self.deprecated_chunks: list[str] = []
        self._signature_depth = 0
        self._deprecated_depth = 0
        self.explicit_current = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        object_id = values.get("id") or ""
        if tag == "dt" and (object_id == self.qualified_name or object_id.endswith("." + self.qualified_name.split(".")[-1])):
            self._signature_depth = 1
        elif self._signature_depth:
            self._signature_depth += 1
        if "deprecated" in classes or values.get("data-deprecated") == "true":
            self._deprecated_depth = 1
        elif self._deprecated_depth:
            self._deprecated_depth += 1
        if values.get("data-deprecated") == "false" or values.get("data-api-status") == "current":
            self.explicit_current = True

    def handle_endtag(self, tag: str) -> None:
        if self._signature_depth:
            self._signature_depth -= 1
        if self._deprecated_depth:
            self._deprecated_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._signature_depth:
            self.signature_chunks.append(data)
        if self._deprecated_depth:
            self.deprecated_chunks.append(data)


def parse_reference_page(raw: bytes, qualified_name: str) -> ReferencePageFacts:
    """Extract only explicit signature/deprecation facts from an official page."""
    parser = _ReferencePageParser(qualified_name)
    parser.feed(raw.decode("utf-8", errors="replace"))
    signature_text = " ".join(" ".join(parser.signature_chunks).split())
    leaf = re.escape(qualified_name.split(".")[-1])
    signature_match = re.search(rf"(?:{leaf}|{re.escape(qualified_name)})\s*(\([^\n]*?\))", signature_text)
    signature = signature_match.group(1) if signature_match else "SIGNATURE_UNKNOWN"
    deprecated_text = " ".join(" ".join(parser.deprecated_chunks).split())
    if deprecated_text:
        since = re.search(r"Deprecated since version\s+([0-9]+(?:\.[0-9A-Za-z_-]+)*)", deprecated_text, re.I)
        removal = re.search(
            r"(?:removed|removal)\s+(?:in|at)\s+(?:version\s+)?([0-9]+(?:\.[0-9A-Za-z_-]+)*)",
            deprecated_text, re.I,
        )
        replacement = re.search(r"(?:use|prefer)\s+([A-Za-z_][A-Za-z0-9_.]*)\s+(?:instead|in its place)", deprecated_text, re.I)
        return ReferencePageFacts(
            DeprecationStatus.DEPRECATED.value,
            since.group(1) if since else None,
            removal.group(1) if removal else None,
            replacement.group(1) if replacement else None,
            signature,
            "OFFICIAL_REFERENCE_SIGNATURE" if signature_match else "SIGNATURE_UNKNOWN",
        )
    status = DeprecationStatus.CURRENT.value if parser.explicit_current else DeprecationStatus.UNKNOWN.value
    return ReferencePageFacts(status, signature=signature,
                              signature_evidence="OFFICIAL_REFERENCE_SIGNATURE" if signature_match else "SIGNATURE_UNKNOWN")


def resolve_signature(qualified_name: str, *, official_page: bytes | None = None,
                      stub_signature: str | None = None,
                      runtime_resolver: Callable[[str], Any] | None = None,
                      documented_call_pattern: str | None = None) -> tuple[str, str]:
    """Apply the required fail-closed signature evidence order."""
    if official_page is not None:
        facts = parse_reference_page(official_page, qualified_name)
        if facts.signature != "SIGNATURE_UNKNOWN":
            return facts.signature, facts.signature_evidence
    if stub_signature:
        return stub_signature, "STUB_SIGNATURE"
    if runtime_resolver is not None:
        try:
            return str(inspect.signature(runtime_resolver(qualified_name))), "RUNTIME_INSPECT_SIGNATURE"
        except (TypeError, ValueError, AttributeError, ImportError):
            pass
    if documented_call_pattern:
        return documented_call_pattern, "DOCUMENTED_CALL_PATTERN"
    return "SIGNATURE_UNKNOWN", "SIGNATURE_UNKNOWN"


def version_verification_status(reference_status: str) -> str:
    if reference_status in {"REFERENCE_VERSION_EXACT", "REFERENCE_URL_VERSION_PINNED"}:
        return VersionVerificationStatus.VERIFIED.value
    if reference_status == "REFERENCE_VERSION_COMPATIBLE_MINOR":
        return VersionVerificationStatus.PARTIALLY_VERIFIED.value
    return VersionVerificationStatus.UNVERIFIED.value


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def detailed_class_id(package: str, object_kind: str) -> str:
    return f"detailed_{_slug(package)}_{_slug(object_kind)}"


def _operator_from_name(name: str) -> str:
    leaf = name.rsplit(".", 1)[-1].lower()
    if leaf in {"sum", "nansum"}: return "add"
    if leaf in {"prod", "product", "nanprod"}: return "multiply"
    if leaf in {"min", "nanmin"}: return "minimum"
    if leaf in {"max", "nanmax"}: return "maximum"
    return leaf


def canonical_semantics_id(record: dict[str, Any], raw_family: str) -> str:
    name = str(record["qualified_name"])
    if raw_family == "DetailedReviewRequired":
        return detailed_class_id(str(record["package"]), str(record["object_kind"]))
    if raw_family in {SemanticFamily.REDUCTION.value, SemanticFamily.AGGREGATION.value}:
        return f"{_slug(raw_family)}_{_slug(_operator_from_name(name))}"
    if raw_family in {SemanticFamily.DISTRIBUTION.value, SemanticFamily.RANDOM_SAMPLE.value}:
        return f"distribution_{_slug(_operator_from_name(name))}"
    evidence = str(record.get("classification_evidence", "documented_mapping"))
    digest = hashlib.sha256(evidence.encode()).hexdigest()[:10]
    return f"{_slug(raw_family)}_{_slug(record['object_kind'])}_{digest}"


NON_SEMANTIC_MEMBER_NAMES = {
    "add_note", "with_traceback", "clear", "copy", "fromkeys", "get", "items", "keys",
    "pop", "popitem", "setdefault", "update", "values", "geterr", "seterr", "errstate",
    "set_random_state", "fast_forward", "jumped", "spawn", "to_clipboard",
}

DISTRIBUTION_OPERATIONS = {
    "cdf", "entropy", "expect", "fit", "fit_loc_scale", "freeze", "icdf", "iccdf",
    "ilogcdf", "ilogccdf", "interval", "isf", "kurtosis", "logcdf", "logccdf", "logpdf",
    "logpmf", "mean", "median", "moment", "nnlf", "pdf", "pmf", "ppf", "qrvs", "random",
    "rvs", "sample", "sf", "skewness", "standard_deviation", "stats", "std", "support",
    "u_error", "var", "variance",
}


def _semantic_subtype(name: str, family: str) -> str:
    leaf = name.rsplit(".", 1)[-1].lower()
    if family == SemanticFamily.SHAPE_TRANSFORM.value and leaf in {"sort", "sorted", "argsort"}:
        return "Ordering"
    if family == SemanticFamily.ALGORITHM_INVOCATION.value:
        if name.startswith("scipy.optimize.minimize"):
            return "OptimizationRelation"
        if name.startswith(("scipy.optimize.root", "scipy.optimize.Root")):
            return "RootFindingRelation"
        if name.startswith("scipy.integrate.solve_ivp"):
            return "DifferentialEquationSolve"
        if name.startswith("scipy.integrate."):
            return "NumericalIntegration"
        if name.startswith("scipy.signal."):
            return "SignalTransform"
    if family == SemanticFamily.DISTRIBUTION.value:
        if name.startswith("scipy.stats.") and leaf not in DISTRIBUTION_OPERATIONS and ".sampling." not in name:
            return "StatisticalInference"
        return "DistributionRelation"
    if family == SemanticFamily.SPATIAL_GEOMETRY.value:
        if any(token in leaf for token in ("contains", "covers", "within", "intersects", "touches",
                                            "crosses", "overlaps", "disjoint", "equals")):
            return "SpatialPredicate"
        if name.startswith("pyproj.") or ".warp." in name or ".transform" in name:
            return "CoordinateTransform"
        return "SpatialGeometry"
    if family == SemanticFamily.ALIGNMENT.value:
        if "groupby" in name.lower() or "groupby" in name or "rolling" in name.lower():
            return "GroupingAlignment"
        return "Alignment"
    if family == SemanticFamily.ELEMENTWISE_FUNCTION.value:
        if name.startswith("numpy.linalg."):
            return "LinearAlgebraRelation"
        if name == "numpy.logspace":
            return "ArrayConstruction"
        if name.startswith("pandas.api.typing.Expanding") or "ExponentialMovingWindow" in name:
            return "AggregationWindow"
        if name.startswith("scipy.spatial.transform."):
            return "CoordinateTransform"
        if name.startswith("scipy.cluster.hierarchy.DisjointSet.") or name.startswith("igraph.Graph"):
            return "GraphAlgorithm"
        if name.startswith("xarray."):
            return "Selection"
        if name.startswith("scipy.special."):
            return "SpecialFunction"
        if name.startswith("pandas."):
            return "TableMapping"
        return "ElementwiseTransform"
    return family


def refined_semantic_class_id(record: dict[str, Any], family: str) -> str:
    """Use operation identity, not a broad name-pattern bucket, for equivalence."""
    name = str(record["qualified_name"])
    leaf = _operator_from_name(name)
    subtype = _semantic_subtype(name, family)
    return f"{_slug(subtype)}_{_slug(leaf)}"


def _candidate_is_nonsemantic(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1].lower()
    return (leaf in NON_SEMANTIC_MEMBER_NAMES or ".distutils." in name or ".drawing." in name
            or ".plot." in name or ".io.formats." in name
            or name in {"dask.config.merge", "pandas.HDFStore.select", "numpy.lib.add_docstring",
                        "numpy.lib.add_newdoc", "numpy.lib.npyio.DataSource.abspath",
                        "bytearray.expandtabs", "bytes.expandtabs", "str.expandtabs", "frozenset.add"}
            or name.endswith(("Warning", "Error", "Exception")))


def _formalization_template(record: dict[str, Any], family: str) -> dict[str, Any] | None:
    name = str(record["qualified_name"])
    package = str(record["package"])
    leaf = name.rsplit(".", 1)[-1]
    subtype = _semantic_subtype(name, family)
    if _candidate_is_nonsemantic(name):
        return None

    supported = {
        SemanticFamily.REDUCTION.value, SemanticFamily.SHAPE_TRANSFORM.value,
        SemanticFamily.SPATIAL_GEOMETRY.value, SemanticFamily.INTERPOLATION.value,
        SemanticFamily.LINEAR_ALGEBRA_RELATION.value, SemanticFamily.GRAPH_ALGORITHM.value,
        SemanticFamily.DISTRIBUTION.value, SemanticFamily.ALIGNMENT.value,
        SemanticFamily.REPRESENTATION_MAPPING.value,
    }
    if family == SemanticFamily.ELEMENTWISE_FUNCTION.value:
        supported_name = (
            name.startswith("scipy.special.") or name.startswith("scipy.sparse.")
            or name.startswith("scipy.linalg.") or name.startswith("scipy.ndimage.")
            or name.startswith(("numpy.emath.", "numpy.lib.scimath.", "numpy.char.",
                                "numpy.strings.", "numpy.ma.", "numpy.ndarray.", "numpy.matrix.",
                                "numpy.memmap.", "numpy.recarray.", "numpy.record."))
            or name.startswith(("pandas.DataFrame.", "pandas.Series.", "pandas.Index.",
                                "pandas.Categorical"))
            or name.startswith(("pandas.api.typing.Expanding", "pandas.api.typing.ExponentialMovingWindow"))
            or name.startswith(("numpy.linalg.", "numpy.polynomial."))
            or name in {"numpy.logspace", "numpy.polyadd"}
            or name.startswith(("scipy.spatial.transform.", "scipy.cluster.hierarchy.DisjointSet.",
                                "igraph.Graph", "xarray.Index.", "xarray.core.indexing."))
            or name.endswith(".where")
        )
        if not supported_name:
            return None
    elif family == SemanticFamily.ALGORITHM_INVOCATION.value:
        if not name.startswith(("scipy.optimize.", "scipy.integrate.", "scipy.signal.")):
            return None
    elif family not in supported:
        return None

    if family == SemanticFamily.ALIGNMENT.value and (
            name.startswith(("dask.config.", "pandas.HDFStore.", "pandas.io.formats."))
            or ".distutils." in name):
        return None
    if family == SemanticFamily.DISTRIBUTION.value and leaf.lower() in NON_SEMANTIC_MEMBER_NAMES:
        return None
    if family == SemanticFamily.SHAPE_TRANSFORM.value and package == "python-builtins" and leaf not in {"sort", "sorted"}:
        return None

    preserve, ignore = _template_scopes(package)
    scopes = {
        "Reduction": ["axis", "dtype", "keepdims", "where", "initial", "missing_value_policy"],
        "ShapeTransform": ["shape", "axes", "order", "dimension_names"],
        "Alignment": ["keys", "indexes", "coordinates", "join", "fill_value", "sort", "dropna"],
        "GroupingAlignment": ["group_keys", "dropna", "sort", "observed", "window", "aggregation"],
        "DistributionRelation": ["distribution", "parameters", "shape", "population", "replace", "weights"],
        "StatisticalInference": ["null_relation", "statistic", "axis", "weights", "alternative", "confidence_level"],
        "OptimizationRelation": ["objective", "method", "bounds", "constraints", "tolerance", "stopping_criteria"],
        "RootFindingRelation": ["residual", "method", "bracket", "jacobian", "tolerance", "stopping_criteria"],
        "NumericalIntegration": ["integrand", "domain", "weights", "tolerance", "error_estimate"],
        "DifferentialEquationSolve": ["differential_relation", "initial_value", "domain", "method", "tolerance", "events"],
        "Interpolation": ["sample_points", "sample_values", "query_points", "method", "bounds", "fill_value"],
        "LinearAlgebraRelation": ["matrix", "right_hand_side", "axes", "decomposition", "tolerance"],
        "SignalTransform": ["signal", "axis", "window", "filter_coefficients", "sampling_frequency", "method"],
        "SpecialFunction": ["function_parameters", "domain", "branch_convention", "axis"],
        "SpatialGeometry": ["geometry", "crs", "axis_order", "predicate", "distance", "all_touched", "resampling"],
        "SpatialPredicate": ["left_geometry", "right_geometry", "predicate", "crs"],
        "CoordinateTransform": ["source_crs", "target_crs", "axis_order", "coordinates", "transform"],
        "GraphAlgorithm": ["graph", "directed", "weights", "source", "target", "cutoff"],
        "ElementwiseTransform": ["operator", "operands", "where", "dtype", "broadcast"],
        "TableMapping": ["index", "columns", "missing_value_policy", "alignment", "operator"],
        "Ordering": ["keys", "ascending", "stability", "missing_value_policy"],
        "ArrayConstruction": ["start", "stop", "count", "base", "dtype", "axis"],
        "AggregationWindow": ["window", "minimum_periods", "center", "weights", "aggregation"],
        "Selection": ["indexers", "dimension_names", "coordinates", "missing_value_policy"],
        "RepresentationMapping": ["units", "calendar", "input_representation", "output_representation"],
    }
    latex = {
        "OptimizationRelation": r"x^* = \operatorname*{arg\,min}_{x} f(x)",
        "RootFindingRelation": r"f(x^*) = 0",
        "NumericalIntegration": r"y = \int_{a}^{b} f(x)\,dx",
        "DifferentialEquationSolve": r"y'(t) = f(t,y(t))",
        "LinearAlgebraRelation": r"A x = b",
        "DistributionRelation": r"X \sim \mathcal{D}(\theta)",
        "StatisticalInference": r"T = \operatorname{statistic}(X; H_0)",
        "Interpolation": r"y = I_{method}(x; X,Y)",
        "Reduction": rf"y = \operatorname{{{_slug(leaf)}}}_{{axis}}(x)",
    }.get(subtype, rf"y = \operatorname{{{_slug(leaf)}}}(x; parameters)")
    extra_ignore = (["prng_engine", "internal_sampling_algorithm", "exact_sample_sequence"]
                    if subtype == "DistributionRelation" else [])
    return {
        "semantic_family": family,
        "semantic_subtype": subtype,
        "operation": leaf,
        "canonical_semantics": {
            "relation_kind": subtype,
            "operator": leaf,
            "mathematical_relation": "official_reference_defined_relation",
            "latex_template": latex,
        },
        "argument_mapping": {
            "rule": "official documented positional/keyword mapping",
            "preserve": sorted(set(preserve + scopes.get(subtype, scopes.get(family, [])))),
        },
        "return_type_rule": "official documented result relation; container type preserved when documented",
        "receiver_type_rule": "qualified documented owner; receiver supplies the first semantic operand",
        "preserve_scope": sorted(set(preserve + scopes.get(subtype, scopes.get(family, [])))),
        "ignore_scope": sorted(set(ignore + extra_ignore
                                   + ["internal_iteration", "native_kernel", "private_helper"])),
        "execution_semantics": ({
            "family": "ParallelExecution", "lazy": True,
            "preserve": ["chunks", "partitions", "split_every", "rechunk",
                         "scheduler_sensitive_documented_parameters"],
            "mathematical_claim": "MATHEMATICAL_EQUIVALENCE",
            "floating_point_claim": "FLOATING_REDUCTION_ORDER_DIFFERS",
        } if package == "dask" else None),
        "equivalence_claims": ({
            "distribution": "DISTRIBUTION_EQUIVALENT",
            "sample_sequence": "SEQUENCE_IDENTICAL_NOT_CLAIMED",
        } if subtype == "DistributionRelation" else {}),
        "signature_required": False,
        "signature_policy": "unknown acceptable when named semantic parameters are documented by the class contract",
        "review_basis": "OFFICIAL_REFERENCE_CLASS_SEMANTICS",
    }


def assess_candidate(record: dict[str, Any], family: str, *, signature_required: bool = False) -> tuple[str, dict[str, Any] | None, str]:
    """Fail-closed class-level promotion decision, independently unit-testable."""
    name = str(record["qualified_name"])
    if _candidate_is_nonsemantic(name):
        return CandidateDisposition.NOT_APPLICABLE.value, None, "NON_NUMERIC_OR_INHERITED_PUBLIC_SURFACE"
    template = _formalization_template(record, family)
    if template is None:
        return CandidateDisposition.REFERENCE_INSUFFICIENT.value, None, "REFERENCE_CLASS_SEMANTICS_NOT_UNIQUE"
    required = signature_required or bool(template["signature_required"])
    if required and record.get("signature_status") != "SIGNATURE_RESOLVED":
        return CandidateDisposition.REFERENCE_INSUFFICIENT.value, None, "SIGNATURE_REQUIRED_BUT_UNKNOWN"
    return CandidateDisposition.FORMALIZED.value, template, "REFERENCE_CLASS_TEMPLATE_REVIEWED"


def _load_environment_versions(path: Path | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    if path is None or not path.is_file():
        return {}, None
    raw = path.read_bytes()
    data = json.loads(raw)
    return ({str(item["package"]): item for item in data.get("packages", [])
             if item.get("version")}, hashlib.sha256(raw).hexdigest())


def _template_scopes(package: str) -> tuple[list[str], list[str]]:
    common = ["documented_arguments", "documented_return_relation", "documented_errors"]
    package_scope = {
        "numpy": ["axis", "dtype", "keepdims", "where", "initial", "missing_value_policy"],
        "pandas": ["group_keys", "dropna", "sort", "observed", "numeric_only", "index", "columns"],
        "xarray": ["dimension_names", "coordinates", "indexes", "join", "fill_value", "container_type"],
        "scipy": ["objective_or_relation", "method", "bounds", "constraints", "tolerance", "stopping_criteria"],
        "dask": ["lazy", "chunks", "partitions", "split_every", "rechunk", "scheduler_sensitive_metadata"],
        "igraph": ["graph_direction", "weights", "vertex_and_edge_identity"],
        "python-builtins": ["python_language_semantics", "iteration_order_when_documented"],
    }
    ignore = ["internal_implementation", "private_helpers", "native_kernel", "memory_layout"]
    if package == "dask":
        ignore += ["scheduler_algorithm", "worker_placement", "task_order_except_when_documented"]
    return common + package_scope.get(package, []), ignore


def _template_family(package: str, object_kind: str) -> str:
    if package == "dask":
        return SemanticFamily.PARALLEL_EXECUTION.value
    if object_kind == "class":
        return SemanticFamily.REPRESENTATION_MAPPING.value
    return SemanticFamily.ALGORITHM_INVOCATION.value


def _load_overrides(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("rules") or [])


def _matching_override(name: str, rules: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [rule for rule in rules if fnmatch.fnmatchcase(name, str(rule.get("callable", "")))]
    matches.sort(key=lambda rule: ("*" in str(rule.get("callable", "")), -len(str(rule.get("callable", "")))))
    return matches[0] if matches else None


def validate_alias_graph(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    targets: dict[str, set[str]] = defaultdict(set)
    for record in records:
        name = str(record["qualified_name"])
        canonical = str(record.get("alias_canonical_name") or name)
        if canonical != name:
            targets[name].add(canonical)
    ambiguous = {name: sorted(values) for name, values in targets.items() if len(values) > 1}
    edges = {name: next(iter(values)) for name, values in targets.items() if len(values) == 1}
    cycles: list[list[str]] = []
    for start in sorted(edges):
        seen: list[str] = []
        current = start
        while current in edges:
            if current in seen:
                cycles.append(seen[seen.index(current):] + [current])
                break
            seen.append(current)
            current = edges[current]
    return {"node_count": len({r["qualified_name"] for r in records}), "edge_count": len(edges),
            "edges": [{"alias": name, "canonical": canonical}
                      for name, canonical in sorted(edges.items())],
            "ambiguous": ambiguous, "cycles": cycles,
            "status": "VALID" if not ambiguous and not cycles else "INVALID"}


def _alignment_alias(name: str, public: set[str]) -> tuple[str | None, str]:
    explicit = {
        "dask.delayed": "dask.delayed.delayed",
        "numpy.abs": "numpy.absolute",
        "numpy.add.at": "numpy.ufunc.at", "numpy.maximum.at": "numpy.ufunc.at",
        "numpy.minimum.at": "numpy.ufunc.at", "numpy.ndarray.median": "numpy.median",
        "pandas.Index.tolist": "pandas.Index.to_list", "pandas.Series.tolist": "pandas.Series.to_list",
        "shapely.Geometry.buffer": "shapely.buffer", "shapely.geometry.Point": "shapely.Point",
        "shapely.ops.unary_union": "shapely.unary_union",
        "shapely.strtree.STRtree.nearest": "shapely.STRtree.nearest",
        "shapely.strtree.STRtree.query": "shapely.STRtree.query",
        "shapely.vectorized.contains": "shapely.contains_xy",
    }
    target = explicit.get(name)
    if target in public:
        return target, "ALIAS_OR_CANONICAL_NAME_DIFFERENCE"
    return None, ""


def align_formal_contracts(registry: LibraryContractRegistry, records: list[dict[str, Any]]) -> dict[str, Any]:
    public = {str(record["qualified_name"]) for record in records}
    rows = []
    for name in sorted(registry.registered_callables()):
        if name in public:
            rows.append({"formal_contract": name, "status": "ALIGNED_DIRECT", "public_api": name,
                         "reason": "EXACT_QUALIFIED_NAME"})
            continue
        alias, reason = _alignment_alias(name, public)
        if alias:
            rows.append({"formal_contract": name, "status": "ALIGNED_ALIAS", "public_api": alias,
                         "reason": reason})
            continue
        if name.startswith("dask.distributed."):
            gap = "HARVEST_GAP_DISTRIBUTED_REFERENCE_NOT_INCLUDED"
        elif name.startswith("scipy.sparse.csr_matrix.") or name in {
                "geopandas.GeoDataFrame.geometry", "xarray.DataArray.assign"}:
            gap = "HARVEST_GAP_PROPERTY_OR_METHOD_NOT_IN_INVENTORY"
        elif name.startswith(("shapely.ops.", "shapely.prepared.")):
            gap = "NAMESPACE_DIFFERENCE_WITHOUT_PUBLIC_INVENTORY_ALIAS"
        else:
            gap = "PUBLIC_REFERENCE_INVENTORY_GAP"
        rows.append({"formal_contract": name, "status": "INVENTORY_EXTERNAL", "public_api": None,
                     "reason": gap})
    counts = Counter(row["status"] for row in rows)
    aligned = counts["ALIGNED_DIRECT"] + counts["ALIGNED_ALIAS"]
    return {"schema_version": 1, "formal_contract_total": len(rows), "aligned": aligned,
            "alignment_rate": aligned / len(rows) if rows else 1.0,
            "counts": dict(sorted(counts.items())), "entries": rows}


def build_review_registry(generated_dir: Path, *, registry: LibraryContractRegistry | None = None,
                          overrides_path: Path | None = None,
                          environment_inventory_path: Path | None = None) -> dict[str, Any]:
    """Integrate generated reports into reviewed class and equivalence registries."""
    registry = registry or LibraryContractRegistry.default()
    report_paths = sorted(path for path in generated_dir.glob("*-*.json")
                          if path.name not in {"coverage_summary.json", "reference_provenance.json"})
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in report_paths]
    rules = _load_overrides(overrides_path)
    environment_versions, environment_inventory_sha256 = _load_environment_versions(environment_inventory_path)
    all_records = [record for report in reports for record in report.get("inventory", [])]
    alias_graph = validate_alias_graph(all_records)
    if alias_graph["status"] != "VALID":
        raise ValueError("Alias graph contains a cycle or ambiguous canonical target")

    class_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    detailed_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidate_dispositions = Counter()
    candidate_template_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_inspection_candidates: list[dict[str, Any]] = []
    detailed_count = 0
    existing_candidate_count = 0
    for report in reports:
        package = str(report["library"]["package"])
        version_status = version_verification_status(str(report["provenance"]["version_match_status"]))
        for record in report["inventory"]:
            name = str(record["qualified_name"])
            contract, raw_family, evidence, _ = classify_contract(name, str(record["object_kind"]), package)
            raw_family = FAMILY_CANONICALIZATION.get(raw_family, raw_family)
            record["harvested_semantic_family"] = raw_family
            record["classification_evidence"] = evidence
            record["version_verification_status"] = version_status
            override = _matching_override(name, rules)
            if override:
                record["deprecated_status"] = str(override.get("deprecated_status", DeprecationStatus.UNKNOWN.value))
                record["deprecated_since"] = override.get("deprecated_since")
                record["removal_version_if_documented"] = override.get("removal_version_if_documented")
                record["replacement_if_documented"] = override.get("replacement_if_documented")
                signature = override.get("official_signature")
                record["signature"] = signature or "SIGNATURE_UNKNOWN"
                record["signature_evidence"] = "OFFICIAL_REFERENCE_SIGNATURE" if signature else "SIGNATURE_UNKNOWN"
                record["deprecation_reference"] = override.get("official_reference")
            else:
                record["deprecated_status"] = DeprecationStatus.UNKNOWN.value
                record["deprecated_since"] = None
                record["removal_version_if_documented"] = None
                record["replacement_if_documented"] = None
                if record.get("signature") in {"SIGNATURE_NOT_EXPOSED", "SIGNATURE_NOT_EXPOSED_BY_REFERENCE"}:
                    record["signature"] = "SIGNATURE_UNKNOWN"
                    record["signature_evidence"] = "SIGNATURE_UNKNOWN"
            record["signature_status"] = ("SIGNATURE_RESOLVED" if record.get("signature") != "SIGNATURE_UNKNOWN"
                                          else "SIGNATURE_UNKNOWN")
            target = record.get("contract_kind") not in NON_TARGET_KINDS
            registered = registry.resolve(name, str(record.get("package_version") or ""))
            if raw_family == "DetailedReviewRequired" and target:
                detailed_count += 1
                class_id = detailed_class_id(package, str(record["object_kind"]))
                detailed_members[class_id].append(record)
                record["detailed_review_class_id"] = class_id
                record["formalization_status"] = "FORMALIZED_CLASS_BOUNDARY"
            elif raw_family in {family.value for family in SemanticFamily} and target:
                existing_candidate_count += 1
                if registered is not None:
                    disposition = CandidateDisposition.FORMALIZED.value
                    descriptor = _formalization_template(record, raw_family)
                    reason = "EXISTING_VERIFIED_REGISTRY_CONTRACT"
                elif record.get("alias_canonical_name") != name and record.get("alias_canonical_name") in registry.bindings:
                    disposition = CandidateDisposition.FORMALIZED.value
                    descriptor = _formalization_template(record, raw_family)
                    reason = "EXISTING_VERIFIED_CANONICAL_ALIAS_CONTRACT"
                else:
                    disposition, descriptor, reason = assess_candidate(record, raw_family)
                candidate_dispositions[disposition] += 1
                record["formalization_status"] = disposition
                record["formalization_reason"] = reason
                class_id = refined_semantic_class_id(record, raw_family)
                if disposition in {CandidateDisposition.NOT_APPLICABLE.value,
                                   CandidateDisposition.REFERENCE_INSUFFICIENT.value}:
                    class_id = f"{_slug(disposition)}_{class_id}"
                record["semantic_class_id"] = class_id
                if descriptor is not None:
                    record["reference_contract_template_id"] = f"reference_{class_id}"
                    record["canonical_semantics"] = descriptor["canonical_semantics"]
                    candidate_template_records[class_id].append(record)
                elif disposition == CandidateDisposition.REFERENCE_INSUFFICIENT.value:
                    source_inspection_candidates.append({
                        "qualified_name": name, "package": package,
                        "semantic_family": raw_family, "semantic_class_id": class_id,
                        "reason": reason, "official_reference": record["canonical_reference_url"],
                        "source_inspection_status": "CANDIDATE_NOT_PERFORMED",
                        "precedence": "OFFICIAL_REFERENCE_REMAINS_AUTHORITATIVE",
                    })
            else:
                record["formalization_status"] = "NOT_CONTRACT_TARGET"
            if not record.get("semantic_class_id") or raw_family == "DetailedReviewRequired":
                class_id = canonical_semantics_id(record, raw_family)
                record["semantic_class_id"] = class_id
            else:
                class_id = str(record["semantic_class_id"])
            if target:
                class_members[class_id].append(record)

    templates = []
    for class_id, members in sorted(detailed_members.items()):
        first = members[0]
        package, kind = str(first["package"]), str(first["object_kind"])
        preserve, ignore = _template_scopes(package)
        report = next(item for item in reports if item["library"]["package"] == package)
        templates.append({
            "class_id": class_id, "member_count": len(members),
            "member_apis": sorted(item["qualified_name"] for item in members),
            "semantic_family": _template_family(package, kind),
            "canonical_semantics": {"kind": "documented_public_invocation_boundary",
                                    "closed_form_claimed": False,
                                    "member_specific_semantics_required_for_equivalence": True},
            "argument_mapping": {"rule": "documented positional/keyword identity",
                                 "unknown_signature": "SIGNATURE_UNKNOWN_FAIL_CLOSED"},
            "return_type_rule": "official signature, stub, runtime annotation, documented call pattern, else UNKNOWN",
            "receiver_type_rule": "qualified owner for methods; none for functions; constructed type for classes",
            "preserve_scope": preserve, "ignore_scope": ignore,
            "version_constraints": {"requested": report["library"]["package_version"],
                                    "status": version_verification_status(report["provenance"]["version_match_status"])},
            "official_reference_provenance": {"documentation_root": report["library"]["documentation_root"],
                                               "sample_member_urls": sorted({m["canonical_reference_url"] for m in members})[:5],
                                               "raw_content_sha256": report["provenance"]["content_sha256"]},
            "review_status": "REFERENCE_REVIEWED_CLASS_TEMPLATE",
            "verification_boundary": "STRUCTURAL_INVOCATION_ONLY_NOT_API_SPECIFIC_EQUIVALENCE",
        })

    candidate_templates = []
    for class_id, members in sorted(candidate_template_records.items()):
        first = members[0]
        descriptor = _formalization_template(first, str(first["harvested_semantic_family"]))
        if descriptor is None:
            continue
        member_descriptors = [
            item for member in members
            if (item := _formalization_template(member, str(member["harvested_semantic_family"]))) is not None
        ]
        preserve_scope = sorted({scope for item in member_descriptors for scope in item["preserve_scope"]})
        ignore_scope = sorted({scope for item in member_descriptors for scope in item["ignore_scope"]})
        package_versions = sorted({f"{member['package']}=={member['package_version']}" for member in members})
        candidate_templates.append({
            "class_id": class_id,
            "template_id": f"reference_{class_id}",
            "semantic_family": descriptor["semantic_family"],
            "semantic_subtype": descriptor["semantic_subtype"],
            "member_count": len(members),
            "member_apis": sorted(member["qualified_name"] for member in members),
            "packages_and_versions": package_versions,
            "canonical_semantics": descriptor["canonical_semantics"],
            "argument_mapping": {**descriptor["argument_mapping"], "preserve": preserve_scope},
            "return_type_rule": descriptor["return_type_rule"],
            "receiver_type_rule": descriptor["receiver_type_rule"],
            "preserve_scope": preserve_scope,
            "ignore_scope": ignore_scope,
            "execution_semantics": ({
                "mathematical_semantics_shared": True,
                "default": "EAGER_OR_LIBRARY_DOCUMENTED",
                "overlays": [{
                    "applicable_packages": ["dask"], "family": "ParallelExecution",
                    "lazy": True,
                    "preserve": ["chunks", "partitions", "split_every", "rechunk",
                                 "scheduler_sensitive_documented_parameters"],
                    "mathematical_claim": "MATHEMATICAL_EQUIVALENCE",
                    "floating_point_claim": "FLOATING_REDUCTION_ORDER_DIFFERS",
                }],
            } if any(member["package"] == "dask" for member in members) else None),
            "equivalence_claims": descriptor["equivalence_claims"],
            "signature_required": descriptor["signature_required"],
            "signature_policy": descriptor["signature_policy"],
            "reference_provenance": {
                "official_reference_urls": sorted({member["canonical_reference_url"] for member in members}),
                "reference_hashes": sorted({
                    next(report["provenance"]["content_sha256"] for report in reports
                         if report["library"]["package"] == member["package"])
                    for member in members
                }),
                "review_basis": descriptor["review_basis"],
            },
            "formalization_status": CandidateDisposition.FORMALIZED.value,
            "binding_expansion": "CLASS_TEMPLATE_TO_MEMBER_API",
        })

    semantic_classes = []
    for class_id, members in sorted(class_members.items()):
        families = sorted({str(member.get("semantic_family")) for member in members})
        statuses = sorted({str(member.get("formalization_status")) for member in members})
        candidate_template = next((item for item in candidate_templates if item["class_id"] == class_id), None)
        semantic_classes.append({
            "id": class_id, "family": families[0] if len(families) == 1 else "MULTI_LIBRARY_CANONICAL",
            "canonical_semantics_id": class_id,
            "canonical_semantics": (candidate_template["canonical_semantics"] if candidate_template
                                    else members[0].get("mathematical_ir", {"family": families[0]})),
            "members": sorted(member["qualified_name"] for member in members),
            "member_count": len(members),
            "packages": sorted({member["package"] for member in members}),
            "review_status": ("REFERENCE_REVIEWED_CLASS_TEMPLATE" if class_id.startswith("detailed_")
                              else "REFERENCE_CANDIDATE_OR_VERIFIED_MEMBER"),
            "formalization_status": statuses[0] if len(statuses) == 1 else "MIXED",
            "reference_contract_template_id": (candidate_template["template_id"]
                                                if candidate_template else None),
        })

    alignment = align_formal_contracts(registry, all_records)
    deprecated_counts = Counter(record["deprecated_status"] for record in all_records)
    signature_counts = Counter(record["signature_status"] for record in all_records)
    version_counts = Counter(version_verification_status(report["provenance"]["version_match_status"])
                             for report in reports)
    bindings = [{key: record.get(key) for key in (
        "package", "package_version", "qualified_name", "semantic_class_id",
        "detailed_review_class_id", "semantic_family", "harvested_semantic_family",
        "formalization_status", "canonical_reference_url", "deprecated_status",
        "formalization_reason", "reference_contract_template_id", "canonical_semantics",
        "signature_status", "version_verification_status", "aliases", "alias_canonical_name")}
        for record in all_records if record.get("contract_kind") not in NON_TARGET_KINDS]

    for report, path in zip(reports, report_paths):
        package_records = report["inventory"]
        package_targets = [r for r in package_records if r.get("contract_kind") not in NON_TARGET_KINDS]
        environment = environment_versions.get(str(report["library"]["package"]))
        environment_matches = bool(environment and str(environment.get("version")) ==
                                   str(report["library"]["package_version"]))
        report["coverage"].update({
            "DEPRECATED_CURRENT": sum(r["deprecated_status"] == DeprecationStatus.CURRENT.value for r in package_records),
            "DEPRECATED_API_COUNT": sum(r["deprecated_status"] == DeprecationStatus.DEPRECATED.value for r in package_records),
            "DEPRECATED_STATUS_UNKNOWN": sum(r["deprecated_status"] == DeprecationStatus.UNKNOWN.value for r in package_records),
            "SIGNATURE_AVAILABLE": sum(r["signature_status"] == "SIGNATURE_RESOLVED" for r in package_records),
            "SIGNATURE_UNAVAILABLE": sum(r["signature_status"] == "SIGNATURE_UNKNOWN" for r in package_records),
            "SEMANTIC_CLASS_ASSIGNED": sum(bool(r.get("semantic_class_id")) for r in package_targets),
            "FORMAL_CLASS_BOUNDARY": sum(r.get("formalization_status") == "FORMALIZED_CLASS_BOUNDARY" for r in package_records),
            "FORMAL_CONTRACT": sum(r.get("registry_resolution", {}).get("status") ==
                                   "VERIFIED_REGISTRY_CONTRACT" for r in package_records),
            "REFERENCE_REVIEWED": sum(r.get("formalization_status") in {
                CandidateDisposition.FORMALIZED.value, "FORMALIZED_CLASS_BOUNDARY"
            } for r in package_records),
            "FORMALIZED_PUBLIC_API": sum(r.get("formalization_status") in {
                CandidateDisposition.FORMALIZED.value, "FORMALIZED_CLASS_BOUNDARY"
            } for r in package_records),
            "REVIEW_PENDING": sum(r.get("formalization_status") == CandidateDisposition.REVIEW_PENDING.value
                                  for r in package_records),
            "REFERENCE_INSUFFICIENT": sum(r.get("formalization_status") ==
                                          CandidateDisposition.REFERENCE_INSUFFICIENT.value
                                          for r in package_records),
            "NOT_APPLICABLE_CANDIDATE": sum(r.get("formalization_status") ==
                                            CandidateDisposition.NOT_APPLICABLE.value
                                            for r in package_records),
            "UNKNOWN_VERSION": (len(package_records) if version_verification_status(
                report["provenance"]["version_match_status"]
            ) == VersionVerificationStatus.UNVERIFIED.value else 0),
        })
        report["provenance"].update({
            "environment_inventory_sha256": environment_inventory_sha256,
            "environment_version": environment.get("version") if environment else None,
            "environment_version_source": environment.get("version_source") if environment else None,
            "environment_install_location": environment.get("install_location") if environment else None,
            "environment_version_status": ("ENVIRONMENT_VERSION_VERIFIED" if environment_matches
                                           else "ENVIRONMENT_VERSION_UNVERIFIED"),
        })
        report["provenance"]["review_parser_version"] = REVIEW_REGISTRY_VERSION
        report["provenance"]["reviewed_inventory_sha256"] = hashlib.sha256(
            json.dumps(package_records, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    artifact = {
        "schema_version": 1, "generated_by": f"cpp_audit.reference_registry/{REVIEW_REGISTRY_VERSION}",
        "formal_contract_objects": len(registry.registered_callables()) + len(templates) + len(candidate_templates),
        "existing_formal_contracts": len(registry.registered_callables()),
        "detailed_review_template_count": len(templates), "detailed_review_api_count": detailed_count,
        "candidate_reference_contract_template_count": len(candidate_templates),
        "existing_family_candidate_count": existing_candidate_count,
        "candidate_dispositions": {status.value: candidate_dispositions[status.value] for status in CandidateDisposition},
        "formalized_public_api_count": detailed_count + candidate_dispositions[CandidateDisposition.FORMALIZED.value],
        "semantic_class_count": len(semantic_classes), "alias_graph": alias_graph,
        "semantic_class_status": dict(sorted(Counter(item["formalization_status"]
                                                     for item in semantic_classes).items())),
        "deprecated": {status.value: deprecated_counts[status.value] for status in DeprecationStatus},
        "signature": dict(sorted(signature_counts.items())),
        "version": {status.value: version_counts[status.value] for status in VersionVerificationStatus},
        "environment_version": {
            "ENVIRONMENT_VERSION_VERIFIED": sum(
                str(item.get("version")) == str(report["library"]["package_version"])
                for report in reports
                if (item := environment_versions.get(str(report["library"]["package"]))) is not None
            ),
            "ENVIRONMENT_VERSION_UNVERIFIED": sum(
                environment_versions.get(str(report["library"]["package"])) is None
                for report in reports
            ),
            "source_inventory_sha256": environment_inventory_sha256,
        },
        "signature_semantic_sufficiency": {
            "resolved_where_required": sum(
                r.get("signature_status") == "SIGNATURE_RESOLVED"
                for records in candidate_template_records.values() for r in records
                if (_formalization_template(r, str(r["harvested_semantic_family"])) or {}).get("signature_required")
            ),
            "unknown_but_acceptable": sum(
                r.get("signature_status") == "SIGNATURE_UNKNOWN"
                for records in candidate_template_records.values() for r in records
            ),
            "blocking_unknown": sum(item["reason"] == "SIGNATURE_REQUIRED_BUT_UNKNOWN"
                                    for item in source_inspection_candidates),
        },
        "formal_contract_inventory_alignment": alignment,
    }
    (generated_dir / "detailed_review_classes.json").write_text(
        json.dumps({"schema_version": 1, "classes": templates}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "semantic_equivalence_registry.json").write_text(
        json.dumps({"schema_version": 1, "classes": semantic_classes}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "public_api_contract_bindings.json").write_text(
        json.dumps({"schema_version": 1, "bindings": bindings}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "candidate_reference_contracts.json").write_text(
        json.dumps({"schema_version": 1, "templates": candidate_templates},
                   ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "source_inspection_candidates.json").write_text(
        json.dumps({"schema_version": 1, "policy": "OFFICIAL_REFERENCE_HAS_PRECEDENCE",
                    "candidates": source_inspection_candidates},
                   ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "formal_contract_inventory_alignment.json").write_text(
        json.dumps(alignment, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "review_registry_summary.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (generated_dir / "alias_graph.json").write_text(
        json.dumps(alias_graph, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    coverage_path = generated_dir / "coverage_summary.json"
    if coverage_path.is_file():
        coverage_summary = json.loads(coverage_path.read_text(encoding="utf-8"))
        target = int(coverage_summary.get("coverage", {}).get("TOTAL_CONTRACT_TARGET", 0))
        coverage_summary["coverage"].update({
            "SEMANTIC_CONTRACT_COVERAGE": (
                artifact["formalized_public_api_count"] / target if target else 1.0
            ),
            "DETAILED_REVIEW_COVERAGE": (
                detailed_count / detailed_count if detailed_count else 1.0
            ),
            "FORMAL_CONTRACT_INVENTORY_ALIGNMENT": alignment["alignment_rate"],
            "FORMALIZED_PUBLIC_API_COUNT": artifact["formalized_public_api_count"],
            "FORMAL_CONTRACT_OBJECT_COUNT": artifact["formal_contract_objects"],
            "SEMANTIC_EQUIVALENCE_CLASS_COUNT": artifact["semantic_class_count"],
            "DETAILED_REVIEW_SEMANTIC_CLASS_COUNT": len(templates),
            "DEPRECATED_CURRENT": deprecated_counts[DeprecationStatus.CURRENT.value],
            "DEPRECATED_API_COUNT": deprecated_counts[DeprecationStatus.DEPRECATED.value],
            "DEPRECATED_STATUS_UNKNOWN": deprecated_counts[DeprecationStatus.UNKNOWN.value],
            "SIGNATURE_AVAILABLE": signature_counts["SIGNATURE_RESOLVED"],
            "SIGNATURE_UNAVAILABLE": signature_counts["SIGNATURE_UNKNOWN"],
            "FORMALIZED_PUBLIC_API": artifact["formalized_public_api_count"],
            "REVIEW_PENDING": candidate_dispositions[CandidateDisposition.REVIEW_PENDING.value],
            "REFERENCE_INSUFFICIENT": candidate_dispositions[
                CandidateDisposition.REFERENCE_INSUFFICIENT.value],
            "NOT_APPLICABLE_CANDIDATE": candidate_dispositions[
                CandidateDisposition.NOT_APPLICABLE.value],
            "VERSION_VERIFICATION_COVERAGE": (
                (version_counts[VersionVerificationStatus.VERIFIED.value]
                 + version_counts[VersionVerificationStatus.PARTIALLY_VERIFIED.value]) / len(reports)
                if reports else 1.0
            ),
        })
        coverage_summary["per_library"] = {
            report["library"]["package"]: report["coverage"] for report in reports
        }
        coverage_summary["review_registry"] = {
            key: value for key, value in artifact.items()
            if key not in {"formal_contract_inventory_alignment", "alias_graph"}
        }
        coverage_path.write_text(
            json.dumps(coverage_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    report_path = generated_dir / "coverage_report.md"
    if report_path.is_file():
        base = report_path.read_text(encoding="utf-8").split("\n## Reviewed registry\n", 1)[0].rstrip()
        disposition = artifact["candidate_dispositions"]
        library_rows = []
        for report in reports:
            coverage = report["coverage"]
            library_rows.append(
                f"| {report['library']['package']} | {coverage['TOTAL_PUBLIC_API']} | "
                f"{coverage['TOTAL_CONTRACT_TARGET']} | {coverage['FORMAL_CONTRACT']} | "
                f"{coverage['FORMALIZED_PUBLIC_API']} | {coverage['REVIEW_PENDING']} | "
                f"{coverage['REFERENCE_INSUFFICIENT']} | {coverage['SEMANTIC_CLASS_ASSIGNED']} | "
                f"{coverage['DEPRECATED_API_COUNT']} | {coverage['SIGNATURE_UNAVAILABLE']} | "
                f"{coverage['UNKNOWN_VERSION']} |"
            )
        reviewed = "\n".join([
            "", "## Reviewed registry", "",
            f"- Detailed-review templates: {len(templates)} ({detailed_count} API bindings)",
            f"- Candidate class templates: {len(candidate_templates)}",
            f"- Existing-family candidates: {existing_candidate_count}",
            f"- Candidate dispositions: {disposition}",
            f"- Formal contract objects: {artifact['formal_contract_objects']}",
            f"- Formalized public API bindings: {artifact['formalized_public_api_count']}",
            f"- Semantic equivalence classes: {artifact['semantic_class_count']}",
            f"- Formal-contract inventory alignment: {alignment['aligned']}/{alignment['formal_contract_total']} "
            f"({alignment['alignment_rate']:.2%})",
            "- A class-boundary contract is structural and does not assert member-specific mathematical equivalence.",
            "- REVIEW_PENDING, unknown deprecation, unknown signature, and unverified version states remain fail-closed.",
            "", "### Per-library reviewed coverage", "",
            "| Library | Public | Target | Registry contract | Formalized | Pending | Ref insufficient | Semantic class | Deprecated | Unknown signature | Unknown version |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            *library_rows,
            "",
        ])
        report_path.write_text(base + reviewed, encoding="utf-8")
    return artifact


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Build reviewed semantic class registries")
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--environment-inventory", type=Path,
                        default=Path(__file__).resolve().parents[2] / "numeric_library_inventory.json")
    args = parser.parse_args(argv)
    artifact = build_review_registry(args.generated, overrides_path=args.overrides,
                                     environment_inventory_path=args.environment_inventory)
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
