"""Versioned declarative mathematical knowledge registry."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import yaml

from .transformations import RewriteRuleDescriptor, _find_pattern_matches, _replace_path, _template


def _native_knowledge(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "D",
            "operation": "LEGACY_KNOWLEDGE", "action": action, **payload})["result"]


class KnowledgeRelationKind(str, Enum):
    EXACT = "EXACT"
    EXACT_UNDER_ASSUMPTIONS = "EXACT_UNDER_ASSUMPTIONS"
    DEFINITIONAL = "DEFINITIONAL"
    IDENTITY = "IDENTITY"
    TRANSFORMATION = "TRANSFORMATION"
    APPROXIMATION = "APPROXIMATION"
    DISCRETIZATION = "DISCRETIZATION"
    TRUNCATION = "TRUNCATION"
    SAMPLING = "SAMPLING"
    ALGORITHMIC_REALIZATION = "ALGORITHMIC_REALIZATION"


EXACT_KNOWLEDGE_RELATIONS = frozenset({
    KnowledgeRelationKind.EXACT.value,
    KnowledgeRelationKind.EXACT_UNDER_ASSUMPTIONS.value,
    KnowledgeRelationKind.DEFINITIONAL.value,
    KnowledgeRelationKind.IDENTITY.value,
})


class KnowledgeEvidenceKind(str, Enum):
    LEAN_VERIFIED = "LEAN_VERIFIED"
    FORMALLY_DERIVED = "FORMALLY_DERIVED"
    REFERENCE_THEOREM = "REFERENCE_THEOREM"
    REFERENCE_CONTRACT = "REFERENCE_CONTRACT"
    USER_ASSUMPTION = "USER_ASSUMPTION"


@dataclass(frozen=True)
class MathematicalKnowledgeEntry:
    knowledge_id: str
    name: str
    category: str
    lhs: dict[str, Any]
    rhs: dict[str, Any]
    relation_kind: str
    preconditions: tuple[str, ...] = ()
    domain_constraints: tuple[str, ...] = ()
    type_constraints: tuple[str, ...] = ()
    shape_constraints: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    algebraic_structures: tuple[str, ...] = ()
    forward_enabled: bool = True
    reverse_enabled: bool = False
    rewrite_cost: int = 1
    priority: int = 100
    motif_tags: tuple[str, ...] = ()
    provider_hints: tuple[str, ...] = ()
    evidence_kind: str = KnowledgeEvidenceKind.REFERENCE_THEOREM.value
    reference: str | None = None
    lean_theorem: str | None = None

    @property
    def is_exact(self) -> bool:
        return bool(_native_knowledge("ENTRY_PROPERTIES", entry=self.to_dict())["is_exact"])

    @property
    def all_conditions(self) -> tuple[str, ...]:
        return tuple(_native_knowledge("ENTRY_PROPERTIES", entry=self.to_dict())["all_conditions"])

    def descriptor(self) -> RewriteRuleDescriptor:
        value = _native_knowledge("ENTRY_PROPERTIES", entry=self.to_dict())["descriptor"]
        return RewriteRuleDescriptor(value["rule_id"], value["relation_kind"], tuple(value["preconditions"]),
            tuple(value["domain_constraints"]), tuple(value["type_constraints"]), tuple(value["shape_constraints"]),
            tuple(value["assumptions"]), value["cost"], value["priority"], value.get("evidence"),
            value.get("inverse_rule"), tuple(value["motifs"]))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("preconditions", "domain_constraints", "type_constraints", "shape_constraints",
                    "required_facts", "algebraic_structures", "motif_tags", "provider_hints"):
            value[key] = list(value[key])
        return value


class MathematicalKnowledgeRegistry:
    def __init__(self, entries: Iterable[MathematicalKnowledgeEntry] = ()):
        self._entries: dict[str, MathematicalKnowledgeEntry] = {}
        for entry in entries: self.register(entry)

    def register(self, entry: MathematicalKnowledgeEntry) -> None:
        if entry.knowledge_id in self._entries:
            raise ValueError(f"DUPLICATE_MATHEMATICAL_KNOWLEDGE:{entry.knowledge_id}")
        diagnostics = _native_knowledge("VALIDATE_ENTRY", entry=entry.to_dict())["diagnostics"]
        fatal = next((item for item in diagnostics if item.startswith(("INVALID_KNOWLEDGE_", "KNOWLEDGE_EXPRESSION_MISSING"))), None)
        if fatal: raise ValueError(fatal)
        self._entries[entry.knowledge_id] = entry

    def get(self, knowledge_id: str) -> MathematicalKnowledgeEntry:
        return self._entries[knowledge_id]

    def entries(self, *, category: str | None = None, exact_only: bool = False) -> list[MathematicalKnowledgeEntry]:
        selected = _native_knowledge("SELECT", entries=[item.to_dict() for item in self._entries.values()],
                                     category=category, exact_only=exact_only, filter_motifs=False)
        return [self._entries[item["knowledge_id"]] for item in selected]

    def select(self, *, motifs: Iterable[str] = (), provider_hints: Iterable[str] = (),
               authorized_ids: Iterable[str] | None = None) -> list[MathematicalKnowledgeEntry]:
        selected = _native_knowledge("SELECT", entries=[item.to_dict() for item in self._entries.values()],
            motifs=list(motifs), provider_hints=list(provider_hints),
            authorized_ids=list(authorized_ids) if authorized_ids is not None else None, filter_motifs=True)
        return [self._entries[item["knowledge_id"]] for item in selected]

    def metrics(self) -> dict[str, Any]:
        return _native_knowledge("METRICS", entries=[item.to_dict() for item in self._entries.values()])

    def validate(self) -> list[str]:
        return _native_knowledge("VALIDATE", entries=[item.to_dict() for item in self._entries.values()])["diagnostics"]

    @classmethod
    def load(cls, root: str | Path) -> "MathematicalKnowledgeRegistry":
        path = Path(root); files = [path] if path.is_file() else sorted(path.glob("*.yaml"))
        entries: list[MathematicalKnowledgeEntry] = []
        for filename in files:
            raw = yaml.safe_load(filename.read_text(encoding="utf-8")) or {}
            for item in raw.get("knowledge", ()):
                entries.append(MathematicalKnowledgeEntry(
                    knowledge_id=item["knowledge_id"], name=item["name"], category=item["category"],
                    lhs=item["lhs"], rhs=item["rhs"], relation_kind=item["relation_kind"],
                    preconditions=tuple(item.get("preconditions", ())),
                    domain_constraints=tuple(item.get("domain_constraints", ())),
                    type_constraints=tuple(item.get("type_constraints", ())),
                    shape_constraints=tuple(item.get("shape_constraints", ())),
                    required_facts=tuple(item.get("required_facts", ())),
                    algebraic_structures=tuple(item.get("algebraic_structures", ())),
                    forward_enabled=bool(item.get("forward_enabled", True)),
                    reverse_enabled=bool(item.get("reverse_enabled", False)),
                    rewrite_cost=int(item.get("rewrite_cost", 1)), priority=int(item.get("priority", 100)),
                    motif_tags=tuple(item.get("motif_tags", ())), provider_hints=tuple(item.get("provider_hints", ())),
                    evidence_kind=item.get("evidence_kind", KnowledgeEvidenceKind.REFERENCE_THEOREM.value),
                    reference=item.get("reference"), lean_theorem=item.get("lean_theorem")))
        return cls(entries)

    @classmethod
    def default(cls) -> "MathematicalKnowledgeRegistry":
        return cls.load(Path(__file__).resolve().parents[2] / "registry" / "mathematical_knowledge")


def apply_knowledge_once(node: dict[str, Any], entry: MathematicalKnowledgeEntry) -> list[dict[str, Any]]:
    """Apply declarative pattern/template knowledge without engine-specific code."""
    return _native_knowledge("APPLY_ONCE", node=node, entry=entry.to_dict())
