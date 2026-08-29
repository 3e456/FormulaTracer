"""Typed, authorization-gated equality saturation for Mathematical IR.

Only exact relations may union e-classes.  Approximation, discretization,
truncation, sampling, and algorithm-realization claims live in a separate
relation graph and can therefore never become equality by accident.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .math_surface import canonical_equal, generalize, typed_unify
from .transformations import RewriteRuleDescriptor, _rewrite_once, load_rewrite_catalog
from .mathematical_knowledge import (MathematicalKnowledgeEntry, MathematicalKnowledgeRegistry,
                                     apply_knowledge_once)
from .algebraic_domains import AlgebraicStructure, structure_closure, structure_fact


EXACT_RULE_KINDS = frozenset({
    "EXACT", "EXACT_UNDER_ASSUMPTIONS", "ALGEBRAIC_EQUIVALENCE",
    "IDENTITY_UNDER_ASSUMPTIONS",
})


def _native_equality(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "B",
            "operation": "LEGACY_EQUALITY", "action": action, **payload})["result"]


def _fact_payload(engine: "MathematicalFactEngine") -> dict[str, Any]:
    return {"facts": [asdict(item) for item in engine._facts.values()],
            "conflicts": [asdict(item) for item in engine.conflicts]}


def _restore_facts(engine: "MathematicalFactEngine", value: dict[str, Any]) -> None:
    engine._facts = {(item["subject"], item["key"]): MathematicalFact(**item) for item in value["facts"]}
    engine.conflicts = [FactConflict(**item) for item in value["conflicts"]]


class RelationKind(str, Enum):
    APPROXIMATION_OF = "APPROXIMATION_OF"
    DISCRETIZATION_OF = "DISCRETIZATION_OF"
    TRUNCATED_TO = "TRUNCATED_TO"
    SAMPLED_AS = "SAMPLED_AS"
    TRANSFORMED_TO = "TRANSFORMED_TO"
    ALGORITHMICALLY_REALIZED_BY = "ALGORITHMICALLY_REALIZED_BY"


class SaturationStatus(str, Enum):
    SATURATED = "SATURATED"
    SATURATION_BUDGET_EXHAUSTED = "SATURATION_BUDGET_EXHAUSTED"
    CONDITIONALLY_BLOCKED = "CONDITIONALLY_BLOCKED"


@dataclass(frozen=True)
class MathematicalFact:
    key: str
    value: Any = True
    subject: str = "global"
    evidence: str = "DECLARED"


@dataclass
class FactConflict:
    subject: str
    key: str
    left: Any
    right: Any


class MathematicalFactEngine:
    """Small deterministic fact store used to guard conditional equality."""

    _ALIASES = {
        "x > 0": ("x_positive_real",),
        "z is real": ("z_real",),
        "n is natural": ("n_natural",),
        "complex_semantics": ("complex_valued",),
        "complex semantics": ("complex_semantics", "complex_valued"),
    }
    _CONTRADICTIONS = {"x > 0": ("x <= 0", "x_nonpositive"), "x <= 0": ("x > 0", "x_positive_real"),
                       "x != 0": ("x = 0",), "x = 0": ("x != 0",),
                       "n >= 0": ("n < 0",), "n < 0": ("n >= 0",)}

    def __init__(self, facts: Iterable[str | MathematicalFact] = ()):
        self._facts: dict[tuple[str, str], MathematicalFact] = {}
        self.conflicts: list[FactConflict] = []
        for fact in facts:
            self.assert_fact(fact)

    def assert_fact(self, fact: str | MathematicalFact, *, subject: str = "global",
                    evidence: str = "DECLARED") -> bool:
        item = fact if isinstance(fact, MathematicalFact) else MathematicalFact(str(fact), True, subject, evidence)
        value = _native_equality("FACT_ASSERT", **_fact_payload(self), fact=asdict(item))
        _restore_facts(self, value)
        return bool(value["accepted"])

    def knows(self, statement: str, *, subject: str = "global") -> bool:
        return bool(_native_equality("FACT_KNOWS", **_fact_payload(self), statement=statement,
                                     subject=subject)["knows"])

    def missing_for(self, rule: RewriteRuleDescriptor) -> tuple[str, ...]:
        return tuple(_native_equality("FACT_MISSING", **_fact_payload(self), rule=asdict(rule))["missing"])

    def merge(self, other: "MathematicalFactEngine") -> bool:
        value = _native_equality("FACT_MERGE", **_fact_payload(self),
                                 other_facts=[asdict(item) for item in other._facts.values()])
        _restore_facts(self, value)
        return bool(value["accepted"])

    def to_dict(self) -> dict[str, Any]:
        return {"facts": [asdict(item) for item in sorted(self._facts.values(), key=lambda x: (x.subject, x.key))],
                "conflicts": [asdict(item) for item in self.conflicts]}


@dataclass(frozen=True)
class ENode:
    expression_id: str
    expression: dict[str, Any]
    origin: str
    cost: int


@dataclass
class EClass:
    eclass_id: str
    nodes: dict[str, ENode] = field(default_factory=dict)
    facts: MathematicalFactEngine = field(default_factory=MathematicalFactEngine)
    origin_set: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EqualityTraceStep:
    rule_id: str
    relation_kind: str
    source_expression_id: str
    target_expression_id: str
    eclass_id: str
    discharged_conditions: tuple[str, ...]
    evidence: str | None


@dataclass(frozen=True)
class BlockedRewrite:
    rule_id: str
    expression_id: str
    missing_conditions: tuple[str, ...]


@dataclass(frozen=True)
class SaturationBudget:
    iterations: int = 8
    enodes: int = 200
    rule_applications: int = 500


@dataclass
class SaturationResult:
    status: str
    root_eclass_ids: tuple[str, ...]
    iterations: int
    enode_count: int
    rule_applications: int
    trace: list[EqualityTraceStep]
    blocked_rewrites: list[BlockedRewrite]
    selected_packs: tuple[str, ...]
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "root_eclass_ids": list(self.root_eclass_ids),
                "iterations": self.iterations, "enode_count": self.enode_count,
                "rule_applications": self.rule_applications,
                "trace": [{**asdict(item), "discharged_conditions": list(item.discharged_conditions)}
                          for item in self.trace],
                "blocked_rewrites": [{**asdict(item), "missing_conditions": list(item.missing_conditions)}
                                     for item in self.blocked_rewrites],
                "selected_packs": list(self.selected_packs), "diagnostics": list(self.diagnostics)}


@dataclass(frozen=True)
class RelationEdge:
    source_eclass_id: str
    target_eclass_id: str
    relation_kind: str
    conditions: tuple[str, ...] = ()
    evidence: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class MathematicalRelationGraph:
    """Graph of intentionally non-equality mathematical relationships."""

    def __init__(self) -> None:
        self.edges: list[RelationEdge] = []

    def add(self, source_eclass_id: str, target_eclass_id: str,
            relation_kind: RelationKind | str, *, conditions: Iterable[str] = (),
            evidence: str | None = None, metadata: Mapping[str, Any] | None = None) -> RelationEdge:
        kind = str(relation_kind.value if isinstance(relation_kind, RelationKind) else relation_kind)
        decision = _native_equality("RELATION_VALIDATE", relation_kind=kind)
        if not decision["accepted"]:
            raise ValueError(f"NON_RELATION_GRAPH_KIND:{kind}")
        edge = RelationEdge(source_eclass_id, target_eclass_id, kind, tuple(conditions), evidence,
                            dict(metadata or {}))
        self.edges.append(edge)
        return edge

    def to_dict(self) -> dict[str, Any]:
        return {"edges": [{**asdict(edge), "conditions": list(edge.conditions),
                            "metadata": dict(edge.metadata)} for edge in self.edges]}


def _marker(expression: Any) -> str:
    return json.dumps(expression, sort_keys=True, separators=(",", ":"), default=str)


def _expression_id(expression: Any) -> str:
    return "expr:" + sha256(_marker(expression).encode()).hexdigest()[:16]


def _source_origins(expression: Any) -> list[dict[str, Any]]:
    origins = []
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("source_span"), dict) and value["source_span"] not in origins:
                origins.append(deepcopy(value["source_span"]))
            if isinstance(value.get("operator_span"), dict) and value["operator_span"] not in origins:
                origins.append(deepcopy(value["operator_span"]))
            if isinstance(value.get("callable_span"), dict) and value["callable_span"] not in origins:
                origins.append(deepcopy(value["callable_span"]))
            for item in value.get("source_spans", []):
                if isinstance(item, dict) and item not in origins: origins.append(deepcopy(item))
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(expression); return origins


class TypedEGraph:
    """Compact Mathematical-IR e-graph retaining every discovered exact form.

    Nodes are whole Mathematical-IR terms in this Python reference backend.  The
    public API intentionally mirrors add/union/extract/e-match so a native egg
    backend can replace storage without changing audit semantics.
    """

    def __init__(self) -> None:
        self.classes: dict[str, EClass] = {}
        self.parents: dict[str, str] = {}
        self.expression_classes: dict[str, str] = {}
        self.trace: list[EqualityTraceStep] = []

    def find(self, eclass_id: str) -> str:
        parent = self.parents[eclass_id]
        if parent != eclass_id:
            self.parents[eclass_id] = self.find(parent)
        return self.parents[eclass_id]

    def add(self, expression: dict[str, Any], *, origin: str = "input", cost: int = 0,
            facts: MathematicalFactEngine | None = None) -> str:
        from formulatracer.native import NativeContext
        with NativeContext() as context:
            context.execute_kernel({"schema_version": "1.0", "kernel": "B", "operation": "EGRAPH",
                                    "values": [expression], "queries": []})
        marker = _marker(expression)
        if marker in self.expression_classes:
            existing = self.find(self.expression_classes[marker])
            if facts is not None and not self.classes[existing].facts.merge(facts):
                raise ValueError("ECLASS_FACT_CONFLICT")
            return existing
        expression_id = _expression_id(expression)
        eclass_id = "eclass:" + expression_id.split(":", 1)[1]
        while eclass_id in self.classes:
            eclass_id += "x"
        node = ENode(expression_id, deepcopy(expression), origin, cost)
        self.classes[eclass_id] = EClass(eclass_id, {expression_id: node}, facts or MathematicalFactEngine(),
                                         _source_origins(expression))
        self.parents[eclass_id] = eclass_id
        self.expression_classes[marker] = eclass_id
        return eclass_id

    def union(self, left: str, right: str) -> str:
        left, right = self.find(left), self.find(right)
        if left == right:
            return left
        # Merge fact analyses before equality. Conflicting domain/shape/type facts
        # fail closed rather than silently creating an inconsistent e-class.
        decision = _native_equality("UNION_VALIDATE",
            left_facts=[asdict(item) for item in self.classes[left].facts._facts.values()],
            right_facts=[asdict(item) for item in self.classes[right].facts._facts.values()])
        if not decision["accepted"]:
            raise ValueError("ECLASS_FACT_CONFLICT")
        probe = MathematicalFactEngine()
        _restore_facts(probe, decision)
        keep, drop = sorted((left, right))
        self.parents[drop] = keep
        self.classes[keep].nodes.update(self.classes[drop].nodes)
        self.classes[keep].facts = probe
        for origin in self.classes[drop].origin_set:
            if origin not in self.classes[keep].origin_set: self.classes[keep].origin_set.append(origin)
        for node in self.classes[drop].nodes.values():
            self.expression_classes[_marker(node.expression)] = keep
        del self.classes[drop]
        return keep

    def add_equivalent(self, root: str, expression: dict[str, Any], *, origin: str,
                       cost: int) -> tuple[str, ENode, bool]:
        root = self.find(root)
        expression = deepcopy(expression)
        origins = list(self.classes[root].origin_set)
        for item in _source_origins(expression):
            if item not in origins: origins.append(item)
        if origins:
            expression["source_spans"] = origins
        marker = _marker(expression); existed = marker in self.expression_classes
        added = self.add(expression, origin=origin, cost=cost)
        root = self.union(root, added)
        node = self.classes[root].nodes[_expression_id(expression)]
        return root, node, not existed

    def nodes(self, root: str) -> list[ENode]:
        return list(self.classes[self.find(root)].nodes.values())

    def equivalent(self, left: str, right: str) -> bool:
        return self.find(left) == self.find(right)

    def extract(self, root: str) -> dict[str, Any]:
        return deepcopy(_native_equality("EXTRACT", candidates=[asdict(item) for item in self.nodes(root)]))

    def ematch(self, root: str, pattern: dict[str, Any]) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        generalized_pattern = generalize(pattern)
        for node in self.nodes(root):
            result = typed_unify(generalized_pattern, generalize(node.expression).pattern)
            if result.status == "TYPED_UNIFICATION_SUCCEEDED":
                matches.append({"expression_id": node.expression_id,
                                "substitution": deepcopy(result.substitution),
                                "obligations": list(result.obligations)})
        return matches


@dataclass(frozen=True)
class RewritePack:
    pack_id: str
    motifs: tuple[str, ...]
    rule_ids: tuple[str, ...]


def load_rewrite_packs(path: str | Path | None = None) -> list[RewritePack]:
    target = Path(path) if path else Path(__file__).resolve().parents[2] / "registry" / "transformations" / "rewrite_packs.yaml"
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return [RewritePack(item["pack_id"], tuple(item.get("motifs", ())), tuple(item.get("rule_ids", ())))
            for item in raw.get("packs", ())]


def select_rewrite_packs(motifs: Iterable[str], *, useful_rewrites: Iterable[str] = (),
                         packs: Iterable[RewritePack] | None = None) -> tuple[RewritePack, ...]:
    source = list(packs or load_rewrite_packs())
    selected = _native_equality("PACK_SELECT", motifs=list(motifs), useful_rewrites=list(useful_rewrites),
                                packs=[asdict(item) for item in source])
    return tuple(RewritePack(item["pack_id"], tuple(item["motifs"]), tuple(item["rule_ids"])) for item in selected)


class ExactEqualitySaturator:
    """Budgeted exact equality saturation over an authorized rule subset."""

    def __init__(self, *, authorized_rule_ids: Iterable[str], facts: Iterable[str | MathematicalFact] = (),
                 motifs: Iterable[str] = (), useful_rewrites: Iterable[str] = (),
                 budget: SaturationBudget | None = None):
        self.authorized = set(authorized_rule_ids)
        self.fact_engine = MathematicalFactEngine(facts)
        self.motifs = set(motifs)
        self.packs = select_rewrite_packs(self.motifs, useful_rewrites=useful_rewrites)
        pack_rules = {rule for pack in self.packs for rule in pack.rule_ids}
        useful = set(useful_rewrites)
        eligible = pack_rules | useful
        selected_rules = _native_equality("RULES_SELECT", authorized=sorted(self.authorized), eligible=sorted(eligible),
                                          rules=[asdict(rule) for rule in load_rewrite_catalog()])
        legacy_rules = [RewriteRuleDescriptor(**{**item,
            "preconditions": tuple(item.get("preconditions", [])), "domain_constraints": tuple(item.get("domain_constraints", [])),
            "type_constraints": tuple(item.get("type_constraints", [])), "shape_constraints": tuple(item.get("shape_constraints", [])),
            "assumptions": tuple(item.get("assumptions", [])), "motifs": tuple(item.get("motifs", []))}) for item in selected_rules]
        knowledge = MathematicalKnowledgeRegistry.default()
        self.knowledge_rules: dict[str, MathematicalKnowledgeEntry] = {
            item.knowledge_id: item for item in knowledge.entries(exact_only=True)
            if item.knowledge_id in self.authorized and (not eligible or item.knowledge_id in eligible)
        }
        self.rules = legacy_rules + [entry.descriptor() for entry in self.knowledge_rules.values()]
        self.rules.sort(key=lambda item: (item.cost, item.priority, item.rule_id))
        self.budget = budget or SaturationBudget()

    def run(self, expressions: Iterable[dict[str, Any]]) -> tuple[TypedEGraph, SaturationResult]:
        graph = TypedEGraph()
        roots = [graph.add(item, origin=f"root:{index}", facts=self.fact_engine)
                 for index, item in enumerate(expressions)]
        blocked: dict[tuple[str, str], BlockedRewrite] = {}
        applications = 0; iterations = 0; exhausted = False
        for iteration in range(self.budget.iterations):
            iterations = iteration + 1; changed = False
            classes = list(graph.classes)
            for class_id in classes:
                if class_id not in graph.parents:
                    continue
                root = graph.find(class_id)
                for node in list(graph.nodes(root)):
                    for rule in self.rules:
                        missing = list(self.fact_engine.missing_for(rule))
                        knowledge_rule = self.knowledge_rules.get(rule.rule_id)
                        if knowledge_rule and knowledge_rule.algebraic_structures and not any(
                                self.fact_engine.knows(structure_fact(item))
                                for item in knowledge_rule.algebraic_structures):
                            missing.append("algebraic_structure_one_of:" + "|".join(knowledge_rule.algebraic_structures))
                        if missing:
                            blocked[(rule.rule_id, node.expression_id)] = BlockedRewrite(rule.rule_id, node.expression_id, tuple(missing))
                            continue
                        generated = (apply_knowledge_once(node.expression, self.knowledge_rules[rule.rule_id])
                                     if rule.rule_id in self.knowledge_rules
                                     else _rewrite_once(node.expression, rule.rule_id))
                        for rewritten in generated:
                            applications += 1
                            if applications > self.budget.rule_applications or sum(len(x.nodes) for x in graph.classes.values()) >= self.budget.enodes:
                                exhausted = True; break
                            root, target, added = graph.add_equivalent(root, rewritten, origin=rule.rule_id,
                                                                       cost=node.cost + rule.cost)
                            if added:
                                changed = True
                                graph.trace.append(EqualityTraceStep(rule.rule_id, rule.relation_kind,
                                    node.expression_id, target.expression_id, root,
                                    (*rule.preconditions, *rule.domain_constraints, *rule.type_constraints,
                                     *rule.shape_constraints, *rule.assumptions), rule.evidence))
                        if exhausted: break
                    if exhausted: break
                if exhausted: break
            # Congruence by canonical Mathematical-IR equality, including alpha rename.
            live = list(graph.classes)
            for index, left in enumerate(live):
                if left not in graph.parents: continue
                for right in live[index + 1:]:
                    if right not in graph.parents: continue
                    if any(canonical_equal(a.expression, b.expression)
                           for a in graph.nodes(left) for b in graph.nodes(right)):
                        graph.union(left, right); changed = True
            if exhausted or not changed:
                break
        roots = tuple(graph.find(root) for root in roots)
        final = _native_equality("SATURATION_STATUS", exhausted=exhausted, iterations=iterations,
            iteration_limit=self.budget.iterations, changed=changed, blocked_count=len(blocked), trace_count=len(graph.trace))
        status = final["status"]
        result = SaturationResult(status, roots, iterations,
            sum(len(item.nodes) for item in graph.classes.values()), min(applications, self.budget.rule_applications),
            list(graph.trace), list(blocked.values()), tuple(pack.pack_id for pack in self.packs),
            final["diagnostics"])
        return graph, result


def replay_equality_trace(trace: Iterable[EqualityTraceStep], graph: TypedEGraph) -> bool:
    """Replay every recorded rewrite against its exact source/target pair."""
    nodes = {node.expression_id: node for item in graph.classes.values() for node in item.nodes.values()}
    for step in trace:
        source, target = nodes.get(step.source_expression_id), nodes.get(step.target_expression_id)
        if source is None or target is None:
            return False
        try: knowledge = MathematicalKnowledgeRegistry.default().get(step.rule_id)
        except KeyError: candidates = _rewrite_once(source.expression, step.rule_id)
        else: candidates = apply_knowledge_once(source.expression, knowledge)
        if not any(canonical_equal(candidate, target.expression) for candidate in candidates):
            return False
    return True


@dataclass
class EGraphMatchResult:
    status: str
    graph: TypedEGraph
    saturation: SaturationResult
    requested_eclass_id: str
    provider_eclass_id: str
    matches: list[dict[str, Any]]


def saturate_and_match(requested: dict[str, Any], provider_pattern: dict[str, Any], *,
                       authorized_rule_ids: Iterable[str], facts: Iterable[str | MathematicalFact] = (),
                       motifs: Iterable[str] = (), useful_rewrites: Iterable[str] = (),
                       budget: SaturationBudget | None = None) -> EGraphMatchResult:
    engine = ExactEqualitySaturator(authorized_rule_ids=authorized_rule_ids, facts=facts, motifs=motifs,
                                    useful_rewrites=useful_rewrites, budget=budget)
    graph, saturation = engine.run((requested, provider_pattern))
    requested_root, provider_root = saturation.root_eclass_ids
    matches = graph.ematch(requested_root, provider_pattern)
    exact = graph.equivalent(requested_root, provider_root) or bool(matches)
    return EGraphMatchResult("EGRAPH_EXACT_MATCH" if exact else "EGRAPH_NO_EXACT_MATCH", graph, saturation,
                             requested_root, provider_root, matches)
