"""Release assurance, audit bundles, semantic diffs, and human i18n."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .expression import render_expression


@dataclass
class MutationOutcome:
    mutation_id: str
    mutation_kind: str
    expected: str
    actual: str
    detected: bool
    false_acceptance: bool


@dataclass
class AssuranceMetrics:
    true_acceptance: int = 0
    true_rejection: int = 0
    false_acceptance: int = 0
    false_rejection: int = 0
    unresolved: int = 0


@dataclass
class AssuranceReport:
    mutations: list[MutationOutcome]
    metamorphic: list[dict[str, Any]]
    adversarial: list[dict[str, Any]]
    metrics: AssuranceMetrics
    status: str

    def to_dict(self) -> dict[str, Any]: return _serial(self)


@dataclass
class RealWorldValidationSummary:
    total_projects: int
    statuses: dict[str, int]
    by_language: dict[str, dict[str, int]]
    by_library: dict[str, int]
    by_algorithm_family: dict[str, int]
    by_project_size: dict[str, int]


@dataclass
class AuditDiff:
    changes: list[dict[str, Any]]
    status: str
    before_hash: str
    after_hash: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class AuditBundle:
    bundle_version: str
    path: str
    manifest: dict[str, Any]
    bundle_hash: str
    status: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


_TRANSLATIONS = {
    "en-US": {"title": "FormulaTracer Audit Certificate", "target": "Target", "theory": "Theory",
              "implementation": "Implementation", "inputs": "Inputs / Constants", "approximation": "Approximation",
              "error": "Error / Range", "result": "Result / Artifact", "verified": "Verified Claims",
              "unresolved": "Unresolved Assumptions", "debug": "Debug Summary", "overall": "Overall Status"},
    "ja-JP": {"title": "FormulaTracer 監査証明書", "target": "監査対象", "theory": "理論式",
              "implementation": "実装式", "inputs": "入力・定数", "approximation": "近似",
              "error": "誤差・範囲", "result": "結果・成果物", "verified": "検証済み主張",
              "unresolved": "未解決の仮定", "debug": "デバッグ要約", "overall": "総合状態"},
}


def _serial(value: Any) -> Any:
    if is_dataclass(value): return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict): return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, list): return [_serial(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return sha256(json.dumps(_serial(value), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _mutations(expression: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result = []
    swaps = {"Add": "Subtract", "Subtract": "Add", "Multiply": "Divide", "Divide": "Multiply"}
    def first(predicate, change):
        value = deepcopy(expression); found = False
        def visit(node):
            nonlocal found
            if not isinstance(node, dict) or found: return
            if predicate(node): change(node); found = True; return
            for item in node.values():
                if isinstance(item, dict): visit(item)
                elif isinstance(item, list):
                    for child in item: visit(child)
        visit(value); return value if found else None
    operator = first(lambda n: n.get("op") in swaps, lambda n: n.update(op=swaps[n["op"]]))
    if operator: result.append(("WRONG_OPERATOR", operator))
    constant = first(lambda n: n.get("op") == "Constant" and isinstance(n.get("value"), (int, float)),
                     lambda n: n.update(value=n["value"] + 1))
    if constant: result.append(("WRONG_CONSTANT", constant))
    index = first(lambda n: n.get("op") == "IndexedValue" and n.get("indices"),
                  lambda n: n["indices"].__setitem__(0, {"op": "Add", "args": [n["indices"][0], {"op": "Constant", "value": 1}]}))
    if index: result.append(("INDEX_PLUS_ONE", index))
    axis = first(lambda n: isinstance(n.get("axes"), int), lambda n: n.update(axes=1 - n["axes"] if n["axes"] in {0, 1} else 0))
    if axis: result.append(("AXIS_CHANGE", axis))
    def swap_branches(node):
        node["then"], node["else"] = node["else"], node["then"]
    branch = first(lambda n: n.get("op") == "IfThenElse", swap_branches)
    if branch: result.append(("BRANCH_FLIP", branch))
    dtype = deepcopy(expression); dtype["dtype"] = "float32"; result.append(("DTYPE_CHANGE", dtype))
    reduction = first(lambda n: n.get("reduction_order") is not None, lambda n: n.update(reduction_order="reorderable"))
    if reduction: result.append(("REDUCTION_ORDER_CHANGE", reduction))
    stencil = first(lambda n: n.get("family_id") is not None, lambda n: n.update(family_id="forward_difference_first_derivative"))
    if stencil: result.append(("WRONG_STENCIL", stencil))
    return result


def run_assurance_suite(expression: dict[str, Any]) -> AssuranceReport:
    from .semantic_debugger import _compare
    outcomes = []
    for kind, mutant in _mutations(expression):
        detected = bool(_compare(expression, mutant))
        outcomes.append(MutationOutcome("mutation:" + _digest([kind, mutant])[:12], kind,
            "REJECT", "REJECT" if detected else "ACCEPT", detected, not detected))
    alpha = deepcopy(expression)
    def rename(node):
        if isinstance(node, dict):
            if node.get("op") == "FreeVariable": node["name"] = "renamed_" + str(node["name"])
            for value in node.values(): rename(value)
        elif isinstance(node, list):
            for item in node: rename(item)
    rename(alpha)
    # These are registered obligations, not executed evidence.  Never inflate
    # true-acceptance metrics merely because a corpus entry exists.
    metamorphic = [{"kind": "ALPHA_RENAME", "status": "CORPUS_REGISTERED_UNRESOLVED"},
                   {"kind": "TEMPORARY_VARIABLE_INTRODUCTION", "status": "CORPUS_REGISTERED_UNRESOLVED"},
                   {"kind": "PYTHON_RUST_CPP", "status": "COVERED_BY_SEPARATE_ROUND_TRIP_SUITE"}]
    adversarial_kinds = ["WRONG_AXIS", "BROADCAST_MISTAKE", "OFF_BY_ONE", "WRONG_DENOMINATOR", "WRONG_UNIT",
                         "NAN_MASKING_MISTAKE", "WRONG_DTYPE", "PARALLEL_REDUCTION_ISSUE",
                         "WRONG_INTERPOLATION", "WRONG_DERIVATIVE_STENCIL"]
    adversarial = [{"case": item, "expected": "REJECT_OR_UNRESOLVED", "status": "CORPUS_REGISTERED"} for item in adversarial_kinds]
    unresolved = sum(item["status"].endswith("UNRESOLVED") for item in metamorphic) + len(adversarial)
    metrics = AssuranceMetrics(true_acceptance=0, true_rejection=sum(item.detected for item in outcomes),
                               false_acceptance=sum(item.false_acceptance for item in outcomes),
                               unresolved=unresolved)
    status = ("ASSURANCE_GATE_PASSED_WITH_UNRESOLVED" if metrics.false_acceptance == 0
              else "CRITICAL_FALSE_ACCEPTANCE_DETECTED")
    return AssuranceReport(outcomes, metamorphic, adversarial, metrics, status)


def summarize_real_world(results: Iterable[Any]) -> RealWorldValidationSummary:
    statuses = {}; languages = {}; libraries = {}; algorithms = {}; sizes = {}
    values = list(results)
    for result in values:
        status = str(result.end_to_end_status or result.status); statuses[status] = statuses.get(status, 0) + 1
        language = str(result.project_graph.metadata.get("language", result.modules[0].language if result.modules and hasattr(result.modules[0], "language") else "python"))
        language_counts = languages.setdefault(language, {}); language_counts[status] = language_counts.get(status, 0) + 1
        for library in result.project_graph.external_modules: libraries[library] = libraries.get(library, 0) + 1
        for output in result.outputs:
            op = str((output.formula or {}).get("op", "UNKNOWN")); algorithms[op] = algorithms.get(op, 0) + 1
        module_count = len(result.modules); bucket = "small" if module_count <= 3 else "medium" if module_count <= 20 else "large"
        sizes[bucket] = sizes.get(bucket, 0) + 1
    return RealWorldValidationSummary(len(values), statuses, languages, libraries, algorithms, sizes)


def audit_diff(before: Any, after: Any) -> AuditDiff:
    left, right = before.to_dict(), after.to_dict(); changes = []
    left_provenance, right_provenance = left.get("provenance", {}), right.get("provenance", {})
    checks = [("FORMULA_CHANGED", [item.get("formula") for item in left["outputs"]], [item.get("formula") for item in right["outputs"]]),
              ("THEORY_CHANGED", [item.get("theory") for item in left["outputs"]], [item.get("theory") for item in right["outputs"]]),
              ("IMPLEMENTATION_SEMANTICS_CHANGED", [item.get("implementation") for item in left["outputs"]], [item.get("implementation") for item in right["outputs"]]),
              ("CONSTANT_CHANGED", left.get("provenance", {}).get("constant_graph"), right.get("provenance", {}).get("constant_graph")),
              ("PARAMETER_CHANGED", left_provenance.get("configuration_resolution"), right_provenance.get("configuration_resolution")),
              ("DEPENDENCY_CHANGED", left.get("dependencies"), right.get("dependencies")),
              ("LIBRARY_PROVIDER_CHANGED", left_provenance.get("selected_providers"), right_provenance.get("selected_providers")),
              ("APPROXIMATION_CHANGED", [item.get("residual") for item in left["outputs"]], [item.get("residual") for item in right["outputs"]]),
              ("TRANSFORMATION_CHANGED", [(item.get("residual") or {}).get("transformation_trace") for item in left["outputs"]], [(item.get("residual") or {}).get("transformation_trace") for item in right["outputs"]]),
              ("ERROR_BOUND_CHANGED", [item.get("total_error_bound") for item in left["outputs"]], [item.get("total_error_bound") for item in right["outputs"]]),
              ("RANGE_CHANGED", [item.get("true_value_enclosure") for item in left["outputs"]], [item.get("true_value_enclosure") for item in right["outputs"]]),
              ("ASSUMPTION_CHANGED", [item.get("assumptions") for item in left.get("end_to_end_claims", [])], [item.get("assumptions") for item in right.get("end_to_end_claims", [])]),
              ("INPUT_SCHEMA_CHANGED", [item.get("schema") for item in left_provenance.get("input_artifacts", [])], [item.get("schema") for item in right_provenance.get("input_artifacts", [])]),
              ("OUTPUT_SCHEMA_CHANGED", left_provenance.get("output_schemas"), right_provenance.get("output_schemas")),
              ("PROOF_STATUS_CHANGED", left.get("proofs"), right.get("proofs")),
              ("LIBRARY_CONTRACT_CHANGED", left.get("provenance", {}).get("library_contract_registry_hash"), right.get("provenance", {}).get("library_contract_registry_hash")),
              ("ARTIFACT_CHANGED", left.get("artifacts"), right.get("artifacts"))]
    for kind, old, new in checks:
        if old != new: changes.append({"kind": kind, "before_hash": _digest(old), "after_hash": _digest(new)})
    return AuditDiff(changes, "AUDIT_SEMANTICS_CHANGED" if changes else "AUDIT_UNCHANGED", _digest(left), _digest(right))


def _formula(output: Any) -> str:
    try:
        expression = deepcopy(output.formula)
        def localize(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("op") in {"FreeVariable", "BoundVariable"} and node.get("name"):
                    node["name"] = str(node["name"]).replace("::", ".").rsplit(".", 1)[-1]
                for item in node.values(): localize(item)
            elif isinstance(node, list):
                for item in node: localize(item)
        localize(expression)
        wrapper = {"outputs": [{"target": {"op": "FreeVariable", "name": output.name}, "expression": expression}]}
        return render_expression(wrapper, "latex").strip()
    except Exception: return r"\text{unavailable}"


def localized_certificate(result: Any, *, locale: str = "en-US", debug: Any = None) -> str:
    if locale not in _TRANSLATIONS: raise ValueError("UNSUPPORTED_LOCALE")
    text = _TRANSLATIONS[locale]; japanese = locale == "ja-JP"
    def machine(value: Any) -> str: return str(value).replace("_", r"\_")
    document = r"\documentclass{ltjsarticle}" if japanese else r"\documentclass{article}"
    lines = [document, r"\usepackage[margin=0.75in]{geometry}", r"\begin{document}",
             rf"\section*{{{text['title']}}}", rf"\subsection*{{{text['target']}}}",
             rf"\texttt{{{machine(result.status)}}}"]
    for output in result.outputs:
        lines += [rf"\subsection*{{{text['theory']}}}", rf"\texttt{{{machine(output.name)}}}",
                  rf"\subsection*{{{text['implementation']}}}", r"\[" + _formula(output) + r"\]",
                  rf"\subsection*{{{text['error']}}}",
                  rf"\texttt{{{machine(output.range_status)}}}",
                  rf"\subsection*{{{text['result']}}}",
                  rf"\texttt{{{machine(output.end_to_end_status)}}}"]
    lines += [rf"\subsection*{{{text['debug']}}}",
              rf"\texttt{{{machine(debug.status if debug else 'NOT_REQUESTED')}}}",
              r"\subsection*{Research Provenance}",
              rf"Source commit: \texttt{{{machine((result.provenance.get('git') or {}).get('commit_sha') or 'UNVERIFIED')}}}\\",
              rf"Input artifacts: {len(result.provenance.get('input_artifacts', []))}\\",
              rf"Configuration parameters: {len(result.provenance.get('configuration_resolution', []))}\\",
              rf"Environment evidence: \texttt{{{machine((result.provenance.get('environment') or {}).get('evidence_level') or 'NOT_CAPTURED')}}}\\",
              rf"Output artifacts: {len(result.artifacts)}\\",
              rf"\subsection*{{{text['overall']}}}",
              rf"\texttt{{{machine(result.end_to_end_status)}}}", r"\end{document}", ""]
    return "\n".join(lines)


def create_audit_bundle(result: Any, path: str | Path, *, locale: str = "en-US", debug: Any = None) -> AuditBundle:
    root = Path(path); root.mkdir(parents=True, exist_ok=True)
    debug = debug or result.debug()
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        native_bundle = context.execute_kernel({"schema_version": "1.0", "kernel": "F",
            "operation": "PROJECT_AUDIT_BUNDLE", "project": result.to_dict(),
            "debugger": debug.to_dict(), "generation_decisions": result.provenance.get("generation_decisions", []),
            "structural_normalization": result.provenance.get("structural_normalization", {}),
            "structural_isomorphism": result.provenance.get("structural_isomorphism", {})})["result"]
    files = {
        "native-audit-bundle.json": json.dumps(native_bundle, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "certificate.json": result.to_json(), "certificate.tex": localized_certificate(result, locale=locale, debug=debug),
        "project-dependency-graph.json": json.dumps(result.project_graph.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "implementation-ir.json": json.dumps([output.implementation for output in result.outputs], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "mathematical-ir.json": json.dumps([output.formula for output in result.outputs], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "theory.json": json.dumps([output.theory for output in result.outputs], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "transformation-trace.json": json.dumps([(output.residual or {}).get("transformation_trace", {}) for output in result.outputs], indent=2, sort_keys=True) + "\n",
        "library-contracts.json": json.dumps({"registry_hash": result.provenance.get("library_contract_registry_hash")}, indent=2) + "\n",
        "assumptions.json": json.dumps([claim.get("assumptions", []) for claim in result.end_to_end_claims], indent=2, ensure_ascii=False) + "\n",
        "error-range.json": json.dumps([{"error": output.total_error_bound, "range": output.true_value_enclosure} for output in result.outputs], indent=2, ensure_ascii=False) + "\n",
        "lean-proofs.json": json.dumps(result.proofs, indent=2, ensure_ascii=False) + "\n",
        "debug-findings.json": debug.to_json(), "end-to-end-claims.json": json.dumps(result.end_to_end_claims, indent=2, ensure_ascii=False) + "\n",
        "source-provenance.json": json.dumps({"git": result.provenance.get("git"),
            "source_hashes": result.provenance.get("used_source_hashes", {})}, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "environment-provenance.json": json.dumps(result.provenance.get("environment", {}), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "configuration-provenance.json": json.dumps(result.provenance.get("configuration_resolution", []), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "data-lineage.json": json.dumps(result.provenance.get("data_lineage", {}), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "schema-snapshots.json": json.dumps({"inputs": result.provenance.get("input_artifacts", []),
            "outputs": result.provenance.get("output_schemas", [])}, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "research-provenance-graph.json": json.dumps(result.provenance.get("research_provenance_graph", {}), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "semantic-diff.json": json.dumps({"status": "BASELINE_NOT_SUPPLIED", "changes": []}, indent=2) + "\n",
    }
    for name, content in files.items(): (root / name).write_text(content, encoding="utf-8")
    hashes = {name: sha256((root / name).read_bytes()).hexdigest() for name in sorted(files)}
    bundle_hash = _digest(hashes)
    manifest = {"bundle_version": "1.0", "bundle_hash": bundle_hash, "locale": locale,
                "files": [{"path": name, "sha256": digest} for name, digest in hashes.items()],
                "source_hashes": result.provenance.get("used_source_hashes", {}), "status": "AUDIT_BUNDLE_COMPLETE"}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return AuditBundle("1.0", str(root), manifest, bundle_hash, "AUDIT_BUNDLE_COMPLETE")


def verify_audit_bundle(path: str | Path) -> dict[str, Any]:
    """Fail closed when any manifest entry is absent or content-hash mismatched."""
    root = Path(path); manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return {"status": "AUDIT_BUNDLE_INVALID", "diagnostics": ["MANIFEST_MISSING"], "verified": False}
    try: manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "AUDIT_BUNDLE_INVALID", "diagnostics": ["MANIFEST_UNREADABLE"], "verified": False}
    diagnostics = []; hashes = {}
    for item in manifest.get("files", []):
        relative = item.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            diagnostics.append(f"UNSAFE_MANIFEST_PATH:{relative}"); continue
        target = root / relative
        if not target.is_file(): diagnostics.append(f"BUNDLE_FILE_MISSING:{relative}"); continue
        actual = sha256(target.read_bytes()).hexdigest(); hashes[relative] = actual
        if actual != item.get("sha256"): diagnostics.append(f"BUNDLE_HASH_MISMATCH:{relative}")
    calculated = _digest({name: hashes[name] for name in sorted(hashes)})
    if calculated != manifest.get("bundle_hash"): diagnostics.append("BUNDLE_MANIFEST_HASH_MISMATCH")
    return {"status": "AUDIT_BUNDLE_VERIFIED" if not diagnostics else "AUDIT_BUNDLE_INVALID",
            "diagnostics": diagnostics, "verified": not diagnostics, "bundle_hash": calculated}
