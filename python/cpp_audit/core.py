"""Deterministic IR extraction and fail-closed comparison for the initial slice.

The portable extractor intentionally accepts only the documented weighted-sum
subset.  The Clang frontend is the authoritative general C++ extractor; this
module makes the golden slice testable when LibTooling is unavailable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
import json
import re

import yaml

SCHEMA_VERSION = "0.1"
PROOF_LEVELS = {
    "SEMANTICALLY_VERIFIED", "VERIFIED_WITH_CONTRACT_ASSUMPTIONS",
    "STRUCTURALLY_VERIFIED", "TYPE_AND_SHAPE_VERIFIED",
    "NUMERICALLY_VALIDATED_ONLY", "UNRESOLVED", "UNSUPPORTED", "FAILED",
}
KNOWN_EFFECTS = {"Pure", "ReadMemory", "WriteMemory"}


def _native(action: str, **payload: Any) -> dict[str, Any]:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version":"1.0","kernel":"F",
            "operation":"LEGACY_CORE","action":action,**payload})["result"]


class AuditError(ValueError):
    """Raised when input cannot be resolved without guessing."""


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    specification: str
    implementation: str
    source: str


@dataclass
class AuditResult:
    status: str
    proof_level: str
    algorithm_id: str
    numeric_model: str
    spec_hash: str
    source_hash: str
    registry_hash: str
    implementation_ir: dict[str, Any]
    semantic_graph: dict[str, Any]
    obligations: list[str]
    assumptions: list[str]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["diagnostics"] = [asdict(item) for item in self.diagnostics]
        return data


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _stable_id(kind: str, payload: str) -> str:
    return f"{kind.lower()}-{_digest(payload.encode('utf-8'))[:16]}"


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate a versioned human algorithm YAML spec."""
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise AuditError("specification must be a YAML mapping")
    required = {"schema_version", "algorithm_id", "algorithm_version", "inputs", "outputs", "steps", "numeric_model"}
    missing = sorted(required - data.keys())
    if missing:
        raise AuditError(f"specification missing required fields: {', '.join(missing)}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise AuditError(f"unsupported schema_version: {data['schema_version']!r}")
    if data["algorithm_id"] != "weighted_sum":
        raise AuditError("initial slice supports algorithm_id weighted_sum only")
    return data


def registry_hash(root: str | Path) -> str:
    """Hash registry paths and bytes in stable lexical order."""
    base = Path(root)
    parts = bytearray()
    for path in sorted(base.rglob("*.yaml"), key=lambda p: p.as_posix()):
        parts.extend(path.relative_to(base).as_posix().encode())
        parts.extend(b"\0")
        parts.extend(path.read_bytes())
        parts.extend(b"\0")
    return _digest(bytes(parts))


def load_registry(root: str | Path, standard: str) -> dict[str, dict[str, Any]]:
    """Load the selected standard plus inherited C++17 entities."""
    if standard not in {"cpp17", "cpp20"}:
        raise AuditError("standard_version must be cpp17 or cpp20")
    base = Path(root)
    versions = ["cpp17"] if standard == "cpp17" else ["cpp17", "cpp20"]
    entities: dict[str, dict[str, Any]] = {}
    for version in versions:
        for path in sorted((base / version / "entities").glob("*.yaml")):
            item = yaml.safe_load(path.read_text(encoding="utf-8"))
            required = {"entity_id", "qualified_name", "effect", "proof_status", "lowering"}
            if not isinstance(item, dict) or required - item.keys():
                raise AuditError(f"invalid registry entity: {path}")
            entities[item["qualified_name"]] = item
    return entities


def _line_of(source: str, position: int) -> int:
    return source.count("\n", 0, position) + 1


def _diag(source_path: Path, source: str, needle: str, code: str, message: str,
          specification: str, implementation: str) -> Diagnostic:
    pos = source.find(needle)
    line = _line_of(source, max(pos, 0))
    return Diagnostic(code, message, specification, implementation, f"{source_path}:{line}")


def extract_ir(source_path: str | Path, standard: str = "cpp20",
               registry_root: str | Path = "registry/std") -> dict[str, Any]:
    """Extract deterministic Implementation IR for the weighted-sum subset."""
    path = Path(source_path)
    source = path.read_text(encoding="utf-8")
    entities = load_registry(registry_root, standard)
    diagnostics: list[Diagnostic] = []
    calls = sorted(set(re.findall(r"\b(std::[A-Za-z_]\w*(?:::\w+)*)\s*\(", source)))
    ignored = {"std::size_t"}
    for call in calls:
        if call in ignored:
            continue
        entity = entities.get(call)
        if entity is None:
            diagnostics.append(_diag(path, source, call, "UNREGISTERED_STANDARD_ENTITY",
                "standard library entity is not registered", "all result-affecting entities classified", call))
        elif entity["effect"] == "Unknown":
            diagnostics.append(_diag(path, source, call, "UNKNOWN_EFFECT",
                "unknown effect is fail-closed", "known permitted effect", "Unknown"))

    external = re.findall(r"(?<![\w:])([A-Za-z_]\w*)\s*\(", source)
    language_words = {"for", "if", "while", "switch", "return", "weighted_sum"}
    for name in sorted(set(external) - language_words):
        if f"std::{name}" in source or name in {"begin", "end"}:
            continue
        # Function definition names and span indexing are excluded conservatively.
        if re.search(rf"\b(?:void|auto|double|float|int)\s+{re.escape(name)}\s*\(", source):
            continue
        diagnostics.append(_diag(path, source, name + "(", "UNSUPPORTED_EXTERNAL_FUNCTION",
            "external function has no source or contract adapter", "no unresolved call", name))

    implementation = "inner_product" if "std::inner_product" in source else "explicit_loop"
    values = [
        {"id": _stable_id("input", "quantity"), "kind": "Input", "name": "quantity", "cpp_type": "std::span<const double>", "semantic_type": "Tensor[region,input]", "unit": "kg", "constness": "const"},
        {"id": _stable_id("input", "factor"), "kind": "Input", "name": "factor", "cpp_type": "std::span<const double>", "semantic_type": "Tensor[input]", "unit": "unit_weight", "constness": "const"},
        {"id": _stable_id("output", "result"), "kind": "Output", "name": "result", "cpp_type": "std::span<double>", "semantic_type": "Tensor[region]", "unit": "kg_result", "constness": "mutable"},
    ]
    operations = [
        {"id": _stable_id("op", "row-major-index"), "kind": "Index", "expression": "r * inputs + i"},
        {"id": _stable_id("op", "multiply-quantity-factor"), "kind": "Multiply", "arguments": ["quantity[r * inputs + i]", "factor[i]"]},
        {"id": _stable_id("op", "reduce-input-left"), "kind": "TransformReduce", "dimension": "input", "initial": 0.0, "reduction_order": "left_to_right"},
        {"id": _stable_id("op", "store-result-r"), "kind": "Store", "index": "r"},
    ]
    obligations = ["quantity.size == regions * inputs", "factor.size == inputs", "result.size == regions",
                   "valid_range", "index_in_bounds", "iterator_not_dangling", "no_forbidden_alias",
                   "object_lifetime_valid", "output_capacity_sufficient", "initialized_before_read"]
    return {"schema_version": SCHEMA_VERSION, "standard_version": standard, "source_hash": _digest(source.encode()),
            "function": "weighted_sum", "implementation_style": implementation, "values": values,
            "operations": operations, "obligations": obligations, "diagnostics": [asdict(d) for d in diagnostics]}


def normalize(ir: dict[str, Any], numeric_model: str = "AbstractReal") -> dict[str, Any]:
    """Normalize accepted loop/inner_product forms to one semantic graph."""
    return _native("NORMALIZE", ir=ir, numeric_model=numeric_model)


def _semantic_diagnostics(path: Path, source: str) -> list[Diagnostic]:
    checks: list[Diagnostic] = []
    def add(needle: str, code: str, message: str, spec: str, impl: str) -> None:
        checks.append(_diag(path, source, needle, code, message, spec, impl))
    if re.search(r"factor\s*\[\s*r\s*\]", source): add("factor[r]", "FACTOR_INDEX_MISMATCH", "Factor index mismatch", "factor[i]", "factor[r]")
    if re.search(r"quantity\s*\[\s*r\s*\+", source): add("quantity[r", "ROW_MAJOR_INDEX_MISMATCH", "Row-major index mismatch", "r * inputs + i", "r + i")
    if re.search(r"i\s*<\s*inputs\s*-\s*1", source): add("inputs - 1", "LOOP_BOUND_MISMATCH", "Reduction range excludes final input", "0 <= i < inputs", "0 <= i < inputs - 1")
    if re.search(r"i\s*<\s*regions", source): add("i < regions", "REDUCTION_DIMENSION_MISMATCH", "Reduction dimension mismatch", "reduce over input", "reduce over region")
    if re.search(r"\bacc\s*=\s*1(?:\.0)?\s*;", source): add("acc = 1", "INITIAL_VALUE_MISMATCH", "Initial value mismatch", "0", "1")
    if re.search(r"acc\s*\+=\s*quantity\s*\[[^]]+\]\s*\+\s*factor", source): add("+ factor", "TRANSFORM_MISMATCH", "Transform operation mismatch", "multiply", "add")
    if re.search(r"result\s*\[\s*i\s*\]", source): add("result[i]", "OUTPUT_INDEX_MISMATCH", "Output index mismatch", "result[r]", "result[i]")
    if "std::reduce" in source: add("std::reduce", "REDUCTION_ORDER_MISMATCH", "Implementation permits reordering", "left_to_right", "implementation_permitted_reordering")
    if re.search(r"std::inner_product\s*\([^;]*,\s*1(?:\.0)?\s*\)", source, re.DOTALL): add("1.0)", "INITIAL_VALUE_MISMATCH", "Initial value mismatch", "0", "1")
    if re.search(r"first\s*\+\s*inputs\s*-\s*1", source): add("inputs - 1", "ITERATOR_RANGE_MISMATCH", "Iterator range excludes final input", "[first, first + inputs)", "[first, first + inputs - 1)")
    if re.search(r"\bfloat\s+acc\b", source): add("float acc", "NUMERIC_NARROWING", "Implicit precision narrowing", "IEEE754Float64 accumulator", "IEEE754Float32 accumulator")
    for call in re.finditer(r"weighted_sum\s*\(([^;{}]+)\)\s*;", source, re.DOTALL):
        args = [part.strip() for part in call.group(1).split(",")]
        if len(args) >= 3 and re.sub(r"\W", "", args[0]) == re.sub(r"\W", "", args[2]):
            add(call.group(0), "FORBIDDEN_ALIAS", "Input and output arguments alias", "non-aliasing spans", f"quantity and result both use {args[0]}")
    # Accepted canonical expressions; absence is itself a resolvable mismatch.
    if "std::inner_product" not in source and not re.search(r"r\s*\*\s*inputs\s*\+\s*i", source): add("quantity[", "ROW_MAJOR_INDEX_UNRESOLVED", "Required row-major mapping was not found", "r * inputs + i", "unresolved")
    if "std::inner_product" not in source and not re.search(r"quantity\s*\[[^]]+\]\s*\*\s*factor\s*\[\s*i\s*\]", source): add("acc", "TRANSFORM_UNRESOLVED", "Required pairwise multiplication was not found", "quantity[...] * factor[i]", "unresolved")
    return checks


def audit(spec_path: str | Path, source_path: str | Path, standard: str = "cpp20",
          registry_root: str | Path = "registry/std") -> AuditResult:
    """Compare the initial weighted-sum spec and source without silent fallback."""
    spec_file, source_file = Path(spec_path), Path(source_path)
    spec, source = load_spec(spec_file), source_file.read_text(encoding="utf-8")
    ir = extract_ir(source_file, standard, registry_root)
    decision = _native("AUDIT_DECIDE", source=source, source_path=str(source_file), ir=ir,
                       numeric_model=spec["numeric_model"])
    diagnostics = [Diagnostic(**d) for d in ir["diagnostics"]] + [Diagnostic(**d) for d in decision["diagnostics"]]
    proof_level = "FAILED" if diagnostics else decision["proof_level"]
    return AuditResult("FAILED" if diagnostics else decision["status"], proof_level, spec["algorithm_id"], spec["numeric_model"],
        _digest(spec_file.read_bytes()), _digest(source.encode()), registry_hash(registry_root), ir,
        decision["semantic_graph"], ir["obligations"], decision["assumptions"], diagnostics)


def render_latex(spec: dict[str, Any]) -> str:
    """Render weighted sum from the canonical model."""
    return r"Y_{r} = \sum_{i} Q_{r,i} F_{i}"


def render_dot(graph: dict[str, Any]) -> str:
    """Render deterministic Graphviz DOT."""
    lines = ["digraph weighted_sum {", "  rankdir=LR;"]
    for node in graph["nodes"]:
        label = node.get("name", node["kind"])
        lines.append(f'  "{node["id"]}" [label="{label}"];')
    for edge in graph["edges"]:
        lines.append(f'  "{edge["source"]}" -> "{edge["target"]}" [label="{edge["argument_role"]}"];')
    return "\n".join(lines + ["}"])


def render_markdown(result: AuditResult) -> str:
    lines = [f"# Audit: {result.algorithm_id}", "", f"Status: **{result.status}**", f"Proof level: `{result.proof_level}`",
             f"Numeric model: `{result.numeric_model}`", "", "## Diagnostics", ""]
    if not result.diagnostics: lines.append("No semantic mismatches detected.")
    for d in result.diagnostics:
        lines.extend([f"### {d.code}", "", d.message, "", f"- Specification: `{d.specification}`", f"- Implementation: `{d.implementation}`", f"- Source: `{d.source}`", ""])
    lines.extend(["## Contract assumptions", ""] + [f"- {a}" for a in result.assumptions])
    return "\n".join(lines) + "\n"


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
