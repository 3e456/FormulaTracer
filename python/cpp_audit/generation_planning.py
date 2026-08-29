"""High-recall provider retrieval followed by strict, replayable adoption."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
import yaml

from .math_surface import (MathBuilder, MathSurfaceAST, NotationResolutionError,
                           SymbolDeclaration, canonical_equal, generalize, instantiate,
                           parse_tex, to_dsl, to_json, to_markdown, to_tex, to_unicode, typed_unify)
from .math_semantics import (CertifiedRange, Domain, FourierSeries, InfiniteProcess, Sequence, TruncationRequirement,
                             TruncationRequirementSolver, analyze_convergence, integral_transform,
                             localize_mathematical_node, OriginSet)
from .transformations import BoundedRewriteResult, bounded_rewrite_search, load_rewrite_catalog
from .equality_saturation import (EGraphMatchResult, MathematicalRelationGraph, RelationEdge, RelationKind,
                                  SaturationBudget, TypedEGraph, saturate_and_match)


def _id(prefix: str, value: Any) -> str:
    return prefix + ":" + sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _walk(node: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], dict[str, Any]]]:
    if isinstance(node, dict):
        if "op" in node: yield path, node
        for key, value in node.items(): yield from _walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node): yield from _walk(value, path + (index,))


def mathematical_features(expression: dict[str, Any]) -> dict[str, Any]:
    ops: set[str] = set(); functions: set[str] = set(); max_rank = 0; bound = 0
    for _, node in _walk(expression):
        op = str(node.get("op")); ops.add(op)
        if op == "FunctionCall": functions.add(str(node.get("name")).lower())
        if op == "IndexedValue": max_rank = max(max_rank, len(node.get("indices", [])))
        if node.get("bound_index"): bound += 1
    motifs: set[str] = set()
    mappings = {
        "FiniteSum": "finite_sum", "InfiniteSeries": "series", "Integral": "integral",
        "Factorial": "factorial", "Derivative": "derivative", "Transpose": "transpose",
        "MatMul": "matmul", "Convolution": "convolution", "Multiply": "multiply",
        "Divide": "divide", "Add": "add", "Power": "power",
    }
    motifs |= {motif for op, motif in mappings.items() if op in ops}
    motifs |= functions
    if "exp" in functions and "FiniteSum" in ops: motifs |= {"complex_exponential", "fourier"}
    if "Factorial" in ops or "factorial" in functions: motifs |= {"factorial", "series"}
    if "Integral" in ops and "exp" in functions: motifs |= {"transform", "laplace"}
    if "FiniteSum" in ops and "Multiply" in ops: motifs |= {"weighted_sum", "indexed_multiplication"}
    return {"ops": sorted(ops), "functions": sorted(functions), "motifs": sorted(motifs),
            "tensor_rank": max_rank, "bound_index_count": bound,
            "finite": "FiniteSum" in ops, "infinite": "InfiniteSeries" in ops,
            "complex_valued": any(value in json.dumps(expression) for value in ('"i"', '"-i"'))}


@dataclass(frozen=True)
class ProviderContract:
    provider_id: str
    language: str
    callable: str
    pattern: dict[str, Any]
    motifs: tuple[str, ...]
    useful_rewrites: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    execution_metadata: Mapping[str, Any] = field(default_factory=dict)
    lowering: str = "direct"
    implementation_relation: str = "EXACT_EQUAL"
    realization_relation: str | None = None


class MathematicalPatternIndex:
    """High-recall inverted index; it ranks candidates but proves nothing."""
    def __init__(self, contracts: Iterable[ProviderContract]):
        self.contracts = list(contracts); self.by_motif: dict[str, list[ProviderContract]] = {}
        for contract in self.contracts:
            for motif in contract.motifs: self.by_motif.setdefault(motif, []).append(contract)

    def retrieve(self, features: Mapping[str, Any]) -> list[ProviderContract]:
        seen: set[str] = set(); result: list[ProviderContract] = []
        for motif in features.get("motifs", []):
            for contract in self.by_motif.get(motif, []):
                if contract.provider_id not in seen: seen.add(contract.provider_id); result.append(contract)
        result.extend(contract for contract in self.contracts if contract.provider_id not in seen)
        return result


def _v(name: str) -> dict[str, Any]: return {"op": "FreeVariable", "name": name}
def _b(name: str) -> dict[str, Any]: return {"op": "BoundVariable", "name": name}
def _c(value: Any) -> dict[str, Any]: return {"op": "Constant", "value": value}


def default_provider_registry() -> list[ProviderContract]:
    dft = {"op": "FiniteSum", "bound_index": "n", "index_domain": {"lower": _c(0), "upper_exclusive": _v("N")},
           "body": {"op": "Multiply", "args": [{"op": "IndexedValue", "name": "x", "indices": [_b("n")]},
              {"op": "FunctionCall", "name": "exp", "args": [{"op": "Divide", "args": [
                  {"op": "Multiply", "args": [_c("-2*pi*i"), {"op": "Multiply", "args": [_b("k"), _b("n")]}]}, _v("N")]}]}]}}
    taylor = {"op": "FiniteSum", "bound_index": "n", "index_domain": {"lower": _c(0), "upper_exclusive": _v("N")},
              "body": {"op": "Divide", "args": [{"op": "Power", "args": [_v("x"), _b("n")]},
                                                      {"op": "Factorial", "args": [_b("n")]}]}}
    finite_difference = {"op": "Divide", "args": [{"op": "Subtract", "args": [
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Add", "args": [_v("x"), _v("h")]}]},
        {"op": "FunctionCall", "name": "f", "args": [{"op": "Subtract", "args": [_v("x"), _v("h")]}]}]},
        {"op": "Multiply", "args": [_c(2), _v("h")]}]}
    weighted = {"op": "FiniteSum", "bound_index": "i", "index_domain": {"lower": _c(0), "upper_exclusive": _v("N")},
                "body": {"op": "Multiply", "args": [{"op": "IndexedValue", "name": "w", "indices": [_b("i")]},
                                                        {"op": "IndexedValue", "name": "y", "indices": [_b("i")]}]}}
    return [
        ProviderContract("python.builtin.direct", "python", "generated loop/expression", {}, (), lowering="direct"),
        ProviderContract("rust.std.direct", "rust", "canonical Rust expression/loop", {}, (),
            execution_metadata={"native": True}, lowering="direct"),
        ProviderContract("cpp.std.direct", "cpp", "canonical C++ expression/loop", {}, (),
            execution_metadata={"native": True}, lowering="direct"),
        ProviderContract("numpy.fft.fft", "python", "numpy.fft.fft", dft,
            ("finite_sum", "complex_exponential", "indexed_multiplication", "fourier"),
            ("euler_to_exponential", "sum_reindex", "dft_inverse_normalization"),
            ("complex input", "normalization convention validated"), {"device": "CPU", "algorithm": "FFT"}, "fft",
            realization_relation=RelationKind.ALGORITHMICALLY_REALIZED_BY.value),
        ProviderContract("scipy.special.expn_series", "python", "scipy.special", taylor,
            ("finite_sum", "factorial", "series"), ("recurrence_to_factorial_term", "taylor_partial_sum"),
            ("remainder bound required",), lowering="series",
            implementation_relation=RelationKind.TRUNCATED_TO.value),
        ProviderContract("numpy.central_difference", "python", "array slicing", finite_difference,
            ("shifted_evaluation", "divide", "derivative"), ("finite_difference_first_derivative",),
            ("h != 0", "smoothness and error bound"), lowering="finite_difference"),
        ProviderContract("numpy.dot.quadrature", "python", "numpy.dot", weighted,
            ("weighted_sum", "sampled_values", "finite_sum"), ("quadrature_weighted_sum",),
            ("quadrature weights validated",), lowering="weighted_sum"),
        ProviderContract("rust.ndarray.dot", "rust", "ndarray::ArrayBase::dot", weighted,
            ("weighted_sum", "finite_sum", "indexed_multiplication"), ("dot_to_index_sum",),
            ("contracted dimensions equal",), {"native": True}, "weighted_sum"),
        ProviderContract("cpp.std.inner_product", "cpp", "std::inner_product", weighted,
            ("weighted_sum", "finite_sum", "indexed_multiplication"), ("dot_to_index_sum",),
            ("range lengths equal",), {"native": True}, "weighted_sum"),
        ProviderContract("cpp.eigen.dot", "cpp", "Eigen::MatrixBase::dot", weighted,
            ("weighted_sum", "finite_sum", "indexed_multiplication"), ("dot_to_index_sum",),
            ("vector sizes equal",), {"native": True, "vectorization": "provider-dependent"}, "weighted_sum"),
        ProviderContract("scipy.integrate.quad", "python", "scipy.integrate.quad", {"op": "Integral"},
            ("integral",), ("quadrature_weighted_sum",), ("error estimate checked",), lowering="quadrature",
            implementation_relation=RelationKind.APPROXIMATION_OF.value),
        ProviderContract("scipy.signal.fftconvolve", "python", "scipy.signal.fftconvolve", {"op": "Convolution"},
            ("convolution", "fourier"), ("convolution_transform_product",),
            ("mode and boundary convention validated",), lowering="convolution"),
    ]


@dataclass
class CandidateMatch:
    contract: ProviderContract
    rank: int
    score: float
    reasons: list[str]
    matched_path: tuple[Any, ...]
    stage: str = "LOOSE_RETRIEVAL"
    unification: Any = None
    rewrite: BoundedRewriteResult | None = None
    egraph_match: EGraphMatchResult | None = None
    relation_edges: list[dict[str, Any]] = field(default_factory=list)
    verification_status: str = "NOT_VERIFIED"
    remaining_obligations: list[str] = field(default_factory=list)

    def explain(self, *, language: str = "en") -> str:
        reason = "; ".join(self.reasons)
        if language.startswith("ja"):
            return f"候補 {self.contract.provider_id}（順位 {self.rank}）。探索理由: {reason}。厳密判定: {self.verification_status}。残る条件: {', '.join(self.remaining_obligations) or 'なし'}。"
        return f"Candidate {self.contract.provider_id} (rank {self.rank}). Retrieval reasons: {reason}. Rigorous status: {self.verification_status}. Remaining obligations: {', '.join(self.remaining_obligations) or 'none'}."


@dataclass(frozen=True)
class SearchBudget:
    retrieval: int = 100
    detailed_unification: int = 20
    full_verification: int = 5
    rewrite_states: int = 30
    rewrite_depth: int = 4
    egraph_iterations: int = 8
    egraph_enodes: int = 200
    egraph_rule_applications: int = 500


@dataclass
class GenerationPlan:
    requested_expression: dict[str, Any]
    candidates: list[CandidateMatch]
    budget: SearchBudget
    status: str
    selected: CandidateMatch | None = None
    relation_graph: MathematicalRelationGraph = field(default_factory=MathematicalRelationGraph)
    decision_provenance: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"requested_expression": deepcopy(self.requested_expression),
            "candidates": [{"provider_id": item.contract.provider_id, "rank": item.rank, "score": item.score,
                "reasons": list(item.reasons), "matched_path": list(item.matched_path), "stage": item.stage,
                "verification_status": item.verification_status,
                "remaining_obligations": list(item.remaining_obligations),
                "egraph_status": item.egraph_match.status if item.egraph_match else None,
                "relation_edges": deepcopy(item.relation_edges)} for item in self.candidates],
            "budget": asdict(self.budget), "status": self.status,
            "selected": {"provider_id": self.selected.contract.provider_id} if self.selected else None,
            "relation_graph": self.relation_graph.to_dict(),
            "decision_provenance": deepcopy(self.decision_provenance)}

    def explain(self, *, language: str = "en", limit: int = 10) -> str:
        heading = "生成候補" if language.startswith("ja") else "Generation candidates"
        return heading + "\n" + "\n".join(item.explain(language=language) for item in self.candidates[:limit])

    def candidate(self, provider_id: str) -> CandidateMatch:
        try: return next(item for item in self.candidates if item.contract.provider_id == provider_id)
        except StopIteration as exc: raise KeyError(provider_id) from exc

    def select(self, provider_id: str | None = None) -> CandidateMatch:
        eligible = [item for item in self.candidates if item.verification_status in
                    {"RIGOROUS_EXACT_MATCH", "MATCH_WITH_AUTHORIZED_TRANSFORMATION", "MATCH_WITH_EXACT_EGRAPH"}]
        if provider_id: eligible = [item for item in eligible if item.contract.provider_id == provider_id]
        if not eligible: raise ValueError("NO_RIGOROUSLY_VERIFIED_PROVIDER_CANDIDATE")
        self.selected = eligible[0]
        self.decision_provenance.append({"event": "PROVIDER_SELECTED", "provider": self.selected.contract.provider_id,
            "verification_status": self.selected.verification_status, "rank": self.selected.rank})
        return self.selected


@dataclass(frozen=True)
class GenerationDecision:
    provider_id: str
    candidate_rank: int
    verification_status: str
    requested_by_user: bool
    provenance: tuple[Mapping[str, Any], ...]


def _score(query: dict[str, Any], contract: ProviderContract) -> tuple[float, list[str]]:
    if contract.provider_id == "python.builtin.direct": return 0.1, ["universal direct lowering fallback"]
    features = mathematical_features(query); qmotifs = set(features["motifs"]); cmotifs = set(contract.motifs)
    shared = qmotifs & cmotifs; score = sum(4.0 if item in {"complex_exponential", "finite_sum", "integral", "factorial", "convolution", "shifted_evaluation"} else 2.0 for item in shared)
    pattern_features = mathematical_features(contract.pattern)
    score += 1.5 * len(set(features["ops"]) & set(pattern_features["ops"]))
    score += 2.0 if features["bound_index_count"] and pattern_features["bound_index_count"] else 0
    score += 1.0 if features["tensor_rank"] == pattern_features["tensor_rank"] and features["tensor_rank"] else 0
    return score, [f"shared mathematical motif: {item}" for item in sorted(shared)] or ["weak structural fallback"]


def _direct_lowering_supported(expression: dict[str, Any], language: str) -> bool:
    allowed = {"Constant", "FreeVariable", "BoundVariable", "IndexedValue", "Add", "Subtract",
               "Multiply", "Divide", "FloorDivide", "Modulo", "Power", "Negate", "Compare",
               "IfThenElse", "Select", "Piecewise", "Predicate", "Indicator", "LogicalAnd", "LogicalOr",
               "LogicalNot", "Minimum", "Maximum", "Clamp", "BitAnd", "BitOr", "BitXor", "BitNot",
               "ShiftLeft", "ShiftRight", "RotateLeft", "RotateRight", "BitFieldExtract", "BitFieldInsert",
               "PopCount", "LeadingZeros", "TrailingZeros", "BitTest", "FunctionCall",
               "FiniteSum", "FiniteProduct", "FoldLeft", "TransformReduce", "Map", "Filter",
               "DiscreteDifference", "Quadrature"}
    ops = set(mathematical_features(expression)["ops"])
    if language != "python": allowed -= {"Quadrature"}
    return ops <= allowed


def _reference_plan_generation(expression: dict[str, Any], *, search: str = "normal", candidate_budget: int | None = None,
                               budget: SearchBudget | None = None, registry: Iterable[ProviderContract] | None = None,
                               assumptions: Iterable[str] = (), authorized_rewrites: Iterable[str] | None = None,
                               language: str | None = None) -> GenerationPlan:
    budget = budget or SearchBudget(retrieval=candidate_budget or (200 if search == "broad" else 100))
    registry = [item for item in (registry or default_provider_registry()) if language is None or item.language == language]
    retrieved: list[CandidateMatch] = []
    registry = MathematicalPatternIndex(registry).retrieve(mathematical_features(expression))
    for contract in registry:
        best = (-1.0, [], ())
        for path, subexpression in _walk(expression):
            score, reasons = _score(subexpression, contract)
            if score > best[0] or (score == best[0] and len(path) > len(best[2])):
                best = (score, reasons, path)
        # There is intentionally no similarity threshold.
        retrieved.append(CandidateMatch(contract, 0, best[0], best[1], best[2]))
    retrieved.sort(key=lambda item: (-item.score, item.contract.provider_id))
    retrieved = retrieved[:budget.retrieval]
    for rank, item in enumerate(retrieved, 1): item.rank = rank
    if authorized_rewrites is None:
        set_path = Path(__file__).resolve().parents[2] / "registry" / "transformations" / "sets" / "scientific_default.yaml"
        selected_set = yaml.safe_load(set_path.read_text(encoding="utf-8"))["transformation_set"]
        rewrites = set(selected_set.get("exact_rules", []))
    else:
        rewrites = set(authorized_rewrites)
    detailed = retrieved[:budget.detailed_unification]
    known_assumptions = set(assumptions)
    relation_graph = MathematicalRelationGraph()
    catalog_by_id = {rule.rule_id: rule for rule in load_rewrite_catalog()}
    relation_mapping = {"APPROXIMATION": RelationKind.APPROXIMATION_OF.value,
                        "DISCRETIZATION": RelationKind.DISCRETIZATION_OF.value,
                        "TRUNCATION": RelationKind.TRUNCATED_TO.value,
                        "TRANSFORMATION": RelationKind.TRANSFORMED_TO.value}
    def record_relation(item: CandidateMatch, target: dict[str, Any], kind: str,
                        conditions: Iterable[str]) -> None:
        relation_terms = TypedEGraph()
        source = relation_terms.add(target, origin="requested")
        provider_term = {"op": "ProviderApplication", "provider_id": item.contract.provider_id,
                         "mathematical_target": deepcopy(item.contract.pattern)}
        provider = relation_terms.add(provider_term, origin="provider")
        edge = relation_graph.add(source, provider, kind, conditions=conditions,
                                  evidence="LibraryContract / rewrite-catalog relation evidence")
        item.relation_edges.append({**asdict(edge), "conditions": list(edge.conditions),
                                    "metadata": dict(edge.metadata)})
    for item in detailed:
        if item.contract.lowering == "direct" and not item.contract.pattern:
            if _direct_lowering_supported(expression, item.contract.language):
                item.verification_status = "RIGOROUS_EXACT_MATCH"
            else:
                item.verification_status = "GENERATION_LOWERING_UNSUPPORTED"
                item.remaining_obligations = ["finite algorithm lowering required"]
            item.stage = "RIGOROUS_RECOMPARISON"; continue
        target = dict(_walk(expression).__iter__().__next__()[1]) if not item.matched_path else next(node for path, node in _walk(expression) if path == item.matched_path)
        result = typed_unify(generalize(item.contract.pattern), generalize(target).pattern)
        item.unification = result; item.stage = "TYPED_UNIFICATION"
        if result.status == "TYPED_UNIFICATION_SUCCEEDED":
            item.remaining_obligations = list(result.obligations) + [value for value in item.contract.constraints
                                                                     if value not in known_assumptions]
            if item.contract.implementation_relation != "EXACT_EQUAL":
                record_relation(item, target, item.contract.implementation_relation, item.remaining_obligations)
                item.verification_status = "NON_EXACT_RELATION_CANDIDATE"
            else:
                item.verification_status = ("RIGOROUS_EXACT_MATCH" if not item.remaining_obligations
                                            else "CONTRACT_OBLIGATIONS_REMAINING")
                if item.contract.realization_relation:
                    record_relation(item, target, item.contract.realization_relation, item.remaining_obligations)
        elif item.rank <= budget.full_verification:
            item.stage = "EXACT_EQUALITY_SATURATION"
            relevant = set(mathematical_features(target)["motifs"]) | set(item.contract.motifs)
            allowed = rewrites & set(item.contract.useful_rewrites or rewrites)
            item.egraph_match = saturate_and_match(target, item.contract.pattern, authorized_rule_ids=allowed,
                facts=assumptions, motifs=relevant, useful_rewrites=item.contract.useful_rewrites,
                budget=SaturationBudget(budget.egraph_iterations, budget.egraph_enodes,
                                        budget.egraph_rule_applications))
            if item.egraph_match.status == "EGRAPH_EXACT_MATCH":
                item.remaining_obligations = [value for value in item.contract.constraints if value not in known_assumptions]
                if item.contract.implementation_relation != "EXACT_EQUAL":
                    record_relation(item, target, item.contract.implementation_relation, item.remaining_obligations)
                    item.verification_status = "NON_EXACT_RELATION_CANDIDATE"
                else:
                    item.verification_status = ("MATCH_WITH_EXACT_EGRAPH" if not item.remaining_obligations
                                                else "CONTRACT_OBLIGATIONS_REMAINING")
            else:
                for rewrite_id in item.contract.useful_rewrites:
                    descriptor = catalog_by_id.get(rewrite_id)
                    if descriptor and descriptor.relation_kind in relation_mapping:
                        conditions = (*descriptor.preconditions, *descriptor.domain_constraints,
                                      *descriptor.type_constraints, *descriptor.shape_constraints,
                                      *descriptor.assumptions, *item.contract.constraints)
                        record_relation(item, target, relation_mapping[descriptor.relation_kind], conditions)
                        item.verification_status = "NON_EXACT_RELATION_CANDIDATE"
                        item.remaining_obligations = list(conditions)
                        break
    status = "PROVIDER_CANDIDATES_PLANNED" if retrieved else "PROVIDER_RETRIEVAL_MISS"
    return GenerationPlan(expression, retrieved, budget, status, relation_graph=relation_graph,
        decision_provenance=[{"event": "BROAD_RETRIEVAL", "search": search, "candidate_count": len(retrieved),
                              "budgets": asdict(budget)}])


def plan_generation(expression: dict[str, Any], *, search: str = "normal", candidate_budget: int | None = None,
                    budget: SearchBudget | None = None, registry: Iterable[ProviderContract] | None = None,
                    assumptions: Iterable[str] = (), authorized_rewrites: Iterable[str] | None = None,
                    language: str | None = None) -> GenerationPlan:
    """Thin projection of the native provider planning decision."""
    from formulatracer.native import NativeContext
    budget = budget or SearchBudget(retrieval=candidate_budget or (200 if search == "broad" else 100))
    contracts = list(registry or default_provider_registry())
    request = {"schema_version": "1.0", "kernel": "D", "operation": "PLAN_GENERATION",
        "expression": deepcopy(expression), "search": search, "budget": asdict(budget),
        "registry": [asdict(item) for item in contracts], "assumptions": list(assumptions),
        "authorized_rewrites": list(authorized_rewrites) if authorized_rewrites is not None else None,
        "language": language}
    with NativeContext() as context:
        native = context.execute_kernel(request)["result"]
    by_id = {item.provider_id: item for item in contracts}
    candidates = []
    for item in native.get("candidates", []):
        contract = by_id[str(item["contract"]["provider_id"])]
        candidates.append(CandidateMatch(contract, int(item["rank"]), float(item["score"]),
            list(item.get("reasons", [])), tuple(item.get("matched_path", [])),
            stage=str(item.get("stage", "LOOSE_RETRIEVAL")), relation_edges=deepcopy(item.get("relation_edges", [])),
            verification_status=str(item.get("verification_status", "NOT_VERIFIED")),
            remaining_obligations=list(item.get("remaining_obligations", []))))
    relation_graph = MathematicalRelationGraph()
    for edge in native.get("relation_graph", {}).get("edges", []):
        relation_graph.edges.append(RelationEdge(str(edge["source_eclass_id"]), str(edge["target_eclass_id"]),
            str(edge["relation_kind"]), tuple(edge.get("conditions", [])), edge.get("evidence"),
            dict(edge.get("metadata", {}))))
    return GenerationPlan(deepcopy(expression), candidates, budget, str(native["status"]),
        relation_graph=relation_graph, decision_provenance=deepcopy(native.get("decision_provenance", [])))


@dataclass
class GeneratedMathematicalImplementation:
    provider_id: str
    source: str
    language: str
    expected_expression: dict[str, Any]
    status: str = "SOURCE_GENERATED_UNVERIFIED"
    independent_audit: Any = None

    def verify(self) -> "GeneratedMathematicalImplementation":
        from tempfile import TemporaryDirectory
        from .python_audit import audit_python
        def exact_lowering(node: dict[str, Any]) -> dict[str, Any]:
            if node.get("op") == "FoldLeft" and node.get("operation") == "Add" and node.get("initial_value") in [
                    {"op": "Constant", "value": 0}, {"op": "Constant", "value": 0.0}]:
                return {"op": "FiniteSum", "bound_index": node["bound_index"],
                    "index_domain": {key: value for key, value in node["index_domain"].items() if key != "step"},
                    "body": node["body"]}
            return node
        with TemporaryDirectory() as directory:
            filename = {"python": "generated.py", "rust": "lib.rs", "cpp": "generated.cpp"}.get(self.language, "generated.txt")
            path = Path(directory) / filename; path.write_text(self.source, encoding="utf-8")
            try:
                if self.language == "python":
                    result = audit_python(path, function="compute", mode="REPORT_ONLY", verify_lean=False)
                    observed = exact_lowering(result.implementation["outputs"][0]["expression"])
                else:
                    from .project import FormulaTracer
                    entry = path
                    if self.language == "rust":
                        cargo = Path(directory) / "Cargo.toml"
                        cargo.write_text('[package]\nname="generated_math"\nversion="0.1.0"\nedition="2021"\n[lib]\npath="lib.rs"\n', encoding="utf-8")
                        entry = cargo
                    result = FormulaTracer(entry, project_root=directory).analyze()
                    observed = result.outputs[0].formula
                self.independent_audit = result
                self.status = "INDEPENDENTLY_REAUDITED_VERIFIED" if canonical_equal(self.expected_expression, observed) else "INDEPENDENT_REAUDIT_DIVERGENCE"
            except Exception as exc:
                self.independent_audit = {"error": str(exc)}; self.status = "INDEPENDENT_REAUDIT_UNRESOLVED"
        return self


@dataclass
class MathematicalFormula:
    expression: dict[str, Any]
    surface: MathSurfaceAST | None = None
    original: str | None = None
    origins: OriginSet = field(default_factory=OriginSet)
    assumptions: list[str] = field(default_factory=list)
    declarations: dict[str, SymbolDeclaration] = field(default_factory=dict)
    language: str = "en"

    def __repr__(self) -> str: return f"MathematicalFormula({to_tex(self.expression)!r})"
    @staticmethod
    def _coerce(value: Any) -> dict[str, Any]:
        if isinstance(value, MathematicalFormula): return value.expression
        if isinstance(value, dict): return value
        return {"op": "Constant", "value": value}
    def _binary(self, op: str, other: Any) -> "MathematicalFormula":
        return MathematicalFormula({"op": op, "args": [deepcopy(self.expression), deepcopy(self._coerce(other))]}, origins=self.origins, assumptions=list(self.assumptions))
    def __add__(self, other: Any) -> "MathematicalFormula": return self._binary("Add", other)
    def __sub__(self, other: Any) -> "MathematicalFormula": return self._binary("Subtract", other)
    def __mul__(self, other: Any) -> "MathematicalFormula": return self._binary("Multiply", other)
    def __truediv__(self, other: Any) -> "MathematicalFormula": return self._binary("Divide", other)
    def __pow__(self, other: Any) -> "MathematicalFormula": return self._binary("Power", other)
    def __call__(self, *arguments: Any) -> "MathematicalFormula":
        if self.expression.get("op") != "FunctionSymbol": raise TypeError("ONLY_FUNCTION_SYMBOLS_ARE_CALLABLE")
        return MathematicalFormula({"op": "FunctionCall", "name": self.expression["name"],
            "args": [deepcopy(self._coerce(item)) for item in arguments]}, origins=self.origins,
            assumptions=list(self.assumptions), declarations=dict(self.declarations))
    def to_tex(self) -> str: return to_tex(self.expression)
    def to_dsl(self) -> str: return to_dsl(self.expression)
    def to_unicode(self) -> str: return to_unicode(self.expression)
    def to_markdown(self) -> str: return to_markdown(self.expression)
    def to_json(self) -> str: return to_json(self.expression)
    def explain(self, *, language: str | None = None) -> str:
        lang = language or self.language; features = mathematical_features(self.expression)
        if lang.startswith("ja"): return f"演算 {', '.join(features['ops'])} を含む数式です。未証明の仮定: {', '.join(self.assumptions) or 'なし'}"
        return f"Formula with operations {', '.join(features['ops'])}. Declared assumptions: {', '.join(self.assumptions) or 'none'}."
    def inspect(self) -> dict[str, Any]: return {"expression": deepcopy(self.expression), "surface": asdict(self.surface) if self.surface else None,
        "features": mathematical_features(self.expression), "assumptions": list(self.assumptions), "origins": asdict(self.origins)}
    def debug(self, path: Iterable[Any] = ()) -> Any: return localize_mathematical_node(path, self.origins)
    def assume(self, *assumptions: str) -> "MathematicalFormula": self.assumptions.extend(x for x in assumptions if x not in self.assumptions); return self
    def assume_tex(self, tex: str) -> "MathematicalFormula": return self.assume(tex)
    def domain(self, symbol: str, domain: Domain | str) -> "MathematicalFormula":
        value = domain if isinstance(domain, Domain) else Domain(domain)
        current = self.declarations.get(symbol, SymbolDeclaration(symbol))
        self.declarations[symbol] = SymbolDeclaration(current.canonical_name, current.namespace,
            current.role, current.shape, current.named_dimensions, value.description)
        return self
    def certified_range(self, symbol: str, lower: Any, upper: Any, *, evidence: str = "DECLARED") -> "MathematicalFormula":
        self.assume(f"range({symbol}) in [{lower}, {upper}] [{evidence}]")
        return self
    def plan_generation(self, **options: Any) -> GenerationPlan:
        return plan_generation(self.expression, assumptions=self.assumptions, **options)
    def truncate(self, terms: int) -> "MathematicalFormula":
        if self.expression.get("op") != "InfiniteSeries": raise ValueError("NOT_AN_INFINITE_SERIES")
        node = self.expression
        return MathematicalFormula({"op": "FiniteSum", "bound_index": node["bound_index"],
            "index_domain": {"lower": node["lower"], "upper_exclusive": _c(terms)},
            "body": node["body"], "lowered_from": "InfiniteSeries"}, origins=self.origins, assumptions=list(self.assumptions))
    def truncate_symmetric(self, radius: int) -> "MathematicalFormula":
        if self.expression.get("op") != "BilateralInfiniteSeries": raise ValueError("NOT_A_BILATERAL_SERIES")
        node = self.expression
        return MathematicalFormula({"op": "FiniteSum", "bound_index": node["bound_index"],
            "index_domain": {"lower": _c(-radius), "upper_exclusive": _c(radius + 1)},
            "body": node["body"], "lowered_from": "BilateralInfiniteSeries",
            "truncation_convention": "symmetric_frequency_window"}, origins=self.origins,
            assumptions=list(self.assumptions))
    def generate(self, *, provider: str | None = None, auto_select: bool = False,
                 verify: bool = False, search: str = "normal", language: str = "python") -> GeneratedMathematicalImplementation:
        if self.expression.get("op") in {"InfiniteSeries", "BilateralInfiniteSeries", "InfiniteProduct"}:
            raise ValueError("INFINITE_PROCESS_REQUIRES_CERTIFIED_FINITE_LOWERING")
        plan = self.plan_generation(search=search, language=language)
        selected = plan.select(provider) if provider or auto_select else None
        if selected is None: raise ValueError("PROVIDER_SELECTION_REQUIRED")
        if selected.contract.lowering != "direct":
            sources = {
                "fft": "import numpy as np\n\ndef compute(x):\n    return np.fft.fft(x)\n",
                "quadrature": "from scipy.integrate import quad\n\ndef compute(f, a, b):\n    return quad(f, a, b)[0]\n",
                "convolution": "from scipy.signal import fftconvolve\n\ndef compute(x, y):\n    return fftconvolve(x, y)\n",
                "finite_difference": "def compute(f, x, h):\n    return (f(x + h) - f(x - h)) / (2 * h)\n",
                "weighted_sum": "def compute(w, y, N):\n    return sum(w[i] * y[i] for i in range(N))\n",
            }
            source = sources.get(selected.contract.lowering)
            if source is None: raise ValueError("SPECIALIZED_PROVIDER_LOWERING_NOT_IMPLEMENTED")
            generated = GeneratedMathematicalImplementation(selected.contract.provider_id, source, "python", self.expression)
            return generated.verify() if verify else generated
        from .synthesis import TheorySpecification, synthesize
        names = sorted({str(node.get("name")) for _, node in _walk(self.expression)
                        if node.get("op") in {"FreeVariable", "IndexedValue"}})
        result = synthesize(TheorySpecification("result", self.expression, names, self.assumptions), language=language, verify=False)
        generated = GeneratedMathematicalImplementation(selected.contract.provider_id, result.generated.source, language, self.expression)
        return generated.verify() if verify else generated
    @classmethod
    def from_tex(cls, tex: str, **options: Any) -> "MathematicalFormula":
        assumptions = list(options.pop("assumptions", ()))
        surface, expression, origins = parse_tex(tex, assumptions=assumptions)
        return cls(expression=expression, surface=surface, original=tex, origins=origins,
                   assumptions=assumptions, **options)
    @classmethod
    def from_expression(cls, expression: dict[str, Any], **options: Any) -> "MathematicalFormula": return cls(deepcopy(expression), **options)
    @classmethod
    def taylor(cls, function: str, variable: str = "x", order: int = 5, center: Any = 0) -> "MathematicalFormula":
        n = "n"; body = {"op": "Divide", "args": [{"op": "Multiply", "args": [
            {"op": "Derivative", "function": function, "variable": variable, "order": _b(n), "at": _c(center)},
            {"op": "Power", "args": [{"op": "Subtract", "args": [_v(variable), _c(center)]}, _b(n)]}]},
            {"op": "Factorial", "args": [_b(n)]}]}
        return cls(MathBuilder.sum(n, _c(0), _c(order + 1), body))
    @classmethod
    def maclaurin(cls, function: str, variable: str = "x", order: int = 5) -> "MathematicalFormula": return cls.taylor(function, variable, order, 0)
    @classmethod
    def fourier(cls, function: str = "f") -> "MathematicalFormula": return cls(integral_transform("fourier", _v(function)))
    @classmethod
    def fourier_series(cls, function: str = "f", variable: str = "x", period: Any = "2*pi") -> "MathematicalFormula":
        process = FourierSeries(function, variable, period).process()
        return cls({"op": "BilateralInfiniteSeries", "bound_index": process.sequence.index,
                    "lower": _c(process.sequence.lower), "body": process.sequence.term,
                    "relation": asdict(process.convergence) if process.convergence else None})
    @classmethod
    def laplace(cls, function: str = "f") -> "MathematicalFormula": return cls(integral_transform("laplace", _v(function)))
    @classmethod
    def inverse_fourier(cls, function: str = "F") -> "MathematicalFormula":
        value = integral_transform("fourier", _v(function)); value["op"] = "InverseFourierTransform"; return cls(value)
    @classmethod
    def inverse_laplace(cls, function: str = "F") -> "MathematicalFormula":
        value = integral_transform("laplace", _v(function)); value["op"] = "InverseLaplaceTransform"; return cls(value)


def function(name: str, *, domain: Domain | None = None) -> MathematicalFormula:
    expression = {"op": "FunctionSymbol", "name": name}
    formula = MathematicalFormula(expression)
    if domain: formula.declarations[name] = SymbolDeclaration(name, role="function", domain=domain.description)
    return formula
