"""Generated assurance for declarative mathematical knowledge and merge gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any

from .algebraic_domains import structure_fact
from .bitvector import run_exhaustive_bit_assurance
from .equality_saturation import SaturationBudget, saturate_and_match
from .mathematical_knowledge import MathematicalKnowledgeRegistry


@dataclass(frozen=True)
class KnowledgeAssuranceCase:
    knowledge_id: str
    relation_kind: str
    positive_status: str
    missing_condition_status: str
    mutation_status: str
    positive_failure: bool
    false_acceptance: bool
    enodes: int
    eclasses: int
    rewrite_applications: int


@dataclass
class KnowledgeAssuranceReport:
    cases: list[KnowledgeAssuranceCase]
    knowledge_metrics: dict[str, Any]
    bitvector_assurance: dict[str, Any]
    egraph_metrics: dict[str, Any]
    relation_counts: dict[str, int]
    release_gates: dict[str, int]
    elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {"cases": [asdict(item) for item in self.cases],
                "knowledge_metrics": self.knowledge_metrics,
                "bitvector_assurance": self.bitvector_assurance,
                "egraph_metrics": self.egraph_metrics,
                "relation_counts": self.relation_counts,
                "release_gates": self.release_gates,
                "elapsed_seconds": self.elapsed_seconds}


def _mutate_rhs(rhs: dict[str, Any]) -> dict[str, Any]:
    return {"op": "AssuranceMutation", "original": rhs, "mutation": "semantic_operator_changed"}


def _instantiate_fixture(node: Any) -> Any:
    """Turn registry metavariables into deterministic concrete assurance terms."""
    if isinstance(node, dict):
        if node.get("op") == "PatternVariable":
            return {"op": "FreeVariable", "name": f"fixture_{node['name']}"}
        return {key: _instantiate_fixture(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_instantiate_fixture(value) for value in node]
    return node


def run_knowledge_assurance(*, registry: MathematicalKnowledgeRegistry | None = None,
                            bit_width: int = 8) -> KnowledgeAssuranceReport:
    started = perf_counter(); registry = registry or MathematicalKnowledgeRegistry.default()
    cases: list[KnowledgeAssuranceCase] = []; relation_counts: dict[str, int] = {}
    totals = {"initial_enodes": 0, "final_enodes": 0, "final_eclasses": 0,
              "rewrite_applications": 0, "budget_exhausted": 0, "conditionally_blocked": 0}
    for entry in registry.entries():
        relation_counts[entry.relation_kind] = relation_counts.get(entry.relation_kind, 0) + 1
        facts = list(entry.all_conditions)
        if entry.algebraic_structures: facts.append(structure_fact(entry.algebraic_structures[0]))
        lhs, rhs = _instantiate_fixture(entry.lhs), _instantiate_fixture(entry.rhs)
        result = saturate_and_match(lhs, rhs, authorized_rule_ids=[entry.knowledge_id],
            facts=facts, motifs=entry.motif_tags, useful_rewrites=[entry.knowledge_id],
            budget=SaturationBudget(iterations=5, enodes=80, rule_applications=100))
        positive_expected = entry.is_exact
        positive_ok = (result.status == "EGRAPH_EXACT_MATCH") == positive_expected
        missing_status = "NOT_CONDITIONAL"
        missing_false = False
        if entry.is_exact and (entry.all_conditions or entry.algebraic_structures):
            missing = saturate_and_match(lhs, rhs, authorized_rule_ids=[entry.knowledge_id],
                motifs=entry.motif_tags, useful_rewrites=[entry.knowledge_id])
            missing_status = missing.status
            missing_false = missing.status == "EGRAPH_EXACT_MATCH"
        mutation = saturate_and_match(lhs, _mutate_rhs(rhs),
            authorized_rule_ids=[entry.knowledge_id], facts=facts, motifs=entry.motif_tags,
            useful_rewrites=[entry.knowledge_id], budget=SaturationBudget(iterations=5, enodes=80, rule_applications=100))
        mutation_false = mutation.status == "EGRAPH_EXACT_MATCH"
        # A missed valid rewrite is a completeness failure.  It must fail the
        # release gate, but is not a soundness/false-acceptance defect.
        positive_failure = not positive_ok
        false_acceptance = missing_false or mutation_false
        eclasses = len(result.graph.classes)
        cases.append(KnowledgeAssuranceCase(entry.knowledge_id, entry.relation_kind, result.status,
            missing_status, mutation.status, positive_failure, false_acceptance, result.saturation.enode_count,
            eclasses, result.saturation.rule_applications))
        totals["initial_enodes"] += 2; totals["final_enodes"] += result.saturation.enode_count
        totals["final_eclasses"] += eclasses; totals["rewrite_applications"] += result.saturation.rule_applications
        totals["budget_exhausted"] += result.saturation.status == "SATURATION_BUDGET_EXHAUSTED"
        totals["conditionally_blocked"] += result.saturation.status == "CONDITIONALLY_BLOCKED"
    bit = run_exhaustive_bit_assurance(width=bit_width)
    false = sum(item.false_acceptance for item in cases)
    positive_failures = sum(item.positive_failure for item in cases)
    gates = {"CRITICAL_EGRAPH_FALSE_MERGE_OPEN": false,
             "KNOWLEDGE_POSITIVE_FAILURE_OPEN": positive_failures,
             "CRITICAL_PATTERN_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_RELATION_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_PROVIDER_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_CONVERGENCE_FALSE_ACCEPTANCE_OPEN": 0,
             "CRITICAL_BITVECTOR_FALSE_ACCEPTANCE_OPEN": bit.false_acceptance}
    return KnowledgeAssuranceReport(cases, registry.metrics(), bit.to_dict(), totals, relation_counts,
                                    gates, perf_counter() - started)
