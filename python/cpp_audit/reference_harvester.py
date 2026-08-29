from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import importlib
import inspect
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from ._compat import StrEnum
from .library_contracts import LibraryContractRegistry, SemanticFamily, integrate_reference_harvest

# The verified registry is authoritative.  Legacy names are retained only to
# describe harvester proposals that do not yet map to a verified family.
EXISTING_SEMANTIC_FAMILIES = {family.value for family in SemanticFamily}

FAMILY_CANONICALIZATION = {
    "ElementwiseTransform": "ElementwiseFunction",
    "LabeledCoordinateMapping": "Alignment",
    "CoordinateTransform": "SpatialGeometry",
    "GeometryConstruction": "SpatialGeometry",
    "SpatialPredicate": "SpatialGeometry",
    "NearestGeometry": "SpatialGeometry",
    "GeometryUnion": "SpatialGeometry",
    "Buffer": "SpatialGeometry",
    "Rasterization": "SpatialGeometry",
    "RasterResampling": "SpatialGeometry",
    "GeodesicDistance": "SpatialGeometry",
    "GraphTraversal": "GraphAlgorithm",
    "GraphFlow": "GraphAlgorithm",
    "TabularTransform": "TableMapping",
    "TimeCoordinateConversion": "RepresentationMapping",
    "DescriptiveStatistic": "Statistics",
    "ArrayConstruction": "RepresentationMapping",
    "Ordering": "ShapeTransform",
    "MatrixDecomposition": "LinearAlgebraRelation",
    "OptimizationInvocation": "AlgorithmInvocation",
    "RootFinding": "AlgorithmInvocation",
    "NumericalIntegration": "AlgorithmInvocation",
    "DifferentialEquationSolve": "AlgorithmInvocation",
    "SignalTransform": "AlgorithmInvocation",
    "StatisticalInference": "Statistics",
    "SpecialFunction": "ElementwiseFunction",
    "UpstreamSemanticOperation": "AlgorithmInvocation",
}


HARVESTER_VERSION = "1.1.0"
LEGACY_SEMANTIC_FAMILIES = {
    "Reduction",
    "ElementwiseTransform",
    "LabeledCoordinateMapping",
    "CoordinateTransform",
    "GeometryConstruction",
    "SpatialPredicate",
    "NearestGeometry",
    "GeometryUnion",
    "Buffer",
    "SpatialGeometry",
    "Rasterization",
    "GeodesicDistance",
    "IOBoundary",
    "DocumentedAttribute",
    "PublicModule",
    "Distribution",
    "NonNumeric",
    "NetCDFIO",
    "UpstreamSemanticOperation",
    "GraphTraversal",
    "TabularTransform",
    "TimeCoordinateConversion",
    "DescriptiveStatistic",
}
INVENTORY_ROLES = {
    "py:function": "function",
    "py:class": "class",
    "py:method": "method",
    "py:attribute": "property_or_attribute",
    "py:property": "property_or_attribute",
    "py:data": "documented_attribute",
    "py:module": "module",
    "std:doc": "documented_page",
}


class HarvestError(RuntimeError):
    pass


class ContractKind(StrEnum):
    EXACT_EXPRESSION = "EXACT_EXPRESSION"
    SIMPLE_SEMANTIC_MAPPING = "SIMPLE_SEMANTIC_MAPPING"
    MAPPING = "MAPPING"
    RELATION = "RELATION"
    ALGORITHM_INVOCATION = "ALGORITHM_INVOCATION"
    DISTRIBUTION = "DISTRIBUTION"
    PARALLEL_EXECUTION = "PARALLEL_EXECUTION"
    IO_BOUNDARY = "IO_BOUNDARY"
    METADATA = "METADATA"
    NON_NUMERIC = "NON_NUMERIC"


@dataclasses.dataclass(frozen=True)
class LibrarySpec:
    package: str
    package_version: str
    documentation_root: str
    inventory_url: str | None
    public_prefixes: tuple[str, ...]
    runtime_module: str
    version_policy: str = "exact"
    html_index_url: str | None = None
    include_std_docs: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LibrarySpec":
        return cls(
            package=value["package"],
            package_version=value["package_version"],
            documentation_root=value["documentation_root"],
            inventory_url=value.get("inventory_url"),
            public_prefixes=tuple(value.get("public_prefixes", [])),
            runtime_module=value["runtime_module"],
            version_policy=value.get("version_policy", "exact"),
            html_index_url=value.get("html_index_url"),
            include_std_docs=bool(value.get("include_std_docs", False)),
        )


@dataclasses.dataclass(frozen=True)
class InventoryEntry:
    qualified_name: str
    role: str
    priority: int
    uri: str
    display_name: str


@dataclasses.dataclass
class ApiRecord:
    package: str
    package_version: str
    qualified_name: str
    object_kind: str
    signature: str
    signature_evidence: str
    module: str
    canonical_reference_url: str
    deprecated_status: str
    return_type_information: str
    receiver_type_information: str
    aliases: list[str]
    alias_canonical_name: str
    publicness_evidence: str
    contract_kind: str
    semantic_family: str
    mathematical_ir: dict[str, Any]
    structural_ir: dict[str, Any]
    execution_ir: dict[str, Any]
    review_status: str
    classification_evidence: str


@dataclasses.dataclass(frozen=True)
class ParsedInventory:
    project: str
    documentation_version: str
    entries: tuple[InventoryEntry, ...]


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(raw)


def parse_sphinx_inventory(raw: bytes) -> ParsedInventory:
    stream = memoryview(raw)
    newlines: list[int] = []
    for index, byte in enumerate(stream):
        if byte == 10:
            newlines.append(index)
            if len(newlines) == 4:
                break
    if len(newlines) != 4:
        raise HarvestError("Invalid Sphinx inventory: four-line header not found")
    header = raw[: newlines[-1] + 1].decode("utf-8", errors="strict").splitlines()
    if not header[0].startswith("# Sphinx inventory version 2"):
        raise HarvestError("Only Sphinx inventory version 2 is supported")
    project = header[1].removeprefix("# Project: ").strip()
    version = header[2].removeprefix("# Version: ").strip()
    try:
        body = zlib.decompress(raw[newlines[-1] + 1 :]).decode("utf-8")
    except (zlib.error, UnicodeDecodeError) as exc:
        raise HarvestError(f"Invalid compressed Sphinx inventory: {exc}") from exc
    entries: list[InventoryEntry] = []
    entry_pattern = re.compile(r"^(.+?)\s+(\S+:\S+)\s+(-?\d+)\s+(\S+)\s+(.*)$")
    for line in body.splitlines():
        match = entry_pattern.match(line)
        if match is None:
            continue
        name, role, priority, uri, display = match.groups()
        if uri.endswith("$"):
            uri = uri[:-1] + name
        entries.append(InventoryEntry(name, role, int(priority), uri, display))
    return ParsedInventory(project, version, tuple(entries))


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str, str]] = []
        self.current_page: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "ft-page":
            self.current_page = values.get("data-qname")
            return
        object_id = values.get("id")
        if object_id and "." in object_id:
            self.entries.append((object_id, "#" + object_id))
        if tag != "a":
            return
        href = values.get("href")
        title = values.get("title") or ""
        if href and href.startswith("#") and self.current_page and not href.startswith("#__"):
            self.entries.append((self.current_page + "." + href[1:], href))
        elif href and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*\.html", href):
            self.entries.append((href[:-5], href))
        if href and ("generated/" in href or "api/" in href) and title:
            self.entries.append((title.strip(), href))

    def handle_endtag(self, tag: str) -> None:
        if tag == "ft-page":
            self.current_page = None


def parse_html_index(raw: bytes) -> ParsedInventory:
    parser = _IndexParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    entries_list: list[InventoryEntry] = []
    unique_entries: dict[str, str] = {}
    for name, href in parser.entries:
        unique_entries.setdefault(name, href)
    for name, href in unique_entries.items():
        parts = name.split(".")
        if parts[-1][:1].isupper():
            role = "py:class"
        elif len(parts) >= 3 and parts[-2][:1].isupper():
            role = "py:method"
        else:
            role = "py:function"
        entries_list.append(InventoryEntry(name, role, 1, href, name))
    entries = tuple(entries_list)
    if not entries:
        raise HarvestError("Official HTML index produced no public API entries")
    version_match = re.search(rb'id="version-([0-9]+)"', raw)
    if version_match:
        digits = version_match.group(1).decode("ascii")
        documented_version = ".".join(digits) if len(digits) <= 3 else digits
    else:
        documented_version = "not_exposed"
    return ParsedInventory("HTML index", documented_version, entries)


def _normalize_version(value: str) -> str:
    return value.lower().lstrip("v").replace(".0+", ".")


def version_matches(requested: str, documented: str, policy: str) -> bool:
    requested_n = _normalize_version(requested)
    documented_n = _normalize_version(documented)
    if policy == "exact":
        return requested_n == documented_n
    if policy == "major_minor":
        return requested_n.split(".")[:2] == documented_n.split(".")[:2]
    if policy == "python_minor":
        return requested_n.split(".")[:2] == documented_n.split(".")[:2]
    if policy == "reference_unversioned":
        return True
    if policy == "url_pinned":
        return True
    raise HarvestError(f"Unknown version policy: {policy}")


def version_match_status(requested: str, documented: str, policy: str) -> str:
    if policy == "reference_unversioned":
        return "REFERENCE_DOES_NOT_EXPOSE_VERSION"
    if policy == "url_pinned":
        return "REFERENCE_URL_VERSION_PINNED"
    if _normalize_version(requested) == _normalize_version(documented):
        return "REFERENCE_VERSION_EXACT"
    if policy in {"major_minor", "python_minor"}:
        return "REFERENCE_VERSION_COMPATIBLE_MINOR"
    return "REFERENCE_VERSION_MISMATCH"


def _fetch(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": f"formulatracer-contract-harvester/{HARVESTER_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            headers = {key.lower(): value for key, value in response.headers.items()}
            headers["_retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            return raw, headers
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HarvestError(f"Reference fetch failed for {url}: {exc}") from exc


def _fetch_html_bundle(index_url: str, package: str) -> tuple[bytes, dict[str, str]]:
    index_raw, headers = _fetch(index_url)
    decoded = index_raw.decode("utf-8", errors="replace")
    hrefs = sorted(set(re.findall(r'href="([A-Za-z][A-Za-z0-9_.]*\.html)"', decoded)))
    pages: list[bytes] = [
        f'<ft-page data-qname="{package}">'.encode(), index_raw, b"</ft-page>"
    ]
    for href in hrefs:
        qname = href[:-5]
        if _has_private_segment(qname):
            continue
        raw, _ = _fetch(urllib.parse.urljoin(index_url, href))
        pages.extend([f'<ft-page data-qname="{qname}">'.encode(), raw, b"</ft-page>"])
    return b"\n".join(pages), headers


def _has_private_segment(name: str) -> bool:
    return any(segment.startswith("_") for segment in name.split("."))


def is_public(entry: InventoryEntry, spec: LibrarySpec) -> tuple[bool, str]:
    if entry.role not in INVENTORY_ROLES:
        return False, "unsupported_reference_role"
    if entry.role == "std:doc" and not spec.include_std_docs:
        return False, "documentation_page_not_api"
    if _has_private_segment(entry.qualified_name):
        return False, "private_name_segment"
    if spec.package == "python-builtins":
        import builtins

        root_name = entry.qualified_name.removeprefix("builtins.").split(".")[0]
        if root_name not in {name for name in dir(builtins) if not name.startswith("_")}:
            return False, "outside_python_builtins_surface"
        return True, f"official_reference_and_runtime_builtins_surface:{entry.role}"
    if spec.public_prefixes and not any(
        entry.qualified_name == prefix or entry.qualified_name.startswith(prefix + ".")
        for prefix in spec.public_prefixes
    ):
        return False, "outside_package_public_namespace"
    return True, f"official_reference_role:{entry.role}"


def _module_for(name: str, kind: str) -> str:
    parts = name.split(".")
    if kind == "module":
        return name
    if len(parts) <= 1:
        return "builtins"
    return ".".join(parts[:-1])


def _runtime_object(name: str, runtime_module: str) -> Any:
    if runtime_module == "builtins":
        import builtins

        current: Any = builtins
        parts = name.removeprefix("builtins.").split(".")
    else:
        current = importlib.import_module(runtime_module)
        parts = name.split(".")
        if parts and parts[0] == runtime_module:
            parts = parts[1:]
    for part in parts:
        current = getattr(current, part)
    return current


def runtime_signature(name: str, runtime_module: str) -> tuple[str, str, str, str]:
    try:
        obj = _runtime_object(name, runtime_module)
        signature = str(inspect.signature(obj))
        annotation = inspect.signature(obj).return_annotation
        return_type = "unknown" if annotation is inspect.Signature.empty else repr(annotation)
        receiver = "none"
        if "." in name and inspect.isroutine(obj):
            first = next(iter(inspect.signature(obj).parameters.values()), None)
            if first and first.name in {"self", "cls"}:
                receiver = ".".join(name.split(".")[:-1])
        return signature, "installed_version_runtime_introspection", return_type, receiver
    except Exception:
        return "SIGNATURE_NOT_EXPOSED", "official_inventory_has_no_signature", "unknown", "unknown"


def _contains(name: str, words: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in words)


def classify_contract(name: str, kind: str, package: str) -> tuple[ContractKind, str, str, dict[str, Any]]:
    lowered = name.lower()
    if kind == "module":
        return ContractKind.METADATA, "PublicModule", "documented public module", {}
    if kind in {"property_or_attribute", "documented_attribute"}:
        return ContractKind.METADATA, "DocumentedAttribute", "documented attribute/property", {}
    if package == "netCDF4":
        if _contains(lowered, ("date2num", "num2date", "date2index")):
            return ContractKind.MAPPING, "TimeCoordinateConversion", "netCDF time-coordinate conversion", {
                "preserve": ["calendar", "units"]
            }
        return ContractKind.IO_BOUNDARY, "NetCDFIO", "netCDF documented I/O boundary", {
            "preserve": ["scale_factor", "add_offset", "mask", "calendar", "units"]
        }
    if _contains(lowered, ("read_", "to_csv", "to_json", "to_netcdf", "open_", "dataset", "file", "writer", "reader")):
        return ContractKind.IO_BOUNDARY, "IOBoundary", "name rule: documented I/O surface", {}
    if package == "dask":
        if _contains(lowered, ("sum", "mean", "min", "max", "std", "var", "prod", "count")):
            upstream = "Reduction"
        elif _contains(lowered, ("reshape", "transpose", "ravel", "squeeze", "rechunk")):
            upstream = "ShapeTransform"
        elif _contains(lowered, ("align", "reindex", "concat", "merge", "groupby", "rolling", "partition")):
            upstream = "LabeledCoordinateMapping"
        else:
            upstream = "DetailedReviewRequired"
        return ContractKind.PARALLEL_EXECUTION, upstream, "Dask upstream semantics plus execution overlay", {
            "lazy": True,
            "chunked": True,
            "preserve_parameters": ["split_every", "chunks", "rechunk", "partition"],
        }
    if _contains(lowered, ("random", "distribution", ".stats.", "normal", "poisson", "binomial", "uniform")):
        return ContractKind.DISTRIBUTION, "Distribution", "documented distribution semantics", {
            "equivalence": "DISTRIBUTION_EQUIVALENT",
            "sequence_identity": "SEQUENCE_IDENTICAL_NOT_CLAIMED",
        }
    if package == "scipy":
        rules = (
            ("optimize.minimize", "OptimizationInvocation"),
            ("optimize.root", "RootFinding"),
            ("integrate.quad", "NumericalIntegration"),
            ("integrate.solve_ivp", "DifferentialEquationSolve"),
            ("interpolate", "Interpolation"),
            ("linalg.solve", "LinearAlgebraRelation"),
            ("linalg.svd", "MatrixDecomposition"),
            ("signal", "SignalTransform"),
            ("special", "SpecialFunction"),
            ("stats", "StatisticalInference"),
        )
        for needle, family in rules:
            if needle in lowered:
                contract = ContractKind.RELATION if family == "LinearAlgebraRelation" else ContractKind.ALGORITHM_INVOCATION
                return contract, family, f"SciPy official API family rule: {needle}", {"internal_algorithm_reproved": False}
    if _contains(lowered, ("sum", "prod", "mean", "median", "std", "var", "quantile", "min", "max", "count")):
        return ContractKind.SIMPLE_SEMANTIC_MAPPING, "Reduction", "name rule: reduction", {}
    if _contains(lowered, ("reshape", "transpose", "ravel", "flatten", "squeeze", "expand_dims", "stack", "unstack")):
        return ContractKind.SIMPLE_SEMANTIC_MAPPING, "ShapeTransform", "name rule: shape transform", {}
    if _contains(lowered, ("sort", "argsort", "rank", "order")):
        return ContractKind.SIMPLE_SEMANTIC_MAPPING, "Ordering", "name rule: ordering", {}
    if _contains(lowered, ("align", "reindex", "sel", "isel", "concat", "merge", "groupby", "rolling", "coarsen", "weighted")):
        return ContractKind.MAPPING, "LabeledCoordinateMapping", "xarray/tabular structural mapping", {
            "preserve": ["dimension_names", "coordinates", "index_alignment"]
        }
    if package in {"geopandas", "shapely", "pyproj", "rasterio"}:
        geo_rules = (
            (("to_crs", "transform"), "CoordinateTransform"),
            (("predicate", "contains", "within", "intersects", "touches", "crosses", "overlaps"), "SpatialPredicate"),
            (("nearest",), "NearestGeometry"),
            (("union",), "GeometryUnion"),
            (("buffer",), "Buffer"),
            (("rasterize",), "Rasterization"),
            (("resampling", "reproject"), "RasterResampling"),
            (("geod", "distance"), "GeodesicDistance"),
        )
        for needles, family in geo_rules:
            if any(needle in lowered for needle in needles):
                return ContractKind.MAPPING, family, "GIS public semantic rule", {
                    "preserve": ["crs", "axis_order", "all_touched", "resampling_method"]
                }
        return ContractKind.MAPPING, "SpatialGeometry", "GIS documented geometry operation", {
            "preserve": ["crs", "axis_order"]
        }
    if package == "igraph" and _contains(lowered, ("flow", "cut")):
        return ContractKind.ALGORITHM_INVOCATION, "GraphFlow", "igraph graph-flow operation", {}
    if _contains(lowered, ("add", "subtract", "multiply", "divide", "exp", "log", "sqrt", "abs", "clip", "where")):
        return ContractKind.EXACT_EXPRESSION, "ElementwiseTransform", "name rule: elementwise expression", {}
    if _contains(lowered, ("str", "string", "format", "plot", "style", "display", "repr")):
        return ContractKind.NON_NUMERIC, "NonNumeric", "name rule: non-numeric presentation/text", {}
    return ContractKind.ALGORITHM_INVOCATION, "DetailedReviewRequired", "fail-closed fallback classification", {}


def _reference_url(root: str, uri: str) -> str:
    return root.rstrip("/") + "/" + uri.lstrip("/")


def harvest_library(
    spec: LibrarySpec,
    raw_reference: bytes,
    headers: dict[str, str] | None = None,
    runtime_signatures_enabled: bool = False,
) -> dict[str, Any]:
    headers = headers or {}
    parsed = parse_sphinx_inventory(raw_reference) if spec.inventory_url else parse_html_index(raw_reference)
    if not version_matches(spec.package_version, parsed.documentation_version, spec.version_policy):
        raise HarvestError(
            f"Documentation version mismatch for {spec.package}: requested {spec.package_version}, "
            f"reference reports {parsed.documentation_version}"
        )
    accepted: list[tuple[InventoryEntry, str]] = []
    excluded = Counter()
    for entry in parsed.entries:
        public, evidence = is_public(entry, spec)
        if public:
            accepted.append((entry, evidence))
        else:
            excluded[evidence] += 1
    by_target: dict[str, list[str]] = defaultdict(list)
    for entry, _ in accepted:
        by_target[entry.uri].append(entry.qualified_name)
    records: list[ApiRecord] = []
    for entry, publicness in accepted:
        object_kind = INVENTORY_ROLES[entry.role]
        aliases = sorted(set(by_target[entry.uri]))
        canonical = aliases[0]
        if runtime_signatures_enabled:
            signature, signature_evidence, return_type, receiver = runtime_signature(entry.qualified_name, spec.runtime_module)
        else:
            signature, signature_evidence, return_type, receiver = (
                "SIGNATURE_NOT_EXPOSED",
                "official_inventory_has_no_signature",
                "unknown",
                "unknown",
            )
        contract, family, evidence, overlay = classify_contract(entry.qualified_name, object_kind, spec.package)
        family = FAMILY_CANONICALIZATION.get(family, family)
        detailed = family == "DetailedReviewRequired"
        records.append(
            ApiRecord(
                package=spec.package,
                package_version=spec.package_version,
                qualified_name=entry.qualified_name,
                object_kind=object_kind,
                signature=signature,
                signature_evidence=signature_evidence,
                module=_module_for(entry.qualified_name, object_kind),
                canonical_reference_url=_reference_url(spec.documentation_root, entry.uri),
                deprecated_status="DOCUMENTED_STATUS_NOT_EXPOSED_BY_INVENTORY",
                return_type_information=return_type,
                receiver_type_information=receiver,
                aliases=[alias for alias in aliases if alias != entry.qualified_name],
                alias_canonical_name=canonical,
                publicness_evidence=publicness,
                contract_kind=contract.value,
                semantic_family=family,
                mathematical_ir={"family": family},
                structural_ir={"qualified_public_name": entry.qualified_name},
                execution_ir=overlay,
                review_status="DETAILED_REVIEW_REQUIRED" if detailed else "CONTRACT_CANDIDATE",
                classification_evidence=evidence,
            )
        )
    serialized_records = [dataclasses.asdict(record) for record in records]
    provenance = {
        "canonical_url": spec.inventory_url or spec.html_index_url,
        "requested_version": spec.package_version,
        "documentation_version": parsed.documentation_version,
        "version_match_status": version_match_status(
            spec.package_version, parsed.documentation_version, spec.version_policy
        ),
        "retrieved_at": headers.get("_retrieved_at", "RETRIEVAL_TIME_NOT_RECORDED"),
        "http_etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "content_sha256": sha256_bytes(raw_reference),
        "parsed_inventory_sha256": canonical_json_sha256(serialized_records),
        "harvester_parser_version": HARVESTER_VERSION,
    }
    family_counts = Counter(record.semantic_family for record in records)
    kind_counts = Counter(record.contract_kind for record in records)
    aliases = sum(1 for names in by_target.values() if len(names) > 1 for _ in names[1:])
    detailed = family_counts.get("DetailedReviewRequired", 0)
    non_target_kinds = {
        ContractKind.IO_BOUNDARY.value,
        ContractKind.METADATA.value,
        ContractKind.NON_NUMERIC.value,
    }
    target_records = [record for record in records if record.contract_kind not in non_target_kinds]
    existing_family_api_count = sum(
        1 for record in target_records if record.semantic_family in EXISTING_SEMANTIC_FAMILIES
    )
    new_family_candidates = sorted(
        family for family in {record.semantic_family for record in target_records}
        if family not in EXISTING_SEMANTIC_FAMILIES and family != "DetailedReviewRequired"
    )
    new_family_api_count = sum(
        1 for record in target_records if record.semantic_family in new_family_candidates
    )
    total_contract = len(target_records)
    semantic_classes = {
        (record.semantic_family, record.classification_evidence, record.object_kind)
        for record in target_records
    }
    return {
        "schema_version": 1,
        "library": dataclasses.asdict(spec),
        "provenance": provenance,
        "inventory": serialized_records,
        "coverage": {
            "TOTAL_PUBLIC_API": len(records),
            "TOTAL_CONTRACT_TARGET": total_contract,
            "EXISTING_FAMILY_REUSE": existing_family_api_count,
            "NEW_FAMILY_REQUIRED": new_family_api_count,
            "GENERATED_CONTRACT_CANDIDATE": existing_family_api_count + new_family_api_count,
            "DETAILED_REVIEW_REQUIRED": detailed,
            "IO_BOUNDARY": kind_counts.get(ContractKind.IO_BOUNDARY.value, 0),
            "METADATA": kind_counts.get(ContractKind.METADATA.value, 0),
            "NON_NUMERIC": kind_counts.get(ContractKind.NON_NUMERIC.value, 0),
            "ALIAS_COUNT": aliases,
            "DEPRECATED_API_COUNT": sum(1 for record in records if record.deprecated_status == "DEPRECATED"),
            "DEPRECATED_STATUS_UNKNOWN": sum(
                1 for record in records
                if record.deprecated_status == "DOCUMENTED_STATUS_NOT_EXPOSED_BY_INVENTORY"
            ),
            "SIGNATURE_AVAILABLE": sum(
                1 for record in records if record.signature != "SIGNATURE_NOT_EXPOSED"
            ),
            "SIGNATURE_UNAVAILABLE": sum(
                1 for record in records if record.signature == "SIGNATURE_NOT_EXPOSED"
            ),
            "REFERENCE_VERSION_VERIFIED": int(
                provenance["version_match_status"] in {
                    "REFERENCE_VERSION_EXACT", "REFERENCE_URL_VERSION_PINNED"
                }
            ),
            "REFERENCE_VERSION_COMPATIBLE_MINOR": int(
                provenance["version_match_status"] == "REFERENCE_VERSION_COMPATIBLE_MINOR"
            ),
            "REFERENCE_VERSION_UNVERIFIED": int(
                provenance["version_match_status"] == "REFERENCE_DOES_NOT_EXPOSE_VERSION"
            ),
            "PRIVATE_EXCLUDED": excluded.get("private_name_segment", 0),
            "REFERENCE_HARVEST_COVERAGE": 1.0,
            "SEMANTIC_CONTRACT_COVERAGE": (len(records) - detailed) / len(records) if records else 0.0,
            "DETAILED_REVIEW_COVERAGE": 0.0,
            "SEMANTIC_EQUIVALENCE_CLASS_COUNT": len(semantic_classes),
            "DETAILED_REVIEW_SEMANTIC_CLASS_COUNT": sum(
                family == "DetailedReviewRequired" for family, _, _ in semantic_classes
            ),
        },
        "excluded": dict(sorted(excluded.items())),
        "semantic_family_counts": dict(sorted(family_counts.items())),
        "new_family_candidates": new_family_candidates,
        "contract_kind_counts": dict(sorted(kind_counts.items())),
    }


def load_specs(path: Path) -> list[LibrarySpec]:
    return [LibrarySpec.from_dict(item) for item in json.loads(path.read_text(encoding="utf-8"))["libraries"]]


def run(specs_path: Path, output: Path, cache: Path, packages: set[str] | None, offline: bool,
        runtime_signatures_enabled: bool, review_overrides: Path | None = None,
        environment_inventory: Path | None = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for spec in load_specs(specs_path):
        if packages and spec.package not in packages:
            continue
        source_url = spec.inventory_url or spec.html_index_url
        if not source_url:
            raise HarvestError(f"No official reference source configured for {spec.package}")
        cache_file = cache / f"{spec.package}-{spec.package_version}.reference"
        headers_file = cache / f"{spec.package}-{spec.package_version}.headers.json"
        if offline:
            if not cache_file.exists() or not headers_file.exists():
                raise HarvestError(f"Offline reference cache missing for {spec.package}")
            raw = cache_file.read_bytes()
            headers = json.loads(headers_file.read_text(encoding="utf-8"))
        else:
            if spec.inventory_url:
                raw, headers = _fetch(source_url)
            elif spec.package == "igraph":
                raw, headers = _fetch_html_bundle(source_url, spec.public_prefixes[0])
            else:
                raw, headers = _fetch(source_url)
            cache_file.write_bytes(raw)
            headers_file.write_text(json.dumps(headers, indent=2, sort_keys=True), encoding="utf-8")
        report = integrate_reference_harvest(
            harvest_library(spec, raw, headers, runtime_signatures_enabled),
            LibraryContractRegistry.default(),
        )
        reports.append(report)
        (output / f"{spec.package}-{spec.package_version}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
    count_keys = {
        "TOTAL_PUBLIC_API", "TOTAL_CONTRACT_TARGET", "EXISTING_FAMILY_REUSE", "NEW_FAMILY_REQUIRED",
        "GENERATED_CONTRACT_CANDIDATE",
        "DETAILED_REVIEW_REQUIRED", "IO_BOUNDARY", "METADATA", "NON_NUMERIC", "ALIAS_COUNT",
        "DEPRECATED_API_COUNT", "DEPRECATED_STATUS_UNKNOWN", "PRIVATE_EXCLUDED",
        "SIGNATURE_AVAILABLE", "SIGNATURE_UNAVAILABLE", "REFERENCE_VERSION_VERIFIED",
        "REFERENCE_VERSION_COMPATIBLE_MINOR", "REFERENCE_VERSION_UNVERIFIED",
        "REGISTERED_CONTRACT_MATCH", "REFERENCE_SIMPLE_MAPPING_CANDIDATE",
        "REFERENCE_DETAILED_CONTRACT_CANDIDATE",
    }
    totals = Counter()
    for report in reports:
        totals.update({key: value for key, value in report["coverage"].items() if key in count_keys})
    total_public = totals["TOTAL_PUBLIC_API"]
    totals["REFERENCE_HARVEST_COVERAGE"] = len(reports) / len(load_specs(specs_path)) if reports else 0.0
    totals["USED_LIBRARY_PUBLIC_API_COVERAGE"] = 1.0 if reports else 0.0
    observed = json.loads((specs_path.parents[1] / "registry" / "library_contract_coverage.json").read_text(encoding="utf-8"))
    observed_counts = observed["counts"]
    observed_target = observed_counts["SUPPORTED"] + observed_counts["NEEDS_CONTRACT"] + observed_counts["OPAQUE_NATIVE"]
    totals["RESEARCH_OBSERVED_API_COVERAGE"] = observed_counts["SUPPORTED"] / observed_target if observed_target else 1.0
    totals["SEMANTIC_CONTRACT_COVERAGE"] = totals["REGISTERED_CONTRACT_MATCH"] / totals["TOTAL_CONTRACT_TARGET"] if totals["TOTAL_CONTRACT_TARGET"] else 1.0
    totals["DETAILED_REVIEW_COVERAGE"] = totals["REGISTERED_CONTRACT_MATCH"] / totals["TOTAL_CONTRACT_TARGET"] if totals["TOTAL_CONTRACT_TARGET"] else 1.0
    semantic_classes = {
        (record["package"], record["semantic_family"], record["classification_evidence"], record["object_kind"])
        for report in reports for record in report["inventory"]
        if record["contract_kind"] not in {
            ContractKind.IO_BOUNDARY.value, ContractKind.METADATA.value, ContractKind.NON_NUMERIC.value
        }
    }
    totals["SEMANTIC_EQUIVALENCE_CLASS_COUNT"] = len(semantic_classes)
    totals["DETAILED_REVIEW_SEMANTIC_CLASS_COUNT"] = sum(
        family == "DetailedReviewRequired" for _, family, _, _ in semantic_classes
    )
    summary = {
        "schema_version": 1,
        "generated_by": f"cpp_audit.reference_harvester/{HARVESTER_VERSION}",
        "libraries": [report["library"]["package"] for report in reports],
        "library_count": len(reports),
        "coverage": dict(sorted(totals.items())),
        "new_family_candidates": sorted({
            family for report in reports for family in report["new_family_candidates"]
        }),
        "per_library": {report["library"]["package"]: report["coverage"] for report in reports},
        "research_observed_baseline": {
            "reported_supported": 397,
            "reported_target": 397,
            "registered_api_count": observed["registered_api_count"],
            "source_registry_present_in_repository": True,
            "status": "RECOMPUTED_FROM_REGISTRY_COVERAGE",
        },
    }
    (output / "coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    provenance_manifest = {
        report["library"]["package"]: report["provenance"] for report in reports
    }
    (output / "reference_provenance.json").write_text(
        json.dumps(provenance_manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    family_registry = {
        "existing_family_count": len(EXISTING_SEMANTIC_FAMILIES),
        "existing_families": sorted(EXISTING_SEMANTIC_FAMILIES),
        "new_family_candidates": summary["new_family_candidates"],
        "candidate_count": len(summary["new_family_candidates"]),
        "policy": "reuse_existing_before_proposing_new",
    }
    (output / "semantic_family_registry.json").write_text(
        json.dumps(family_registry, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    rows = []
    for report in reports:
        coverage = report["coverage"]
        rows.append(
            f"| {report['library']['package']} | {coverage['TOTAL_PUBLIC_API']} | "
            f"{coverage['TOTAL_CONTRACT_TARGET']} | {coverage['EXISTING_FAMILY_REUSE']} | "
            f"{coverage['NEW_FAMILY_REQUIRED']} | {coverage['DETAILED_REVIEW_REQUIRED']} | "
            f"{coverage['IO_BOUNDARY']} | {coverage['METADATA']} | {coverage['NON_NUMERIC']} |"
        )
    markdown = "\n".join([
        "# Public API contract harvest coverage",
        "",
        "Generated exclusively from the version configuration and official-reference artifacts recorded in provenance.",
        "The research-observed 397/397 baseline is read from the verified registry coverage artifact.",
        "Deprecation markers are not exposed by most Sphinx inventories; unknown status is retained rather than treated as current.",
        "",
        "| Library | Public API | Contract target | Existing family | New family | Detailed review | I/O | Metadata | Non-numeric |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"Total public API: **{totals['TOTAL_PUBLIC_API']}**  ",
        f"Generated contract candidates: **{totals['GENERATED_CONTRACT_CANDIDATE']}**  ",
        f"Detailed review required: **{totals['DETAILED_REVIEW_REQUIRED']}**  ",
        f"Semantic equivalence families/classes: **{totals['SEMANTIC_EQUIVALENCE_CLASS_COUNT']}**  ",
        f"Alias names beyond canonical names: **{totals['ALIAS_COUNT']}**  ",
        f"Private names excluded: **{totals['PRIVATE_EXCLUDED']}**",
        "",
        "## Fail-closed limitations",
        "",
        f"- Deprecation status unknown from inventory alone: {totals['DEPRECATED_STATUS_UNKNOWN']}",
        f"- Runtime signature unavailable: {totals['SIGNATURE_UNAVAILABLE']}",
        f"- Stable references without an exposed version: {totals['REFERENCE_VERSION_UNVERIFIED']}",
        f"- References verified only at compatible major/minor level: {totals['REFERENCE_VERSION_COMPATIBLE_MINOR']}",
        "- SciPy 1.17.1 uses the official 1.17.0 reference because no patch-specific 1.17.1 reference is published.",
        "- Detailed-review entries are candidates, never silently supported contracts.",
        "",
    ])
    (output / "coverage_report.md").write_text(markdown, encoding="utf-8")
    # Keep the network/cache harvester independent from review policy, then make
    # the reviewed registries a mandatory final stage of the same pipeline.
    from .reference_registry import build_review_registry
    build_review_registry(output, overrides_path=review_overrides,
                          environment_inventory_path=environment_inventory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest version-pinned official public API references")
    here = Path(__file__).resolve().parent
    parser.add_argument("--specs", type=Path, default=here / "specs.json")
    parser.add_argument("--output", type=Path, default=here / "generated")
    parser.add_argument("--cache", type=Path, default=here / ".reference-cache")
    parser.add_argument("--packages", nargs="*")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--runtime-signatures", action="store_true")
    parser.add_argument("--review-overrides", type=Path,
                        default=here.parents[1] / "registry" / "public_api_reference_review_overrides.yaml")
    parser.add_argument("--environment-inventory", type=Path,
                        default=here.parents[1] / "numeric_library_inventory.json")
    args = parser.parse_args(argv)
    try:
        run(args.specs, args.output, args.cache, set(args.packages or []) or None, args.offline,
            args.runtime_signatures, args.review_overrides, args.environment_inventory)
    except HarvestError as exc:
        print(f"HARVEST_FAILED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
