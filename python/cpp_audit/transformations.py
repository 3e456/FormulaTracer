"""Apply explicitly allowed TransformationSets to Mathematical Expression IR."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from .core import AuditError
from .approximation_families import approximation_metadata
from .expression import load_transformation_rule, load_transformation_set, normalize_exact, select_transformation
from .python_audit import compare_symbolic


class RuleKind(str, Enum):
    EXACT = "EXACT"
    EXACT_UNDER_ASSUMPTIONS = "EXACT_UNDER_ASSUMPTIONS"
    ALGEBRAIC_EQUIVALENCE = "ALGEBRAIC_EQUIVALENCE"
    IDENTITY_UNDER_ASSUMPTIONS = "IDENTITY_UNDER_ASSUMPTIONS"
    TRANSFORMATION = "TRANSFORMATION"
    APPROXIMATION = "APPROXIMATION"
    DISCRETIZATION = "DISCRETIZATION"
    TRUNCATION = "TRUNCATION"
    NUMERICALLY_NON_EQUIVALENT = "NUMERICALLY_NON_EQUIVALENT"


class ComparisonRelation(str, Enum):
    EXACT_EQUAL = "EXACT_EQUAL"
    EQUIVALENT_UNDER_ASSUMPTIONS = "EQUIVALENT_UNDER_ASSUMPTIONS"
    DISCRETIZATION_OF = "DISCRETIZATION_OF"
    APPROXIMATION_OF = "APPROXIMATION_OF"
    REFINEMENT_OF = "REFINEMENT_OF"
    PARTIAL_IMPLEMENTATION_OF = "PARTIAL_IMPLEMENTATION_OF"
    INCONSISTENT_WITH = "INCONSISTENT_WITH"
    NOT_COMPARABLE = "NOT_COMPARABLE"


@dataclass(frozen=True)
class TransformationObligation:
    obligation_id: str
    statement: str
    kind: str
    status: str
    evidence: str | None = None


@dataclass(frozen=True)
class TransformationApplication:
    rule_id: str
    source_expression_id: str
    target_expression_id: str
    parameters: dict[str, Any]
    rule_kind: str
    assumptions: list[str]
    hard_constraints: list[dict[str, Any]]
    discharged_obligations: list[TransformationObligation]
    remaining_obligations: list[TransformationObligation]
    reference: dict[str, Any]
    authorization_status: str
    status: str


@dataclass
class TransformationTrace:
    source_expression_id: str
    target_expression_id: str
    applications: list[TransformationApplication] = field(default_factory=list)


@dataclass
class TransformationResult:
    status: str
    allowed_transformation_sets: list[dict[str, Any]]
    transformation_trace: TransformationTrace
    transformed_theory: dict[str, Any]
    applied_rules: list[dict[str, Any]]
    rejected_rules: list[dict[str, Any]]
    remaining_obligations: list[dict[str, Any]]
    comparison_relation: str
    comparison: dict[str, Any] | None
    residual_candidate: dict[str, Any] | None
    selection: dict[str, Any] | None
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "allowed_transformation_sets": self.allowed_transformation_sets,
                "transformation_trace": {"source_expression_id": self.transformation_trace.source_expression_id,
                    "target_expression_id": self.transformation_trace.target_expression_id,
                    "applications": [asdict(item) for item in self.transformation_trace.applications]},
                "transformed_theory": deepcopy(self.transformed_theory),
                "applied_rules": deepcopy(self.applied_rules), "rejected_rules": deepcopy(self.rejected_rules),
                "remaining_obligations": deepcopy(self.remaining_obligations),
                "comparison_relation": self.comparison_relation, "comparison": deepcopy(self.comparison),
                "residual_candidate": deepcopy(self.residual_candidate), "selection": deepcopy(self.selection),
                "diagnostics": deepcopy(self.diagnostics)}


@dataclass(frozen=True)
class RewriteRuleDescriptor:
    rule_id: str
    relation_kind: str
    preconditions: tuple[str, ...] = ()
    domain_constraints: tuple[str, ...] = ()
    type_constraints: tuple[str, ...] = ()
    shape_constraints: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    cost: int = 1
    priority: int = 100
    evidence: str | None = None
    inverse_rule: str | None = None
    motifs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RewriteState:
    expression: dict[str, Any]
    applied_rule: str | None
    assumptions: tuple[str, ...]
    cost: int
    depth: int
    provenance: tuple[str, ...]


@dataclass
class BoundedRewriteResult:
    status: str
    left_state: RewriteState | None
    right_state: RewriteState | None
    visited_states: int
    diagnostics: list[str] = field(default_factory=list)


def _native_transform(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "B",
            "operation": "LEGACY_TRANSFORMATIONS", "action": action, **payload})["result"]


def _rewrite_state(value: dict[str, Any] | None) -> RewriteState | None:
    return None if value is None else RewriteState(value["expression"], value.get("applied_rule"),
        tuple(value.get("assumptions", [])), value["cost"], value["depth"], tuple(value.get("provenance", [])))


def load_rewrite_catalog(path: str | Path | None = None) -> list[RewriteRuleDescriptor]:
    """Load the broad registry.  Loading does not authorize a rule."""
    import yaml
    target = Path(path) if path else Path(__file__).resolve().parents[2] / "registry" / "transformations" / "rewrite_catalog.yaml"
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return [RewriteRuleDescriptor(
        rule_id=item["rule_id"], relation_kind=item["relation_kind"],
        preconditions=tuple(item.get("preconditions", [])), domain_constraints=tuple(item.get("domain_constraints", [])),
        type_constraints=tuple(item.get("type_constraints", [])), shape_constraints=tuple(item.get("shape_constraints", [])),
        assumptions=tuple(item.get("assumptions", [])), cost=int(item.get("cost", 1)),
        priority=int(item.get("priority", 100)), evidence=item.get("evidence"), inverse_rule=item.get("inverse_rule"),
        motifs=tuple(item.get("motifs", []))) for item in raw.get("rules", [])]


def _rewrite_once(node: Any, rule_id: str) -> list[Any]:
    """Thin native wrapper for catalogued exact identities."""
    return _native_transform("REWRITE_ONCE", node=node, rule_id=rule_id)


def _mentions_bound(node: Any, name: str) -> bool:
    if isinstance(node, list): return any(_mentions_bound(item, name) for item in node)
    return isinstance(node, dict) and ((node.get("op") == "BoundVariable" and node.get("name") == name) or
                                       any(_mentions_bound(item, name) for item in node.values()))


def bounded_rewrite_search(left: dict[str, Any], right: dict[str, Any], *,
                           authorized_rule_ids: Iterable[str], assumptions: Iterable[str] = (),
                           relevant_motifs: Iterable[str] = (), max_depth: int = 4,
                           state_budget: int = 30) -> BoundedRewriteResult:
    value = _native_transform("BOUNDED_REWRITE", left=left, right=right,
        authorized_rule_ids=list(authorized_rule_ids), assumptions=list(assumptions),
        relevant_motifs=list(relevant_motifs), max_depth=max_depth, state_budget=state_budget,
        catalog=[asdict(rule) for rule in load_rewrite_catalog()])
    return BoundedRewriteResult(value["status"], _rewrite_state(value.get("left_state")),
                                _rewrite_state(value.get("right_state")), value["visited_states"], value["diagnostics"])


def _id(prefix: str, value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(text.encode()).hexdigest()[:16]}"


def _expression_id(value: dict[str, Any]) -> str:
    return str(value.get("expression_id") or _id("expression", value.get("outputs", value)))


def _root(ir: dict[str, Any]) -> dict[str, Any]:
    if not ir.get("outputs"): raise AuditError("TRANSFORMATION_EXPRESSION_HAS_NO_OUTPUT")
    return ir["outputs"][0]["expression"]


def _contains_op(value: Any, op: str) -> bool:
    if isinstance(value, list): return any(_contains_op(item, op) for item in value)
    return isinstance(value, dict) and (value.get("op") == op or any(_contains_op(item, op) for item in value.values()))


def _contains_derivative_order(value: Any, order: Any) -> bool:
    if isinstance(value, list): return any(_contains_derivative_order(item, order) for item in value)
    return isinstance(value, dict) and ((value.get("op") == "Derivative" and value.get("order") == order) or
                                        any(_contains_derivative_order(item, order) for item in value.values()))


def _find_pattern_matches(pattern: dict[str, Any], value: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    values = _native_transform("FIND_MATCHES", pattern=pattern, value=value)
    return [(tuple([*path, *item["path"]]), item["bindings"]) for item in values]


def _replace_path(value: Any, path: tuple[Any, ...], replacement: Any) -> Any:
    return _native_transform("REPLACE_PATH", value=value, path=list(path), replacement=replacement)


def _pattern_matches(pattern: Any, value: Any, bindings: dict[str, Any] | None = None) -> bool:
    result = _native_transform("PATTERN_MATCH", pattern=pattern, value=value)
    if bindings is not None: bindings.update(result["bindings"])
    return bool(result["match"])


def _template(value: Any, bindings: dict[str, Any] | None = None) -> Any:
    return _native_transform("TEMPLATE", value=value, bindings=bindings or {})


def _with_expression(ir: dict[str, Any], expression: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(ir); result["outputs"][0]["expression"] = expression
    result["expression_id"] = _id("expression", result["outputs"])
    return result


def _rename_bound(value: Any, old: str, new: str) -> Any:
    if isinstance(value, list): return [_rename_bound(item, old, new) for item in value]
    if not isinstance(value, dict): return value
    result = {key: _rename_bound(child, old, new) for key, child in value.items()}
    if result.get("op") == "BoundVariable" and result.get("name") == old: result["name"] = new
    return result


def _apply_exact_node(value: Any, rule_id: str, depth: int = 0) -> Any:
    if isinstance(value, list): return [_apply_exact_node(item, rule_id, depth) for item in value]
    if not isinstance(value, dict): return value
    current = deepcopy(value)
    if rule_id == "alpha_rename" and current.get("op") in {"FiniteSum", "TransformReduce", "FoldLeft", "Map", "Scan"} and current.get("bound_index"):
        old, new = str(current["bound_index"]), f"_i{depth}"
        current = _rename_bound(current, old, new); current["bound_index"] = new; depth += 1
    current = {key: _apply_exact_node(child, rule_id, depth) for key, child in current.items()
               if key not in {"original_index", "source_node_ids", "source_spans"}}
    if rule_id == "finite_sum_normalization" and current.get("op") == "TransformReduce" and current.get("reduction") == "Add":
        finite = {"op": "FiniteSum", "bound_index": current["bound_index"], "index_domain": current["index_domain"],
                  "body": current["transform"], "reduction_order": current.get("reduction_order", "left_to_right")}
        initial = current.get("initial_value")
        return finite if initial in [{"op": "Constant", "value": 0}, {"op": "Constant", "value": 0.0}] else {"op": "Add", "args": [initial, finite]}
    if rule_id == "neutral_element_elimination" and current.get("op") in {"Add", "Multiply"}:
        identity = 0 if current["op"] == "Add" else 1
        args = [arg for arg in current.get("args", []) if arg not in [{"op": "Constant", "value": identity}, {"op": "Constant", "value": float(identity)}]]
        return args[0] if len(args) == 1 else {**current, "args": args}
    if rule_id == "simple_commutative_normalization" and current.get("op") in {"Add", "Multiply"}:
        current["args"] = sorted(current.get("args", []), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return current


def _apply_exact_rule(expression: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return _native_transform("APPLY_EXACT", expression=expression, rule_id=rule_id)


def _obligations(rule: dict[str, Any], assumptions: set[str]) -> tuple[list[TransformationObligation], list[TransformationObligation]]:
    discharged, remaining = [], []
    for index, statement in enumerate(rule.get("conditions", [])):
        exact = str(statement) in assumptions
        item = TransformationObligation(_id("obligation", [rule["id"], index, statement]), str(statement),
            "RULE_ASSUMPTION", "DISCHARGED" if exact else "REMAINING", "user supplied assumption" if exact else None)
        (discharged if exact else remaining).append(item)
    return discharged, remaining


def _hard_constraints(rule: dict[str, Any], transformation_set: dict[str, Any], theory: dict[str, Any],
                      context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    value = _native_transform("HARD_CONSTRAINTS", rule=rule, transformation_set=transformation_set,
                              theory=theory, context=context)
    return value["checks"], value["failures"]


def _application(rule: dict[str, Any], source: dict[str, Any], target: dict[str, Any], checks: list[dict[str, Any]],
                 assumptions: set[str], provenance: dict[str, Any]) -> TransformationApplication:
    registry_path = Path(__file__).resolve().parents[2] / "registry" / "approximation_families.yaml"
    family = approximation_metadata(rule, registry_path)
    enriched = {**rule, "approximation_family": family} if family else rule
    value = _native_transform("APPLICATION", rule=enriched, source=source, target=target, checks=checks,
                              assumptions=sorted(assumptions), provenance=provenance)
    discharged = [TransformationObligation(**item) for item in value.pop("discharged_obligations")]
    remaining = [TransformationObligation(**item) for item in value.pop("remaining_obligations")]
    return TransformationApplication(**value, discharged_obligations=discharged, remaining_obligations=remaining)


def _load_rules(root: Path, ids: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rules, rejected = [], []
    builtins = {
        "alpha_rename": {"id": "alpha_rename", "kind": "exact", "source_pattern": {}, "target_template": {}},
        "finite_sum_normalization": {"id": "finite_sum_normalization", "kind": "exact", "source_pattern": {}, "target_template": {}},
        "neutral_element_elimination": {"id": "neutral_element_elimination", "kind": "exact", "source_pattern": {}, "target_template": {}},
        "simple_commutative_normalization": {"id": "simple_commutative_normalization", "kind": "exact", "source_pattern": {}, "target_template": {}},
        "inline_temporary": {"id": "inline_temporary", "kind": "exact", "source_pattern": {}, "target_template": {}},
        "piecewise_normalization": {"id": "piecewise_normalization", "kind": "exact", "source_pattern": {}, "target_template": {}},
    }
    for rule_id in ids:
        path = root / f"{rule_id}.yaml"
        if path.is_file(): rules.append(load_transformation_rule(path))
        elif rule_id in builtins: rules.append(deepcopy(builtins[rule_id]))
        else: rejected.append({"rule_id": rule_id, "status": "RULE_DEFINITION_NOT_FOUND"})
    return rules, rejected


def apply_transformation_set(theory: dict[str, Any], implementation: dict[str, Any],
                             transformation_set: dict[str, Any] | str | Path, *,
                             rules_root: str | Path = "registry/transformations/rules",
                             requested_rule_ids: Iterable[str] | None = None,
                             assumptions: Iterable[str] = (), context: dict[str, Any] | None = None,
                             selection_profile: str = "minimum_cost") -> TransformationResult:
    item = load_transformation_set(transformation_set) if isinstance(transformation_set, (str, Path)) else deepcopy(transformation_set)
    context, assumption_set = context or {}, set(assumptions)
    allowed_exact, allowed_approx = set(item.get("exact_rules", [])), set(item.get("approximation_rules", []))
    allowed = allowed_exact | allowed_approx
    requested = list(requested_rule_ids) if requested_rule_ids is not None else list(allowed)
    authorized = allowed if requested_rule_ids is None else allowed & set(requested)
    rules, rejected = _load_rules(Path(rules_root), requested)
    for rule_id in requested:
        if rule_id not in allowed:
            rejected.append({"rule_id": rule_id, "status": "RULE_NOT_ALLOWED", "reason": "not present in selected TransformationSet"})
    rules = [rule for rule in rules if rule["id"] in allowed]
    source_id = _expression_id(theory)
    applications: list[TransformationApplication] = []
    diagnostics: list[dict[str, Any]] = []

    theory_normal, implementation_normal = normalize_exact(theory), normalize_exact(implementation)
    exact_equal = theory_normal["canonical_expression"] == implementation_normal["canonical_expression"]
    symbolic = compare_symbolic(implementation, theory)
    raw_symbolic_match = bool(symbolic.get("match"))
    canonical_symbolic = compare_symbolic(implementation_normal["canonical_expression"], theory_normal["canonical_expression"])
    if not symbolic.get("match") and canonical_symbolic.get("match"):
        symbolic = canonical_symbolic
    trace_ids = [entry["rule_id"] for entry in theory_normal["rewrite_trace"]]
    if symbolic.get("match") and symbolic.get("mapping"):
        if any(left != right for group in symbolic["mapping"].values() for left, right in group.items()): trace_ids.append("alpha_rename")
    if raw_symbolic_match and not exact_equal and _root(theory).get("op") in {"Add", "Multiply"}:
        trace_ids.append("simple_commutative_normalization")
    trace_ids = list(dict.fromkeys(trace_ids))
    forbidden_exact = [rule_id for rule_id in trace_ids if rule_id not in allowed_exact or rule_id not in authorized]
    if forbidden_exact:
        rejected.extend({"rule_id": rule_id, "status": "RULE_NOT_ALLOWED", "reason": "implicit exact normalization outside selected set"} for rule_id in forbidden_exact)
        diagnostics.append({"code": "TRANSFORMATION_NOT_ALLOWED", "rules": forbidden_exact})
    elif exact_equal or symbolic.get("match"):
        transformed = deepcopy(theory)
        current = theory
        for rule_id in trace_ids:
            rule = next((value for value in rules if value["id"] == rule_id), {"id": rule_id, "kind": "exact"})
            next_expression = _apply_exact_rule(current, rule_id)
            application = _application(rule, current, next_expression, [], assumption_set,
                {"transformation_set": item["id"], "version": item["version"], "source": item.get("provenance")})
            applications.append(application); current = next_expression
        transformed = current
        final = _native_transform("FINALIZE", mode="EXACT", has_applications=bool(applications))
        relation = final["relation"]
        trace = TransformationTrace(source_id, _expression_id(transformed), applications)
        return TransformationResult(final["status"],
            [{"id": item["id"], "version": item["version"], "provenance": item.get("provenance")}], trace,
            transformed, [asdict(value) for value in applications], rejected, [], relation, symbolic,
            None, None, diagnostics)

    conditional_rules = [rule for rule in rules if rule.get("kind") == "exact_under_assumptions"]
    for rule in conditional_rules:
        checks, failures = _hard_constraints(rule, item, theory, context)
        bindings: dict[str, Any] = {}
        if not _pattern_matches(rule["source_pattern"], _root(theory), bindings): failures.append("SOURCE_PATTERN_MISMATCH")
        if failures:
            rejected.append({"rule_id": rule["id"], "status": "TRANSFORMATION_CONSTRAINT_FAILED",
                             "failures": failures, "hard_constraints": checks})
            continue
        transformed = _with_expression(theory, _template(rule["target_template"], bindings))
        conditional_comparison = compare_symbolic(implementation, transformed)
        if not conditional_comparison.get("match"):
            rejected.append({"rule_id": rule["id"], "status": "TRANSFORMATION_CONSTRAINT_FAILED",
                             "failures": ["TARGET_IMPLEMENTATION_MISMATCH"], "hard_constraints": checks})
            continue
        application = _application(rule, theory, transformed, checks, assumption_set,
            {"transformation_set": item["id"], "version": item["version"],
             "rule_file": str(Path(rules_root) / f"{rule['id']}.yaml")})
        remaining = [asdict(value) for value in application.remaining_obligations]
        trace = TransformationTrace(source_id, transformed["expression_id"], [application])
        final = _native_transform("FINALIZE", mode="CONDITIONAL", application=asdict(application))
        return TransformationResult(final["status"],
            [{"id": item["id"], "version": item["version"], "provenance": item.get("provenance")}], trace,
            transformed, [asdict(application)], rejected, remaining,
            final["relation"], conditional_comparison, None, None, diagnostics)

    approximation_rules = [rule for rule in rules if rule.get("kind") == "approximation"]
    feasible_rules = []
    checks_by_rule: dict[str, list[dict[str, Any]]] = {}
    match_by_rule: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for rule in approximation_rules:
        checks, failures = _hard_constraints(rule, item, theory, context)
        checks_by_rule[rule["id"]] = checks
        matches = _find_pattern_matches(rule["source_pattern"], _root(theory))
        explicit_path = context.get("target_path")
        if explicit_path is not None:
            wanted = tuple(explicit_path)
            matches = [match for match in matches if match[0] == wanted]
        if not matches:
            failures.append("SOURCE_PATTERN_MISMATCH" if explicit_path is None else "EXPLICIT_TARGET_PATH_MISMATCH")
        elif len(matches) > 1:
            failures.append("AMBIGUOUS_TRANSFORMATION_MATCH")
        else:
            match_by_rule[rule["id"]] = matches[0]
        if failures:
            rejected.append({"rule_id": rule["id"], "status": "TRANSFORMATION_CONSTRAINT_FAILED", "failures": failures, "hard_constraints": checks})
        else: feasible_rules.append(rule)
    selection = select_transformation(item, feasible_rules, context.get("required_observables", []), selection_profile)
    selected_id = (selection.get("selected") or {}).get("rule_id")
    selected = next((rule for rule in feasible_rules if rule["id"] == selected_id), None)
    if selected is None:
        selection_remaining = ([asdict(TransformationObligation(_id("obligation", [item["id"], "selection"]),
            "user selection required for tied feasible transformations", "CANDIDATE_SELECTION", "REMAINING", None))]
            if selection.get("status") == "SELECTION_TIE_REQUIRES_USER" else [])
        final = _native_transform("FINALIZE", mode="NO_SELECTION", rejected=rejected, selection=selection)
        status = final["status"]
        diagnostics.extend(final["diagnostics"][:-1])
        trace = TransformationTrace(source_id, source_id, [])
        return TransformationResult(status, [{"id": item["id"], "version": item["version"], "provenance": item.get("provenance")}],
            trace, deepcopy(theory), [], rejected, selection_remaining, final["relation"], None, None, selection,
            [*diagnostics, final["diagnostics"][-1]])
    target_path, bindings = match_by_rule[selected["id"]]
    replacement = _template(selected["target_template"], bindings)
    transformed = _with_expression(theory, _replace_path(_root(theory), target_path, replacement))
    comparison = compare_symbolic(implementation, transformed)
    application = _application(selected, theory, transformed, checks_by_rule[selected["id"]], assumption_set,
        {"transformation_set": item["id"], "version": item["version"], "rule_file": str(Path(rules_root) / f"{selected['id']}.yaml"),
         "library_contract": selected.get("library_contract"), "target_path": list(target_path),
         "parameters": {name: context.get(name) for name in selected.get("parameters", [])}})
    applications.append(application)
    remaining = [asdict(item) for item in application.remaining_obligations]
    final = _native_transform("FINALIZE", mode="APPROXIMATION", matched=bool(comparison.get("match")),
                              selected=selected, application=asdict(application))
    relation, status = final["relation"], final["status"]
    diagnostics.extend(final["diagnostics"])
    residual = {"status": "BOUND_NOT_YET_EVALUATED", "op": "Subtract",
                "theory_expression": deepcopy(_root(transformed)), "implementation_expression": deepcopy(_root(implementation)),
                "numeric_samples_used_as_proof": False}
    trace = TransformationTrace(source_id, transformed["expression_id"], applications)
    return TransformationResult(status, [{"id": item["id"], "version": item["version"], "provenance": item.get("provenance")}],
        trace, transformed, [asdict(application)], rejected, remaining, relation, comparison, residual, selection, diagnostics)
