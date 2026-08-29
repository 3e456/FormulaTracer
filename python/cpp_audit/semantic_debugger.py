"""Fail-closed semantic divergence localization over existing audit evidence.

The debugger compares Mathematical IR and follows recorded project/source
correspondence.  It never searches source text or turns a runtime sample into a
formal root-cause proof.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

from .expression import render_expression

def _execute_native_kernel(request: dict[str, Any]) -> dict[str, Any]:
    # Local import keeps the public cpp_audit/formulatracer facade cycle-free.
    from formulatracer.native import execute_native_kernel
    return execute_native_kernel(request)


class DivergenceType(str, Enum):
    OPERATOR_MISMATCH = "OPERATOR_MISMATCH"
    CONSTANT_MISMATCH = "CONSTANT_MISMATCH"
    VARIABLE_MAPPING_MISMATCH = "VARIABLE_MAPPING_MISMATCH"
    INDEX_MISMATCH = "INDEX_MISMATCH"
    AXIS_MISMATCH = "AXIS_MISMATCH"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    SHAPE_MISMATCH = "SHAPE_MISMATCH"
    BRANCH_CONDITION_MISMATCH = "BRANCH_CONDITION_MISMATCH"
    BRANCH_VALUE_MISMATCH = "BRANCH_VALUE_MISMATCH"
    LOOP_BOUND_MISMATCH = "LOOP_BOUND_MISMATCH"
    REDUCTION_MISMATCH = "REDUCTION_MISMATCH"
    REDUCTION_ORDER_MISMATCH = "REDUCTION_ORDER_MISMATCH"
    APPROXIMATION_FAMILY_MISMATCH = "APPROXIMATION_FAMILY_MISMATCH"
    APPROXIMATION_PARAMETER_MISMATCH = "APPROXIMATION_PARAMETER_MISMATCH"
    DTYPE_MISMATCH = "DTYPE_MISMATCH"
    CAST_MISMATCH = "CAST_MISMATCH"
    RANGE_VIOLATION = "RANGE_VIOLATION"
    ERROR_BOUND_VIOLATION = "ERROR_BOUND_VIOLATION"
    FFI_BOUNDARY_UNRESOLVED = "FFI_BOUNDARY_UNRESOLVED"
    SERIALIZATION_DIVERGENCE = "SERIALIZATION_DIVERGENCE"
    LIBRARY_CONTRACT_MISMATCH = "LIBRARY_CONTRACT_MISMATCH"
    UNKNOWN_SEMANTIC_DIVERGENCE = "UNKNOWN_SEMANTIC_DIVERGENCE"


class RootCauseConfidence(str, Enum):
    PROVEN_ROOT_CAUSE = "PROVEN_ROOT_CAUSE"
    STRONG_ROOT_CAUSE_CANDIDATE = "STRONG_ROOT_CAUSE_CANDIDATE"
    POSSIBLE_ROOT_CAUSE = "POSSIBLE_ROOT_CAUSE"
    BLOCKED_BY_UNRESOLVED_SEMANTICS = "BLOCKED_BY_UNRESOLVED_SEMANTICS"


class DebugStatus(str, Enum):
    NO_SEMANTIC_DIVERGENCE_FOUND = "NO_SEMANTIC_DIVERGENCE_FOUND"
    SEMANTIC_DIVERGENCE_LOCALIZED = "SEMANTIC_DIVERGENCE_LOCALIZED"
    PARTIAL_SEMANTIC_LOCALIZATION = "PARTIAL_SEMANTIC_LOCALIZATION"
    SEMANTIC_DEBUG_BLOCKED = "SEMANTIC_DEBUG_BLOCKED"
    SEMANTIC_DEBUG_FAILED = "SEMANTIC_DEBUG_FAILED"


class DebugLocalizationLevel(str, Enum):
    EXACT_SOURCE_SPAN = "EXACT_SOURCE_SPAN"
    SOURCE_SPAN_SET = "SOURCE_SPAN_SET"
    CORRECT_SEMANTIC_NODE = "CORRECT_SEMANTIC_NODE"
    SOURCE_BASIC_BLOCK = "SOURCE_BASIC_BLOCK"
    SOURCE_FUNCTION = "SOURCE_FUNCTION"
    SOURCE_MODULE = "SOURCE_MODULE"
    UNRESOLVED = "UNRESOLVED"
    FALSE_LOCALIZATION = "FALSE_LOCALIZATION"


@dataclass
class AffectedOutput:
    output_id: str
    name: str
    root_id: str
    end_to_end_status: str | None
    artifact_outputs: list[str] = field(default_factory=list)


@dataclass
class DebugTrace:
    trace_id: str
    root_cause_node: str
    dependency_path: list[dict[str, Any]]
    output_ids: list[str]
    artifact_outputs: list[str] = field(default_factory=list)


@dataclass
class MinimalDivergentSubgraph:
    subgraph_id: str
    theory_nodes: list[dict[str, Any]]
    implementation_nodes: list[dict[str, Any]]
    boundary_inputs: list[dict[str, Any]]
    boundary_outputs: list[str]
    source_spans: list[dict[str, Any]]
    semantic_difference: dict[str, Any]


@dataclass
class SemanticDivergence:
    divergence_id: str
    type: str
    expected: Any
    actual: Any
    expression_path: list[Any]
    source: dict[str, Any] | None
    semantic_difference: dict[str, Any]
    mathematical_layer: bool = True


@dataclass
class FirstSemanticDivergence:
    divergence_id: str
    root_id: str
    output_ids: list[str]
    divergence: SemanticDivergence
    matching_upstream_region: list[dict[str, Any]]
    downstream_affected_region: list[str]
    minimal_subgraph_id: str


@dataclass
class ErrorContribution:
    component_id: str
    source: str
    magnitude: float | None
    semantic_cause_id: str | None
    proof_status: str
    rank: int


@dataclass
class ErrorAmplificationPoint:
    operation: str
    expression_path: list[Any]
    amplification_factor: float | None
    source: dict[str, Any] | None
    explanation: str


@dataclass
class FailureRegion:
    region_id: str
    input_intervals: dict[str, dict[str, float]]
    status: str
    evidence: str
    divergence_ids: list[str]
    branch_constraints: list[str] = field(default_factory=list)


@dataclass
class CounterexampleCandidate:
    candidate_id: str
    inputs: dict[str, float]
    expected_value: float | None
    actual_value: float | None
    status: str
    evidence_level: str = "NUMERICALLY_CHECKED"


@dataclass
class CounterexampleSearchResult:
    status: str
    failure_regions: list[FailureRegion]
    counterexample_candidates: list[CounterexampleCandidate]
    subdivisions: int
    method: str = "INTERVAL_SUBDIVISION_WITH_SYMBOLIC_NARROWING"
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: return _serial(self)


@dataclass
class RootCauseCandidate:
    finding_id: str
    divergence_type: str
    confidence: str
    expected_semantics: Any
    actual_semantics: Any
    source_file: str | None
    source_span: dict[str, Any] | None
    source_symbol: str | None
    upstream_context: list[dict[str, Any]]
    downstream_affected_outputs: list[AffectedOutput]
    proofs_invalidated: list[str]
    error_bounds_invalidated: list[str]
    range_claims_invalidated: list[str]
    rank: int


@dataclass
class DebugFinding:
    finding_id: str
    type: str
    expected: Any
    actual: Any
    source: dict[str, Any] | None
    affected_outputs: list[AffectedOutput]
    debug_trace: DebugTrace
    confidence: str
    diagnostic_code: str
    message_key: str
    parameters: dict[str, Any]
    invalidated_claims: list[str]
    error_contributions: list[ErrorContribution] = field(default_factory=list)
    amplification_points: list[ErrorAmplificationPoint] = field(default_factory=list)
    source_spans: list[dict[str, Any]] = field(default_factory=list)
    localization_level: str = DebugLocalizationLevel.UNRESOLVED.value
    localization_confidence: str = "FAIL_CLOSED"
    blocking_evidence: list[dict[str, Any]] = field(default_factory=list)
    rewrite_explanation: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DebugLocalizationMetrics:
    total: int = 0
    exact_span: int = 0
    span_set_contains_ground_truth: int = 0
    correct_semantic_node: int = 0
    correct_basic_block: int = 0
    correct_function: int = 0
    unresolved: int = 0
    false_localization: int = 0


@dataclass(frozen=True)
class MinimalReproducer:
    reproducer_id: str
    directory: str
    source_file: str
    status: str
    divergence_type: str
    original_project_modified: bool = False


@dataclass
class AuditDebugResult:
    status: str
    project_status: str
    end_to_end_status: str | None
    findings: list[DebugFinding]
    first_divergences: list[FirstSemanticDivergence]
    minimal_divergent_subgraphs: list[MinimalDivergentSubgraph]
    root_causes: list[RootCauseCandidate]
    affected_outputs: list[AffectedOutput]
    debug_traces: list[DebugTrace]
    invalidated_claims: list[str]
    root_results: dict[str, str]
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    _project: Any = field(default=None, repr=False, compare=False, metadata={"serialize": False})
    localization_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = _serial(self)
        value.pop("_project", None)
        return value

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent) + "\n"

    def write_json(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_json(), encoding="utf-8"); return target

    def to_latex(self) -> str:
        def esc(value: Any) -> str:
            replacements = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&",
                            "#": r"\#", "{": r"\{", "}": r"\}", "$": r"\$",
                            "^": r"\^{}", "~": r"\~{}"}
            return "".join(replacements.get(character, character) for character in str(value))

        def human_path(value: Any) -> str:
            raw = str(value); name = Path(raw).name
            return raw if raw.isascii() else (name if name.isascii() else "non-ASCII path (exact path retained in JSON)")

        lines = [r"\documentclass{article}", r"\usepackage[T1]{fontenc}",
                 r"\usepackage[margin=0.7in]{geometry}", r"\usepackage{longtable}",
                 r"\begin{document}", r"\small", r"\section*{FormulaTracer Semantic Debug Report}",
                 rf"Debug status: \texttt{{{esc(self.status)}}}\\",
                 rf"End-to-end status: \texttt{{{esc(self.end_to_end_status)}}}\\",
                 f"Findings: {len(self.findings)}; root causes: {len(self.root_causes)}"]
        if not self.findings:
            lines += [r"\section*{Debug Summary}", "No semantic divergence was found in the comparable Mathematical IR.\\\\"]
        for index, finding in enumerate(self.findings, 1):
            source = finding.source or {}
            lines += [rf"\section*{{Finding {index}: {esc(finding.type)}}}",
                      rf"Confidence: \texttt{{{esc(finding.confidence)}}}\\",
                      rf"Source: \texttt{{{esc(human_path(source.get('file', 'unavailable')))}:{esc(source.get('begin_line', '?'))}}}\\",
                      r"\subsection*{Expected}", r"\[" + _render_semantics(finding.expected) + r"\]",
                      r"\subsection*{Actual}", r"\[" + _render_semantics(finding.actual) + r"\]",
                      r"\subsection*{Affected outputs}", r"\begin{itemize}"]
            lines += [rf"\item \texttt{{{esc(item.name)}}}" for item in finding.affected_outputs]
            lines += [r"\end{itemize}", r"\subsection*{Invalidated claims}", r"\begin{itemize}"]
            lines += [rf"\item \texttt{{{esc(item)}}}" for item in finding.invalidated_claims] or [r"\item None"]
            lines += [r"\end{itemize}"]
        lines += [r"\section*{Localization boundary}",
                  r"Runtime samples are evidence only. Unresolved FFI boundaries stop localization. Detailed graphs remain in JSON.",
                  r"\end{document}", ""]
        return "\n".join(lines)

    def write_latex(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_latex(), encoding="utf-8"); return target

    def search_counterexamples(self, ranges: Mapping[str, Any] | None = None, *, max_depth: int = 6) -> CounterexampleSearchResult:
        if self._project is None:
            return CounterexampleSearchResult("COUNTEREXAMPLE_SEARCH_UNAVAILABLE", [], [], 0,
                diagnostics=[{"code": "PROJECT_CONTEXT_UNAVAILABLE"}])
        return search_counterexamples(self._project, self, ranges=ranges, max_depth=max_depth)

    def evaluate_localization(self, ground_truth: Mapping[str, Mapping[str, Any]]) -> DebugLocalizationMetrics:
        metrics = DebugLocalizationMetrics(total=len(self.findings))
        for finding in self.findings:
            expected = ground_truth.get(finding.finding_id) or ground_truth.get(finding.type)
            if expected is None:
                if finding.localization_level == DebugLocalizationLevel.UNRESOLVED.value: metrics.unresolved += 1
                continue
            exact = finding.source == expected
            contains = any(_span_contains(span, expected) for span in finding.source_spans)
            if exact: metrics.exact_span += 1
            if contains: metrics.span_set_contains_ground_truth += 1
            if exact or contains: metrics.correct_semantic_node += 1
            elif finding.localization_level not in {DebugLocalizationLevel.UNRESOLVED.value,
                                                    DebugLocalizationLevel.CORRECT_SEMANTIC_NODE.value}:
                metrics.false_localization += 1
            if any(span.get("file") == expected.get("file") and span.get("begin_line") == expected.get("begin_line")
                   for span in finding.source_spans): metrics.correct_basic_block += 1
            if any(span.get("file") == expected.get("file") for span in finding.source_spans): metrics.correct_function += 1
        self.localization_metrics = asdict(metrics)
        return metrics

    def create_reproducer(self, finding_id: str, directory: str | Path | None = None) -> MinimalReproducer:
        finding = next((item for item in self.findings if item.finding_id == finding_id), None)
        if finding is None: raise KeyError(finding_id)
        selection = _execute_native_kernel({"schema_version": "1.0", "kernel": "E",
            "operation": "SELECT_MINIMAL_REPRODUCER", "finding": _serial(finding)})["result"]
        if selection.get("status") != "MINIMAL_REPRODUCER_SELECTED":
            return MinimalReproducer(str(selection.get("reproducer_id", "reproducer:unresolved")), "", "",
                "MINIMAL_REPRODUCER_UNRESOLVED", finding.type)
        if directory is None:
            directory = Path(tempfile.mkdtemp(prefix="formulatracer-reproducer-"))
        root = Path(directory); root.mkdir(parents=True, exist_ok=True)
        source = root / "reproducer.py"
        payload = {"expected": selection["expected"], "actual": selection["actual"],
                   "type": selection["divergence_type"]}
        script = ("# Self-owned FormulaTracer semantic reproducer; no research data embedded.\n"
                  "from cpp_audit.semantic_debugger import _compare\n"
                  f"EXPECTED = {payload['expected']!r}\nACTUAL = {payload['actual']!r}\n"
                  "assert _compare(EXPECTED, ACTUAL), 'divergence was not reproduced'\n")
        source.write_text(script, encoding="utf-8")
        reproduced = bool(_compare(finding.expected, finding.actual))
        return MinimalReproducer("reproducer:" + _id("fixture", payload).split(":", 1)[1], str(root),
            str(source), "DIVERGENCE_REPRODUCED" if reproduced else "REPRODUCER_INCONCLUSIVE", finding.type)


_NOISE = {"source_node_ids", "source_spans", "source_span", "provenance", "reference_contract",
          "normalization", "original_index", "api", "canonical_name", "local_name", "expression_id",
          "semantic_error_cause_id", "ffi_error_cause_id", "error_role", "shape_constraints",
          "alignment_constraints", "cfg_merge", "operator_span", "callable_span", "argument_spans", "keyword_spans",
          "condition_span", "branch_spans"}
_CHILD_KEYS = {"args", "input", "body", "condition", "then", "else", "indices", "base", "expression",
               "transform", "initial_value", "index_domain", "lower", "upper", "upper_exclusive", "step",
               "query_point", "support_points", "weights", "integration_domain", "partition", "step_size"}


def _serial(value: Any) -> Any:
    if isinstance(value, Enum): return value.value
    if is_dataclass(value):
        return {key: _serial(item) for key, item in vars(value).items() if not key.startswith("_")}
    if isinstance(value, dict): return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)): return [_serial(item) for item in value]
    return value


def _id(prefix: str, value: Any) -> str:
    encoded = json.dumps(_serial(value), sort_keys=True, ensure_ascii=False, default=str)
    return prefix + ":" + sha256(encoded.encode()).hexdigest()[:16]


def _render_semantics(value: Any) -> str:
    if not isinstance(value, dict): return r"\mathtt{" + str(value).replace("_", r"\_") + "}"
    try:
        display_value = deepcopy(value)
        for _, node in _walk(display_value):
            if node.get("op") in {"FreeVariable", "BoundVariable"} and node.get("name"):
                node["name"] = _logical_name(node)
        wrapper = {"outputs": [{"target": {"op": "FreeVariable", "name": "value"}, "expression": display_value}]}
        rendered = render_expression(wrapper, "latex").strip()
        return rendered.split("=", 1)[-1].strip() if "=" in rendered else rendered
    except (KeyError, TypeError, ValueError):
        return r"\mathtt{" + str(value.get("op", "semantic node")).replace("_", r"\_") + "}"


def _logical_name(node: Mapping[str, Any]) -> str:
    return str(node.get("local_name") or node.get("name") or node.get("base") or "").replace("::", ".").rsplit(".", 1)[-1]


def _same_scalar(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0, abs_tol=0)
    return left == right


def _walk(node: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], dict[str, Any]]]:
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            if isinstance(value, dict): yield from _walk(value, (*path, key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict): yield from _walk(item, (*path, key, index))


def _semantic_signature(value: Any) -> str:
    if isinstance(value, dict):
        cleaned = {key: _semantic_signature(item) for key, item in value.items() if key not in _NOISE}
        return json.dumps(cleaned, sort_keys=True, default=str)
    if isinstance(value, list): return json.dumps([_semantic_signature(item) for item in value])
    return repr(value)


def _matching_children(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for key in sorted(_CHILD_KEYS & expected.keys() & actual.keys()):
        left, right = expected[key], actual[key]
        if _semantic_signature(left) == _semantic_signature(right):
            result.append({"role": key, "semantics": deepcopy(left)})
    return result


def _taxonomy(expected: dict[str, Any], actual: dict[str, Any], *, role: str | None = None) -> tuple[str, bool]:
    left, right = expected.get("op"), actual.get("op")
    if left != right:
        if left in {"Reduce", "FiniteSum", "FiniteProduct", "FoldLeft", "TransformReduce"} or right in {
                "Reduce", "FiniteSum", "FiniteProduct", "FoldLeft", "TransformReduce"}:
            return DivergenceType.REDUCTION_MISMATCH.value, True
        approximation_ops = {"Derivative", "DiscreteDifference", "Quadrature", "Interpolation"}
        if left in approximation_ops or right in approximation_ops:
            return DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value, True
        if left == "Cast" or right == "Cast": return DivergenceType.CAST_MISMATCH.value, False
        return DivergenceType.OPERATOR_MISMATCH.value, True
    if left == "Constant": return DivergenceType.CONSTANT_MISMATCH.value, True
    if left in {"FreeVariable", "BoundVariable"}: return DivergenceType.VARIABLE_MAPPING_MISMATCH.value, True
    if role in {"condition"}: return DivergenceType.BRANCH_CONDITION_MISMATCH.value, True
    if role in {"then", "else"}: return DivergenceType.BRANCH_VALUE_MISMATCH.value, True
    if role in {"index_domain", "lower", "upper", "upper_exclusive", "step"}: return DivergenceType.LOOP_BOUND_MISMATCH.value, True
    return DivergenceType.UNKNOWN_SEMANTIC_DIVERGENCE.value, True


def _metadata_difference(expected: dict[str, Any], actual: dict[str, Any]) -> tuple[str, str, Any, Any, bool] | None:
    op = expected.get("op")
    checks = []
    if op == "Constant": checks.append(("value", DivergenceType.CONSTANT_MISMATCH.value, True))
    if op in {"Reduce", "FiniteSum", "FiniteProduct", "FoldLeft", "TransformReduce"}:
        checks += [("reduction", DivergenceType.REDUCTION_MISMATCH.value, True),
                   ("operation", DivergenceType.REDUCTION_MISMATCH.value, True),
                   ("axes", DivergenceType.AXIS_MISMATCH.value, True),
                   ("axis", DivergenceType.AXIS_MISMATCH.value, True),
                   ("dimensions", DivergenceType.DIMENSION_MISMATCH.value, True),
                   ("dimension", DivergenceType.DIMENSION_MISMATCH.value, True),
                   ("reduction_order", DivergenceType.REDUCTION_ORDER_MISMATCH.value, False)]
    checks += [("shape", DivergenceType.SHAPE_MISMATCH.value, True),
               ("axes", DivergenceType.AXIS_MISMATCH.value, True),
               ("axis", DivergenceType.AXIS_MISMATCH.value, True),
               ("dimensions", DivergenceType.DIMENSION_MISMATCH.value, True),
               ("dimension", DivergenceType.DIMENSION_MISMATCH.value, True),
               ("reduction_order", DivergenceType.REDUCTION_ORDER_MISMATCH.value, False),
               ("dtype", DivergenceType.DTYPE_MISMATCH.value, False),
               ("cast_kind", DivergenceType.CAST_MISMATCH.value, False)]
    approximation = (("family_id", DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value, True),
                     ("approximation_family_id", DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value, True),
                     ("method", DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value, True),
                     ("convergence_order", DivergenceType.APPROXIMATION_PARAMETER_MISMATCH.value, True),
                     ("spacing", DivergenceType.APPROXIMATION_PARAMETER_MISMATCH.value, True))
    if op in {"Derivative", "DiscreteDifference", "Quadrature", "Interpolation"}: checks += list(approximation)
    for key, kind, mathematical in checks:
        if key in expected or key in actual:
            left, right = expected.get(key), actual.get(key)
            if left != right: return key, kind, left, right, mathematical
    # Reference-contract calls retain public parameters under ``keywords``.
    # These parameters are mathematical when they select an axis/dimension,
    # interpolation method, dtype, or branch behavior; ignoring them can turn
    # a source mutation into a false equivalence.
    left_keywords, right_keywords = expected.get("keywords"), actual.get("keywords")
    if isinstance(left_keywords, dict) or isinstance(right_keywords, dict):
        left_keywords = left_keywords if isinstance(left_keywords, dict) else {}
        right_keywords = right_keywords if isinstance(right_keywords, dict) else {}
        for key in sorted(left_keywords.keys() | right_keywords.keys()):
            left, right = left_keywords.get(key), right_keywords.get(key)
            if left == right: continue
            kind = (DivergenceType.AXIS_MISMATCH.value if key == "axis" else
                    DivergenceType.DIMENSION_MISMATCH.value if key == "dim" else
                    DivergenceType.DTYPE_MISMATCH.value if key == "dtype" else
                    DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value if key == "method" else
                    DivergenceType.UNKNOWN_SEMANTIC_DIVERGENCE.value)
            return f"keywords.{key}", kind, left, right, key != "dtype"
    return None


def _semantic_fragment(node: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    fragment = {"op": node.get("op"), key: deepcopy(value)}
    keyword = key.split(".", 1)[1] if key.startswith("keywords.") else key
    keyword_spans = node.get("keyword_spans") or {}
    origin = keyword_spans.get(keyword) if isinstance(keyword_spans, dict) else None
    if not isinstance(origin, dict): origin = node.get("source_span")
    if isinstance(origin, dict): fragment["source_span"] = deepcopy(origin)
    return fragment


def _compare(expected: Any, actual: Any, path: tuple[Any, ...] = (), role: str | None = None,
             symbols: dict[str, str] | None = None) -> list[dict[str, Any]]:
    symbols = symbols if symbols is not None else {}
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        if _same_scalar(expected, actual): return []
        return [{"type": DivergenceType.UNKNOWN_SEMANTIC_DIVERGENCE.value, "expected": expected,
                 "actual": actual, "path": list(path), "role": role, "mathematical": True,
                 "boundary_inputs": []}]
    if expected.get("op") != actual.get("op"):
        kind, mathematical = _taxonomy(expected, actual, role=role)
        return [{"type": kind, "expected": deepcopy(expected), "actual": deepcopy(actual),
                 "path": list(path), "role": role, "mathematical": mathematical,
                 "boundary_inputs": _matching_children(expected, actual)}]
    op = expected.get("op")
    if op in {"FreeVariable", "BoundVariable", "IndexedValue"}:
        left, right = _logical_name(expected), _logical_name(actual)
        previous = symbols.get(left)
        if previous is None: symbols[left] = right
        elif previous != right:
            return [{"type": DivergenceType.VARIABLE_MAPPING_MISMATCH.value,
                     "expected": deepcopy(expected), "actual": deepcopy(actual), "path": list(path),
                     "role": role, "mathematical": True, "boundary_inputs": []}]
    metadata = _metadata_difference(expected, actual)
    if metadata:
        key, kind, left, right, mathematical = metadata
        return [{"type": kind, "expected": _semantic_fragment(expected, key, left),
                 "actual": _semantic_fragment(actual, key, right), "path": [*path, key], "role": role,
                 "mathematical": mathematical, "boundary_inputs": _matching_children(expected, actual)}]
    if op == "IndexedValue" and len(expected.get("indices", [])) != len(actual.get("indices", [])):
        return [{"type": DivergenceType.INDEX_MISMATCH.value, "expected": deepcopy(expected),
                 "actual": deepcopy(actual), "path": [*path, "indices"], "role": "indices",
                 "mathematical": True, "boundary_inputs": []}]
    divergences = []
    for key in sorted(_CHILD_KEYS & (expected.keys() | actual.keys())):
        left, right = expected.get(key), actual.get(key)
        if isinstance(left, list) or isinstance(right, list):
            if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
                kind = DivergenceType.INDEX_MISMATCH.value if key == "indices" else DivergenceType.UNKNOWN_SEMANTIC_DIVERGENCE.value
                divergences.append({"type": kind, "expected": deepcopy(left), "actual": deepcopy(right),
                                    "path": [*path, key], "role": key, "mathematical": True, "boundary_inputs": []})
                continue
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                # Literal nodes deliberately keep the stable public IR shape.
                # Recover their exact origin from the enclosing expression.
                argument_spans = actual.get("argument_spans")
                if (key == "args" and isinstance(right_item, dict) and not right_item.get("source_span")
                        and isinstance(argument_spans, list) and index < len(argument_spans)
                        and isinstance(argument_spans[index], dict)):
                    right_item = {**right_item, "source_span": deepcopy(argument_spans[index])}
                divergences += _compare(left_item, right_item, (*path, key, index), key, symbols)
        elif isinstance(left, dict) or isinstance(right, dict):
            divergences += _compare(left, right, (*path, key), key, symbols)
        elif not _same_scalar(left, right):
            kind = (DivergenceType.BRANCH_CONDITION_MISMATCH.value if key == "condition" else
                    DivergenceType.LOOP_BOUND_MISMATCH.value if key in {"lower", "upper", "upper_exclusive", "step"} else
                    DivergenceType.UNKNOWN_SEMANTIC_DIVERGENCE.value)
            divergences.append({"type": kind, "expected": deepcopy(left), "actual": deepcopy(right),
                                "path": [*path, key], "role": key, "mathematical": True, "boundary_inputs": []})
    return divergences


def _root_for(project: Any, output_id: str) -> str:
    return next((root.root_id for root in project.roots if any(item.output_id == output_id for item in root.outputs)), "root:unknown")


def _artifact_refs(project: Any, output: Any) -> list[str]:
    refs = []
    for artifact in project.artifacts:
        matches = artifact.payload_symbol == output.name or artifact.dataset_variable == output.name
        variables = [item.name for item in getattr(artifact, "dataset_outputs", [])]
        if matches or output.name in variables:
            label = str(artifact.path_expression or artifact.sink_id)
            variable = artifact.dataset_variable or (output.name if output.name in variables else None)
            refs.append(f"{label}::{variable}" if variable else label)
    return refs


def _affected(project: Any, output: Any) -> AffectedOutput:
    return AffectedOutput(output.output_id, output.name, _root_for(project, output.output_id),
                          output.end_to_end_status, _artifact_refs(project, output))


def _candidate_spans(project: Any, output: Any, divergence_type: str, actual: Any) -> list[dict[str, Any]]:
    spans = []
    if isinstance(actual, dict):
        if divergence_type == DivergenceType.OPERATOR_MISMATCH.value and isinstance(actual.get("operator_span"), dict):
            raw = [actual["operator_span"]]
        else: raw = actual.get("source_spans") or ([actual["source_span"]] if actual.get("source_span") else [])
        spans.extend(item for item in raw if isinstance(item, dict))
    if divergence_type == DivergenceType.CONSTANT_MISMATCH.value:
        for symbol in project.project_graph.symbols:
            if symbol.kind == "CONSTANT" and symbol.canonical_name in output.dependencies and symbol.source_span:
                spans.append(deepcopy(symbol.source_span))
    spans.extend(deepcopy(item) for item in output.source_locations)
    unique = []
    for item in spans:
        if item not in unique: unique.append(item)
    return unique


def _span_contains(container: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    if container.get("file") != target.get("file"): return False
    c0, c1 = container.get("begin_line"), container.get("end_line", container.get("begin_line"))
    t0, t1 = target.get("begin_line"), target.get("end_line", target.get("begin_line"))
    if not all(isinstance(item, int) for item in (c0, c1, t0, t1)): return container == target
    if not (c0 <= t0 and t1 <= c1): return False
    c_begin = container.get("begin_column", container.get("begin_col")); c_end = container.get("end_column", container.get("end_col"))
    t_begin = target.get("begin_column", target.get("begin_col")); t_end = target.get("end_column", target.get("end_col"))
    if c0 == t0 and c1 == t1 and all(isinstance(item, int) for item in (c_begin, c_end, t_begin, t_end)):
        return c_begin <= t_begin and t_end <= c_end
    return True


def _localization(actual: Any, spans: list[dict[str, Any]]) -> tuple[str, str]:
    direct = []
    if isinstance(actual, dict):
        direct = ([actual["operator_span"]] if isinstance(actual.get("operator_span"), dict) else
                  actual.get("source_spans") or ([actual["source_span"]] if isinstance(actual.get("source_span"), dict) else []))
    direct = [item for item in direct if isinstance(item, dict)]
    if len(direct) == 1 and all(key in direct[0] for key in ("file", "begin_line", "end_line")) and (
            all(key in direct[0] for key in ("begin_column", "end_column")) or
            all(key in direct[0] for key in ("begin_col", "end_col"))):
        return DebugLocalizationLevel.EXACT_SOURCE_SPAN.value, "RECORDED_OPERATOR_OR_ARGUMENT_ORIGIN"
    if direct or len(spans) > 1:
        return DebugLocalizationLevel.SOURCE_SPAN_SET.value, "ORIGIN_SET_NO_SINGLE_SPAN_INVENTED"
    if spans:
        return DebugLocalizationLevel.SOURCE_FUNCTION.value, "FALLBACK_OUTPUT_OR_SYMBOL_SPAN"
    if isinstance(actual, dict):
        return DebugLocalizationLevel.CORRECT_SEMANTIC_NODE.value, "SEMANTIC_NODE_ONLY"
    return DebugLocalizationLevel.UNRESOLVED.value, "NO_RECORDED_ORIGIN"


def _source_symbol(project: Any, source: dict[str, Any] | None) -> str | None:
    if not source: return None
    for symbol in project.project_graph.symbols:
        span = symbol.source_span or {}
        if span.get("file") == source.get("file") and span.get("begin_line") == source.get("begin_line"):
            return symbol.canonical_name
    return None


def _component_magnitude(component: Mapping[str, Any]) -> float | None:
    bound = component.get("bound") or {}
    symmetric = bound.get("symmetric_bound")
    if isinstance(symmetric, dict): symmetric = symmetric.get("value")
    if isinstance(symmetric, (int, float)): return abs(float(symmetric))
    values = [bound.get("lower_bound"), bound.get("upper_bound")]
    numeric = [abs(float(item)) for item in values if isinstance(item, (int, float))]
    return max(numeric) if numeric else None


def _error_contributions(output: Any) -> list[ErrorContribution]:
    seen = set(); values = []
    for component in output.error_components or []:
        cause = str(component.get("semantic_cause_id") or component.get("origin_id") or component.get("component_id"))
        if cause in seen: continue
        seen.add(cause)
        values.append((component, _component_magnitude(component), cause))
    values.sort(key=lambda item: (item[1] is not None, item[1] or 0), reverse=True)
    return [ErrorContribution(str(item.get("component_id")), str(item.get("source")), magnitude, cause,
                              str(item.get("proof_status", "UNRESOLVED")), index + 1)
            for index, (item, magnitude, cause) in enumerate(values)]


def _amplification_points(output: Any, project: Any) -> list[ErrorAmplificationPoint]:
    result = []
    for path, node in _walk(output.formula):
        if node.get("op") != "Divide" or len(node.get("args", [])) != 2: continue
        denominator = node["args"][1]
        factor = None
        if denominator.get("op") == "Constant" and isinstance(denominator.get("value"), (int, float)):
            value = abs(float(denominator["value"])); factor = None if value == 0 else 1 / value
        source = (_candidate_spans(project, output, DivergenceType.ERROR_BOUND_VIOLATION.value, node) or [None])[0]
        result.append(ErrorAmplificationPoint("Divide", list(path), factor, source,
            "Division sensitivity can amplify upstream absolute error; denominator range evidence controls the factor."))
    return sorted(result, key=lambda item: (item.amplification_factor is not None, item.amplification_factor or 0), reverse=True)


def _confidence(kind: str, source: dict[str, Any] | None, *, mathematical: bool, runtime_only: bool = False,
                localization_level: str = DebugLocalizationLevel.UNRESOLVED.value) -> str:
    if kind == DivergenceType.FFI_BOUNDARY_UNRESOLVED.value:
        return RootCauseConfidence.BLOCKED_BY_UNRESOLVED_SEMANTICS.value
    if runtime_only: return RootCauseConfidence.POSSIBLE_ROOT_CAUSE.value
    if mathematical and source and localization_level in {DebugLocalizationLevel.EXACT_SOURCE_SPAN.value,
                                                           DebugLocalizationLevel.SOURCE_SPAN_SET.value}:
        return RootCauseConfidence.STRONG_ROOT_CAUSE_CANDIDATE.value
    return RootCauseConfidence.POSSIBLE_ROOT_CAUSE.value


def _invalidated(output: Any, kind: str, mathematical: bool) -> tuple[list[str], list[str], list[str]]:
    proofs = []; errors = []; ranges = []
    claim = output.end_to_end_claim or {}
    if mathematical:
        if output.lean_status == "LEAN_KERNEL_VERIFIED": proofs.append("LEAN_CLAIM_INVALIDATED_BY_DIVERGENCE")
        if claim.get("claim_id"): proofs.append(str(claim["claim_id"]))
        if output.range_status: ranges.append(str(output.range_status))
    if kind in {DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value,
                DivergenceType.APPROXIMATION_PARAMETER_MISMATCH.value}:
        errors.append("CERTIFIED_BOUND_INVALIDATED")
        proofs.append("APPROXIMATION_THEOREM_INVALIDATED")
    if kind == DivergenceType.ERROR_BOUND_VIOLATION.value: errors.append("TOTAL_TOLERANCE_NOT_PROVEN")
    return list(dict.fromkeys(proofs)), errors, ranges


def _trace(project: Any, output: Any, finding_id: str, source: dict[str, Any] | None) -> DebugTrace:
    symbol = _source_symbol(project, source)
    path = []
    if symbol: path.append({"kind": "SOURCE_SYMBOL", "id": symbol, "source_span": source})
    else: path.append({"kind": "SEMANTIC_NODE", "id": finding_id, "source_span": source})
    for dependency in output.dependencies:
        if dependency != symbol: path.append({"kind": "DEPENDENCY", "id": dependency})
    path.append({"kind": "OUTPUT", "id": output.output_id, "name": output.name})
    artifacts = _artifact_refs(project, output)
    path += [{"kind": "ARTIFACT_OUTPUT", "id": item} for item in artifacts]
    return DebugTrace(_id("debug-trace", [finding_id, output.output_id]), symbol or finding_id,
                      path, [output.output_id], artifacts)


def _reference_debug_project(project: Any) -> AuditDebugResult:
    """Localize minimal semantic divergences using an existing ProjectAuditResult."""
    raw: list[dict[str, Any]] = []
    comparable = 0
    for output in project.outputs:
        residual = output.residual or {}
        theory = residual.get("theory_expression") if isinstance(residual, dict) else None
        if isinstance(theory, dict) and isinstance(output.formula, dict):
            comparable += 1
            for item in _compare(theory, output.formula): raw.append({**item, "output": output})
        claim = output.end_to_end_claim or {}
        matrix = {item.get("layer"): item for item in claim.get("verification_matrix", [])}
        ffi = matrix.get("FFI", {})
        if ffi.get("status") == "UNRESOLVED":
            raw.append({"type": DivergenceType.FFI_BOUNDARY_UNRESOLVED.value,
                        "expected": {"representation_mapping": "RANGE_PRESERVING"},
                        "actual": deepcopy(claim.get("ffi_boundaries", [])), "path": ["ffi_boundaries"],
                        "role": "ffi", "mathematical": False, "boundary_inputs": [], "output": output})
        serialization = matrix.get("SERIALIZATION", {})
        if serialization.get("status") == "UNRESOLVED":
            raw.append({"type": DivergenceType.SERIALIZATION_DIVERGENCE.value,
                        "expected": {"serialization": "SERIALIZATION_VALUE_PRESERVING"},
                        "actual": deepcopy(claim.get("serialization_boundaries", [])),
                        "path": ["serialization_boundaries"], "role": "serialization",
                        "mathematical": False, "boundary_inputs": [], "output": output})
        if output.range_constraint_status == "OUTPUT_RANGE_CONSTRAINT_VIOLATED":
            raw.append({"type": DivergenceType.RANGE_VIOLATION.value,
                        "expected": deepcopy((output.interval_propagation or {}).get("output_range_constraint")),
                        "actual": deepcopy(output.true_value_enclosure), "path": ["true_value_enclosure"],
                        "role": "range", "mathematical": False, "boundary_inputs": [], "output": output})
        if claim.get("observed_result_status") == "OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE":
            raw.append({"type": DivergenceType.RANGE_VIOLATION.value,
                        "expected": deepcopy(output.true_value_enclosure), "actual": claim.get("observed_result"),
                        "path": ["observed_result"], "role": "runtime_range", "mathematical": False,
                        "runtime_only": True, "boundary_inputs": [], "output": output})
        if claim.get("tolerance_status") == "TOTAL_TOLERANCE_NOT_PROVEN":
            raw.append({"type": DivergenceType.ERROR_BOUND_VIOLATION.value,
                        "expected": {"tolerance_status": "TOTAL_TOLERANCE_PROVEN"},
                        "actual": deepcopy(output.total_error_bound), "path": ["total_error_bound"],
                        "role": "error", "mathematical": False, "boundary_inputs": [], "output": output})

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in raw:
        output = item["output"]
        spans = _candidate_spans(project, output, item["type"], item.get("actual"))
        source = spans[0] if spans else None
        key = _id("root-cause-key", [_root_for(project, output.output_id), item["type"], source,
                                      _semantic_signature(item.get("expected")), _semantic_signature(item.get("actual"))])
        item["source"] = source; item["source_spans"] = spans
        grouped.setdefault(key, []).append(item)

    findings = []; first = []; subgraphs = []; roots = []; traces = []
    for rank, values in enumerate(grouped.values(), 1):
        primary = values[0]; outputs = []
        for item in values:
            affected = _affected(project, item["output"])
            if affected.output_id not in {value.output_id for value in outputs}: outputs.append(affected)
        output = primary["output"]; kind = primary["type"]; source = primary.get("source")
        source_spans = deepcopy(primary.get("source_spans", []))
        localization_level, localization_confidence = _localization(primary.get("actual"), source_spans)
        mathematical = bool(primary.get("mathematical", True))
        divergence_id = _id("semantic-divergence", [kind, primary.get("expected"), primary.get("actual"), source])
        difference = {"type": kind, "path": primary.get("path", []), "role": primary.get("role")}
        divergence = SemanticDivergence(divergence_id, kind, deepcopy(primary.get("expected")),
            deepcopy(primary.get("actual")), list(primary.get("path", [])), deepcopy(source), difference, mathematical)
        subgraph = MinimalDivergentSubgraph(_id("minimal-divergent-subgraph", divergence_id),
            [deepcopy(primary.get("expected"))] if isinstance(primary.get("expected"), dict) else [],
            [deepcopy(primary.get("actual"))] if isinstance(primary.get("actual"), dict) else [],
            deepcopy(primary.get("boundary_inputs", [])), [item.output_id for item in outputs],
            deepcopy(primary.get("source_spans", [])), difference)
        subgraphs.append(subgraph)
        root_id = _root_for(project, output.output_id)
        first.append(FirstSemanticDivergence(divergence_id, root_id, [item.output_id for item in outputs],
            divergence, deepcopy(primary.get("boundary_inputs", [])), [item.output_id for item in outputs], subgraph.subgraph_id))
        trace = _trace(project, output, divergence_id, source)
        trace.output_ids = [item.output_id for item in outputs]
        trace.artifact_outputs = list(dict.fromkeys(value for item in outputs for value in item.artifact_outputs))
        traces.append(trace)
        confidence = _confidence(kind, source, mathematical=mathematical,
                                 runtime_only=bool(primary.get("runtime_only")),
                                 localization_level=localization_level)
        proofs, errors, ranges = _invalidated(output, kind, mathematical)
        invalidated = [*proofs, *errors, *ranges]
        finding_id = _id("debug-finding", [divergence_id, [item.output_id for item in outputs]])
        contributions = _error_contributions(output) if kind == DivergenceType.ERROR_BOUND_VIOLATION.value else []
        amplification = _amplification_points(output, project) if contributions else []
        residual = output.residual or {}
        trace_payload = residual.get("transformation_trace", {}) if isinstance(residual, dict) else {}
        rewrite_explanation = []
        if isinstance(trace_payload, dict):
            rewrite_explanation = deepcopy(trace_payload.get("applied_rules") or trace_payload.get("steps") or [])
        elif isinstance(trace_payload, list): rewrite_explanation = deepcopy(trace_payload)
        blocking_evidence = []
        if kind == DivergenceType.SERIALIZATION_DIVERGENCE.value:
            blocking_evidence.append({"reason": "MATHEMATICAL_PAYLOAD_AND_SERIALIZATION_ARE_SEPARATE_CLAIMS"})
        if kind in {DivergenceType.APPROXIMATION_FAMILY_MISMATCH.value,
                    DivergenceType.APPROXIMATION_PARAMETER_MISMATCH.value}:
            blocking_evidence.append({"reason": "NON_EXACT_RELATION_CANNOT_MERGE_EXACT_ECLASS"})
        blocking_evidence.extend(deepcopy(item) for item in project.diagnostics
                                 if any(token in str(item) for token in ("CONFLICT", "BLOCKED", "UNRESOLVED")))
        finding = DebugFinding(finding_id, kind, deepcopy(primary.get("expected")),
            deepcopy(primary.get("actual")), deepcopy(source), outputs, trace, confidence,
            kind, "semantic_debug." + kind.lower(),
            {"expected": deepcopy(primary.get("expected")), "actual": deepcopy(primary.get("actual")),
             "source_symbol": _source_symbol(project, source)}, invalidated, contributions, amplification)
        finding.source_spans = source_spans
        finding.localization_level = localization_level
        finding.localization_confidence = localization_confidence
        finding.blocking_evidence = blocking_evidence
        finding.rewrite_explanation = rewrite_explanation
        findings.append(finding)
        roots.append(RootCauseCandidate(finding_id, kind, confidence, finding.expected, finding.actual,
            source.get("file") if source else None, deepcopy(source), _source_symbol(project, source),
            deepcopy(primary.get("boundary_inputs", [])), outputs, proofs, errors, ranges, rank))

    affected_outputs = []
    for finding in findings:
        for output in finding.affected_outputs:
            if output.output_id not in {item.output_id for item in affected_outputs}: affected_outputs.append(output)
    blocked = any(item.confidence == RootCauseConfidence.BLOCKED_BY_UNRESOLVED_SEMANTICS.value for item in findings)
    if findings: status = DebugStatus.PARTIAL_SEMANTIC_LOCALIZATION.value if blocked else DebugStatus.SEMANTIC_DIVERGENCE_LOCALIZED.value
    elif comparable: status = DebugStatus.NO_SEMANTIC_DIVERGENCE_FOUND.value
    else: status = DebugStatus.SEMANTIC_DEBUG_BLOCKED.value
    root_results = {}
    for root in project.roots:
        root_findings = [item for item in findings if any(output.root_id == root.root_id for output in item.affected_outputs)]
        root_results[root.root_id] = ("DIVERGENCE_LOCALIZED" if root_findings else
                                      "NO_SEMANTIC_DIVERGENCE_FOUND" if any(
                                          isinstance((output.residual or {}).get("theory_expression"), dict)
                                          for output in root.outputs) else "DEBUG_BLOCKED")
    diagnostics = [{"diagnostic_code": item.diagnostic_code, "message_key": item.message_key,
                    "parameters": deepcopy(item.parameters)} for item in findings]
    result = AuditDebugResult(status, project.status, project.end_to_end_status, findings, first, subgraphs,
        roots, affected_outputs, traces,
        list(dict.fromkeys(value for item in findings for value in item.invalidated_claims)), root_results, diagnostics,
        project)
    result.localization_metrics = {"total": len(findings),
        "exact_span": sum(item.localization_level == DebugLocalizationLevel.EXACT_SOURCE_SPAN.value for item in findings),
        "span_set": sum(item.localization_level == DebugLocalizationLevel.SOURCE_SPAN_SET.value for item in findings),
        "semantic_node_or_better": sum(item.localization_level != DebugLocalizationLevel.UNRESOLVED.value for item in findings),
        "unresolved": sum(item.localization_level == DebugLocalizationLevel.UNRESOLVED.value for item in findings),
        "false_localization": 0,
        "false_localization_basis": "No exact ground-truth assertion made without recorded origin evidence"}
    return result


def _native_affected(value: Mapping[str, Any]) -> AffectedOutput:
    return AffectedOutput(str(value.get("output_id", "")), str(value.get("name", "")),
        str(value.get("root_id", "root:unknown")), value.get("end_to_end_status"),
        list(value.get("artifact_outputs", [])))


def _native_trace(value: Mapping[str, Any]) -> DebugTrace:
    return DebugTrace(str(value.get("trace_id", "")), str(value.get("root_cause_node", "")),
        list(value.get("dependency_path", [])), list(value.get("output_ids", [])),
        list(value.get("artifact_outputs", [])))


def _native_finding(value: Mapping[str, Any]) -> DebugFinding:
    trace = _native_trace(value.get("debug_trace", {}))
    finding = DebugFinding(str(value.get("finding_id", "")), str(value.get("type", "UNKNOWN_SEMANTIC_DIVERGENCE")),
        value.get("expected"), value.get("actual"), value.get("source"),
        [_native_affected(item) for item in value.get("affected_outputs", [])], trace,
        str(value.get("confidence", RootCauseConfidence.POSSIBLE_ROOT_CAUSE.value)),
        str(value.get("diagnostic_code", value.get("type", "UNKNOWN_SEMANTIC_DIVERGENCE"))),
        str(value.get("message_key", "semantic_debug.unknown")), dict(value.get("parameters", {})),
        list(value.get("invalidated_claims", [])),
        [ErrorContribution(str(item.get("component_id", "")), str(item.get("source", "")),
            item.get("magnitude"), item.get("semantic_cause_id"), str(item.get("proof_status", "UNRESOLVED")),
            int(item.get("rank", 0))) for item in value.get("error_contributions", [])],
        [ErrorAmplificationPoint(str(item.get("operation", "")), list(item.get("expression_path", [])),
            item.get("amplification_factor"), item.get("source"), str(item.get("explanation", "")))
            for item in value.get("amplification_points", [])])
    finding.source_spans = list(value.get("source_spans", []))
    finding.localization_level = str(value.get("localization_level", DebugLocalizationLevel.UNRESOLVED.value))
    finding.localization_confidence = str(value.get("localization_confidence", "FAIL_CLOSED"))
    finding.blocking_evidence = list(value.get("blocking_evidence", []))
    finding.rewrite_explanation = list(value.get("rewrite_explanation", []))
    return finding


def debug_project(project: Any) -> AuditDebugResult:
    """Thin projection of Rust-owned semantic localization and root-cause decisions."""
    raw = _execute_native_kernel({"schema_version": "1.0", "kernel": "E",
        "operation": "DEBUG_PROJECT", "project": project.to_dict()})["result"]
    findings = [_native_finding(item) for item in raw.get("findings", [])]
    subgraphs = [MinimalDivergentSubgraph(str(item.get("subgraph_id", "")),
        list(item.get("theory_nodes", [])), list(item.get("implementation_nodes", [])),
        list(item.get("boundary_inputs", [])), list(item.get("boundary_outputs", [])),
        list(item.get("source_spans", [])), dict(item.get("semantic_difference", {})))
        for item in raw.get("minimal_divergent_subgraphs", [])]
    divergences = []
    for item in raw.get("first_divergences", []):
        value = item.get("divergence", {})
        divergence = SemanticDivergence(str(value.get("divergence_id", "")), str(value.get("type", "")),
            value.get("expected"), value.get("actual"), list(value.get("expression_path", [])),
            value.get("source"), dict(value.get("semantic_difference", {})),
            bool(value.get("mathematical_layer", True)))
        divergences.append(FirstSemanticDivergence(str(item.get("divergence_id", "")),
            str(item.get("root_id", "root:unknown")), list(item.get("output_ids", [])), divergence,
            list(item.get("matching_upstream_region", [])), list(item.get("downstream_affected_region", [])),
            str(item.get("minimal_subgraph_id", ""))))
    roots = [RootCauseCandidate(str(item.get("finding_id", "")), str(item.get("divergence_type", "")),
        str(item.get("confidence", RootCauseConfidence.POSSIBLE_ROOT_CAUSE.value)), item.get("expected_semantics"),
        item.get("actual_semantics"), item.get("source_file"), item.get("source_span"), item.get("source_symbol"),
        list(item.get("upstream_context", [])), [_native_affected(value) for value in item.get("downstream_affected_outputs", [])],
        list(item.get("proofs_invalidated", [])), list(item.get("error_bounds_invalidated", [])),
        list(item.get("range_claims_invalidated", [])), int(item.get("rank", 0)))
        for item in raw.get("root_causes", [])]
    result = AuditDebugResult(str(raw.get("status", DebugStatus.SEMANTIC_DEBUG_BLOCKED.value)),
        str(raw.get("project_status", project.status)), raw.get("end_to_end_status"), findings, divergences,
        subgraphs, roots, [_native_affected(item) for item in raw.get("affected_outputs", [])],
        [_native_trace(item) for item in raw.get("debug_traces", [])], list(raw.get("invalidated_claims", [])),
        dict(raw.get("root_results", {})), list(raw.get("diagnostics", [])), project)
    result.localization_metrics = dict(raw.get("localization_metrics", {}))
    return result


def _input_ranges(project: Any, supplied: Mapping[str, Any] | None) -> dict[str, tuple[float, float]]:
    raw = supplied
    if raw is None:
        specification = project.provenance.get("range_specification") or {}
        raw = {item.get("name"): item for item in specification.get("ranges", [])}
    result = {}
    for name, value in (raw or {}).items():
        if isinstance(value, Mapping): lower, upper = value.get("lower"), value.get("upper")
        elif isinstance(value, (list, tuple)) and len(value) == 2: lower, upper = value
        else: continue
        if isinstance(lower, (int, float)) and isinstance(upper, (int, float)) and lower <= upper:
            result[str(name).rsplit(".", 1)[-1]] = (float(lower), float(upper))
    return result


def _interval(node: Any, ranges: Mapping[str, tuple[float, float]]) -> tuple[float, float] | None:
    if not isinstance(node, dict): return None
    op = node.get("op")
    if op == "Constant" and isinstance(node.get("value"), (int, float)):
        value = float(node["value"]); return value, value
    if op in {"FreeVariable", "BoundVariable"}: return ranges.get(_logical_name(node))
    args = [_interval(item, ranges) for item in node.get("args", [])]
    if op == "Negate" and args and args[0]: return -args[0][1], -args[0][0]
    if len(args) == 2 and all(item is not None for item in args):
        left, right = args[0], args[1]
        if op == "Add": return left[0] + right[0], left[1] + right[1]
        if op == "Subtract": return left[0] - right[1], left[1] - right[0]
        if op == "Multiply":
            values = [left[i] * right[j] for i in (0, 1) for j in (0, 1)]; return min(values), max(values)
        if op == "Divide" and not (right[0] <= 0 <= right[1]):
            values = [left[i] / right[j] for i in (0, 1) for j in (0, 1)]; return min(values), max(values)
    if op == "IfThenElse":
        yes, no = _interval(node.get("then"), ranges), _interval(node.get("else"), ranges)
        if yes and no: return min(yes[0], no[0]), max(yes[1], no[1])
    return None


def _evaluate(node: Any, inputs: Mapping[str, float]) -> float | None:
    if not isinstance(node, dict): return None
    op = node.get("op")
    if op == "Constant" and isinstance(node.get("value"), (int, float)): return float(node["value"])
    if op in {"FreeVariable", "BoundVariable"}: return inputs.get(_logical_name(node))
    values = [_evaluate(item, inputs) for item in node.get("args", [])]
    if op == "Negate" and values and values[0] is not None: return -values[0]
    if len(values) == 2 and all(item is not None for item in values):
        left, right = values
        if op == "Add": return left + right
        if op == "Subtract": return left - right
        if op == "Multiply": return left * right
        if op == "Divide" and right != 0: return left / right
        if op == "Power": return left ** right
    return None


def search_counterexamples(project: Any, debug: AuditDebugResult, *, ranges: Mapping[str, Any] | None = None,
                           max_depth: int = 6) -> CounterexampleSearchResult:
    """Narrow proven/maybe failure regions; concrete points remain numeric evidence."""
    initial = _input_ranges(project, ranges)
    mathematical = [item for item in debug.first_divergences if item.divergence.mathematical_layer]
    if not initial or not mathematical:
        return CounterexampleSearchResult("COUNTEREXAMPLE_SEARCH_INCONCLUSIVE", [], [], 0,
            diagnostics=[{"code": "NUMERIC_INPUT_RANGE_OR_MATHEMATICAL_DIVERGENCE_REQUIRED"}])
    regions = []; candidates = []; subdivisions = 0
    for divergence in mathematical:
        expected, actual = divergence.divergence.expected, divergence.divergence.actual
        queue = [(dict(initial), 0)]
        while queue:
            current, depth = queue.pop(0)
            left, right = _interval(expected, current), _interval(actual, current)
            if left is None or right is None: continue
            residual = (left[0] - right[1], left[1] - right[0])
            proven = residual[1] < 0 or residual[0] > 0
            if proven or depth >= max_depth:
                status = "FAILURE_REGION_PROVEN" if proven else "FAILURE_REGION_POSSIBLE"
                payload = {name: {"lower": value[0], "upper": value[1]} for name, value in current.items()}
                regions.append(FailureRegion(_id("failure-region", [divergence.divergence_id, payload]),
                    payload, status, "SYMBOLIC_INTERVAL" if proven else "INTERVAL_OVERLAP_INCONCLUSIVE",
                    [divergence.divergence_id]))
                midpoint = {name: (value[0] + value[1]) / 2 for name, value in current.items()}
                expected_value, actual_value = _evaluate(expected, midpoint), _evaluate(actual, midpoint)
                if expected_value is not None and actual_value is not None and expected_value != actual_value:
                    candidates.append(CounterexampleCandidate(_id("counterexample", [divergence.divergence_id, midpoint]),
                        midpoint, expected_value, actual_value, "COUNTEREXAMPLE_CANDIDATE_NUMERICALLY_CONFIRMED"))
                continue
            name = max(current, key=lambda key: current[key][1] - current[key][0])
            lower, upper = current[name]
            if lower == upper: continue
            middle = (lower + upper) / 2
            for interval in ((lower, middle), (middle, upper)):
                child = dict(current); child[name] = interval; queue.append((child, depth + 1)); subdivisions += 1
    unique_regions = {item.region_id: item for item in regions}
    unique_candidates = {item.candidate_id: item for item in candidates}
    status = "FAILURE_REGION_LOCALIZED" if any(item.status == "FAILURE_REGION_PROVEN" for item in unique_regions.values()) else "COUNTEREXAMPLE_SEARCH_INCONCLUSIVE"
    return CounterexampleSearchResult(status, list(unique_regions.values()), list(unique_candidates.values()), subdivisions)


class AuditDebugger:
    """Thin object wrapper; ProjectAuditResult.debug() is the primary entry."""

    def __init__(self, project: Any): self.project = project
    def run(self) -> AuditDebugResult: return debug_project(self.project)


def aggregate_localization_metrics(
        cases: Iterable[tuple[AuditDebugResult, Mapping[str, Mapping[str, Any]]]]) -> DebugLocalizationMetrics:
    total = DebugLocalizationMetrics()
    for debug, ground_truth in cases:
        item = debug.evaluate_localization(ground_truth)
        for field_name in vars(total): setattr(total, field_name, getattr(total, field_name) + getattr(item, field_name))
    return total
