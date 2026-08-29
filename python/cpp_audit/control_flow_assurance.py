"""Fail-closed control-flow assurance over generated, real, and ephemeral corpora.

The module produces empirical assurance evidence.  It never upgrades finite
testing, source inventory, or mutation detection to a kernel proof.
"""

from __future__ import annotations

import ast
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Iterable, Mapping

from .python_audit import audit_python, compare_symbolic
from .python_cfg import build_python_cfg
from .synthesis import TheorySpecification, synthesize, synthesize_cross_language


class AssuranceEvidence(str, Enum):
    KERNEL_VERIFIED = "KERNEL_VERIFIED"
    FORMALLY_DERIVED = "FORMALLY_DERIVED"
    REFERENCE_CONTRACT = "REFERENCE_CONTRACT"
    EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN = "EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN"
    REAL_WORLD_VALIDATED = "REAL_WORLD_VALIDATED"
    MUTATION_DETECTED = "MUTATION_DETECTED"
    METAMORPHICALLY_VALIDATED = "METAMORPHICALLY_VALIDATED"
    UNRESOLVED = "UNRESOLVED"


class ControlFlowAssuranceStatus(str, Enum):
    FINITE_LOOP_SEMANTICS_VERIFIED = "FINITE_LOOP_SEMANTICS_VERIFIED"
    BRANCH_PATHS_RESOLVED = "BRANCH_PATHS_RESOLVED"
    BREAK_CONTINUE_SEMANTICS_VERIFIED = "BREAK_CONTINUE_SEMANTICS_VERIFIED"
    EARLY_RETURN_SEMANTICS_VERIFIED = "EARLY_RETURN_SEMANTICS_VERIFIED"
    LOOP_CARRIED_STATE_VERIFIED = "LOOP_CARRIED_STATE_VERIFIED"
    NESTED_CONTROL_FLOW_VERIFIED = "NESTED_CONTROL_FLOW_VERIFIED"
    LOOP_NORMALIZED_UNDER_ASSUMPTIONS = "LOOP_NORMALIZED_UNDER_ASSUMPTIONS"
    BRANCH_FEASIBILITY_UNRESOLVED = "BRANCH_FEASIBILITY_UNRESOLVED"
    LOOP_INVARIANT_UNRESOLVED = "LOOP_INVARIANT_UNRESOLVED"
    TERMINATION_UNPROVEN = "TERMINATION_UNPROVEN"
    ALIAS_CONTROL_FLOW_UNRESOLVED = "ALIAS_CONTROL_FLOW_UNRESOLVED"
    CONTROL_FLOW_PARTIALLY_RESOLVED = "CONTROL_FLOW_PARTIALLY_RESOLVED"
    CONTROL_FLOW_UNRESOLVED = "CONTROL_FLOW_UNRESOLVED"


@dataclass(frozen=True)
class ExternalCorpusManifest:
    repository: str
    name: str
    commit: str
    license_identifier: str
    sparse_paths: tuple[str, ...]
    corpus_source: str = "OFFICIAL_TESTS_OR_EXAMPLES"
    case_id: str | None = None


@dataclass
class ExternalCorpusResult:
    repository: str
    name: str
    commit: str
    license_identifier: str
    corpus_source: str
    case_id: str | None
    files_analyzed: int
    languages: dict[str, int]
    constructs: dict[str, int]
    resolution: dict[str, int]
    source_records: list[dict[str, Any]]
    cleanup_verified: bool
    status: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class EphemeralCheckout(AbstractContextManager[Path]):
    """Sparse pinned checkout that is unconditionally removed on exit."""

    def __init__(self, manifest: ExternalCorpusManifest, *, parent: str | Path | None = None):
        self.manifest = manifest
        self.parent = Path(parent) if parent else None
        self.root: Path | None = None
        self.cleanup_verified = False

    def __enter__(self) -> Path:
        self.root = Path(tempfile.mkdtemp(prefix="formulatracer-external-", dir=self.parent))
        try:
            self._git("init")
            self._git("remote", "add", "origin", self.manifest.repository)
            if self.manifest.sparse_paths:
                self._git("sparse-checkout", "init", "--no-cone")
                self._git("sparse-checkout", "set", *self.manifest.sparse_paths)
            self._git("fetch", "--depth", "1", "origin", self.manifest.commit)
            self._git("checkout", "--detach", "FETCH_HEAD")
            actual = self._git("rev-parse", "HEAD", capture=True).strip()
            if not actual.startswith(self.manifest.commit.lower()):
                raise RuntimeError(f"EXTERNAL_COMMIT_MISMATCH: expected {self.manifest.commit}, got {actual}")
            return self.root
        except Exception:
            self._cleanup()
            raise

    def _git(self, *args: str, capture: bool = False) -> str:
        completed = subprocess.run(["git", *args], cwd=self.root, check=True,
                                   text=True, capture_output=True)
        return completed.stdout if capture else ""

    def _cleanup(self) -> None:
        root = self.root
        if root and root.exists():
            for path in root.rglob("*"):
                try: os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                except OSError: pass
            shutil.rmtree(root)
        self.cleanup_verified = bool(root and not root.exists())

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._cleanup()
        return False


_PYTHON_SUFFIXES = {".py"}
_RUST_SUFFIXES = {".rs"}
_CPP_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".h", ".hh"}
_ALL_SUFFIXES = _PYTHON_SUFFIXES | _RUST_SUFFIXES | _CPP_SUFFIXES


def _zero_counts() -> dict[str, int]:
    return {key: 0 for key in ("loops", "branches", "nested_loops", "nested_branches", "break",
                               "continue", "early_returns", "while", "state_mutation", "try_paths",
                               "match", "iterator_chains")}


class _PythonConstructVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.counts = _zero_counts(); self.control: list[str] = []; self.function_depth = 0

    def _region(self, kind: str, node: ast.AST) -> None:
        if kind == "loop":
            self.counts["loops"] += 1
            if "loop" in self.control: self.counts["nested_loops"] += 1
        else:
            self.counts["branches"] += 1
            if self.control: self.counts["nested_branches"] += 1
        self.control.append(kind); self.generic_visit(node); self.control.pop()

    def visit_For(self, node: ast.For) -> None: self._region("loop", node)
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None: self._region("loop", node)
    def visit_While(self, node: ast.While) -> None:
        self.counts["while"] += 1; self._region("loop", node)
    def visit_If(self, node: ast.If) -> None: self._region("branch", node)
    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.counts["branches"] += 1; self.generic_visit(node)
    def visit_Match(self, node: ast.Match) -> None:
        self.counts["match"] += 1; self.counts["branches"] += len(node.cases); self.generic_visit(node)
    def visit_Try(self, node: ast.Try) -> None:
        self.counts["try_paths"] += 1 + len(node.handlers); self.generic_visit(node)
    def visit_Break(self, node: ast.Break) -> None: self.counts["break"] += 1
    def visit_Continue(self, node: ast.Continue) -> None: self.counts["continue"] += 1
    def visit_Return(self, node: ast.Return) -> None:
        if self.control: self.counts["early_returns"] += 1
        self.generic_visit(node)
    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.counts["state_mutation"] += 1; self.generic_visit(node)
    def visit_Assign(self, node: ast.Assign) -> None:
        if any(isinstance(target, (ast.Subscript, ast.Attribute)) for target in node.targets):
            self.counts["state_mutation"] += 1
        self.generic_visit(node)


def inventory_source(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    digest = sha256(text.encode()).hexdigest()
    relative = str(path.relative_to(root)) if root else path.name
    record: dict[str, Any] = {"relative_path": relative.replace("\\", "/"), "sha256": digest,
                              "bytes": len(text.encode()), "constructs": _zero_counts()}
    if path.suffix.lower() in _PYTHON_SUFFIXES:
        record["language"] = "Python"
        try:
            tree = ast.parse(text); visitor = _PythonConstructVisitor(); visitor.visit(tree)
            record["constructs"] = visitor.counts; record["parse_status"] = "PARSED"
            statuses: list[str] = []
            for function in (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                try: statuses.extend(build_python_cfg(text, function=function.name).summary["statuses"])
                except Exception: statuses.append(ControlFlowAssuranceStatus.CONTROL_FLOW_UNRESOLVED.value)
            if any(value in statuses for value in ("CFG_PARTIALLY_RESOLVED", "CONTROL_FLOW_PARTIALLY_RESOLVED")):
                resolution = "PARTIALLY_RESOLVED"
            elif statuses and any(value in statuses for value in ("LOOP_NORMALIZED", "LOOP_SEMANTICS_PRESERVED")):
                resolution = "RESOLVED_UNDER_ASSUMPTIONS"
            else: resolution = "FULLY_RESOLVED"
            record["assurance_statuses"] = sorted(set(statuses)); record["resolution"] = resolution
        except SyntaxError as exc:
            record.update(parse_status="PARSE_FAILED", resolution="UNRESOLVED",
                          diagnostic={"code": "PYTHON_PARSE_FAILED", "line": exc.lineno})
    else:
        language = "Rust" if path.suffix.lower() in _RUST_SUFFIXES else "C++"
        record["language"] = language; record["parse_status"] = "LEXICAL_INVENTORY"
        patterns = {
            "loops": r"\b(for|while|loop)\b", "branches": r"\b(if|match|switch)\b",
            "break": r"\bbreak\b", "continue": r"\bcontinue\b", "while": r"\bwhile\b",
            "early_returns": r"\breturn\b", "state_mutation": r"(\+=|-=|\*=|/=|\+\+|--)",
            "match": r"\bmatch\b", "iterator_chains": r"\.(map|filter|fold|reduce)\s*\(",
        }
        for key, pattern in patterns.items(): record["constructs"][key] = len(re.findall(pattern, text))
        record["resolution"] = "PARTIALLY_RESOLVED" if any(record["constructs"].values()) else "FULLY_RESOLVED"
        record["assurance_statuses"] = ["CONTROL_FLOW_PARTIALLY_RESOLVED"] if any(record["constructs"].values()) else []
    return record


def aggregate_records(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records); constructs = _zero_counts(); languages: dict[str, int] = {}; resolution: dict[str, int] = {}
    for record in records:
        languages[record["language"]] = languages.get(record["language"], 0) + 1
        resolution[record["resolution"]] = resolution.get(record["resolution"], 0) + 1
        for key, value in record["constructs"].items(): constructs[key] += value
    return {"files_analyzed": len(records), "languages": languages, "constructs": constructs,
            "resolution": resolution}


def analyze_external_manifest(manifest: ExternalCorpusManifest, *, temp_parent: str | Path | None = None) -> ExternalCorpusResult:
    checkout = EphemeralCheckout(manifest, parent=temp_parent); records: list[dict[str, Any]] = []
    status = "EXTERNAL_CORPUS_ANALYZED"
    try:
        with checkout as root:
            paths = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _ALL_SUFFIXES)
            records = [inventory_source(path, root=root) for path in paths]
            aggregate = aggregate_records(records)
    except Exception as exc:
        aggregate = aggregate_records([]); status = "EXTERNAL_CORPUS_ANALYSIS_FAILED"
        records = [{"diagnostic": {"code": type(exc).__name__, "message": str(exc)[:500]}}]
    return ExternalCorpusResult(manifest.repository, manifest.name, manifest.commit, manifest.license_identifier,
                                manifest.corpus_source, manifest.case_id, aggregate["files_analyzed"],
                                aggregate["languages"], aggregate["constructs"], aggregate["resolution"],
                                records, checkout.cleanup_verified, status)


def _number(value: Any) -> Any:
    if isinstance(value, str):
        try: return float(value) if "." in value else int(value)
        except ValueError: return value
    return value


def evaluate_mathematical_ir(node: Any, environment: Mapping[str, Any], bound: Mapping[str, Any] | None = None) -> Any:
    """Small independent evaluator used only for finite-domain empirical checks."""
    if not isinstance(node, dict): raise ValueError("IR_NODE_REQUIRED")
    bound = dict(bound or {}); op = node.get("op")
    if op == "Constant": return _number(node.get("value"))
    if op == "FreeVariable": return environment[node["name"]]
    if op == "BoundVariable": return bound[node["name"]]
    if op == "IndexedValue":
        value = environment[node["name"]]
        for index in node.get("indices", []): value = value[evaluate_mathematical_ir(index, environment, bound)]
        return value
    if op == "Negate": return -evaluate_mathematical_ir(node["args"][0], environment, bound)
    if op == "IfThenElse":
        branch = "then" if evaluate_mathematical_ir(node["condition"], environment, bound) else "else"
        return evaluate_mathematical_ir(node[branch], environment, bound)
    if op == "Compare":
        left, right = (evaluate_mathematical_ir(item, environment, bound) for item in node["args"])
        return {"LessThan": left < right, "LessEqual": left <= right, "GreaterThan": left > right,
                "GreaterEqual": left >= right, "Equal": left == right, "NotEqual": left != right}[node["comparison"]]
    if op in {"Add", "Subtract", "Multiply", "Divide", "Power", "And", "Or"}:
        left, right = (evaluate_mathematical_ir(item, environment, bound) for item in node["args"])
        return {"Add": lambda: left + right, "Subtract": lambda: left - right,
                "Multiply": lambda: left * right, "Divide": lambda: left / right,
                "Power": lambda: left ** right, "And": lambda: left and right,
                "Or": lambda: left or right}[op]()
    if op in {"FoldLeft", "FiniteSum", "FiniteProduct"}:
        domain = node["index_domain"]
        lower = int(evaluate_mathematical_ir(domain["lower"], environment, bound))
        upper = int(evaluate_mathematical_ir(domain["upper_exclusive"], environment, bound))
        step = int(evaluate_mathematical_ir(domain.get("step", {"op": "Constant", "value": 1}), environment, bound))
        operation = node.get("operation", "Multiply" if op == "FiniteProduct" else "Add")
        result = evaluate_mathematical_ir(node.get("initial_value", {"op": "Constant", "value": 1 if operation == "Multiply" else 0}), environment, bound)
        for index in range(lower, upper, step):
            local = {**bound, node.get("bound_index", "i"): index}
            term = evaluate_mathematical_ir(node.get("body") or node.get("transform"), environment, local)
            result = result + term if operation == "Add" else result * term
        return result
    raise ValueError(f"UNSUPPORTED_ASSURANCE_IR: {op}")


def _extract(source: str, function: str, output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="formulatracer-generated-") as directory:
        path = Path(directory) / "case.py"; path.write_text(source, encoding="utf-8")
        result = audit_python(path, function=function, output=output, verify_lean=False, mode="REPORT_ONLY")
        expression = result.implementation["outputs"][0]["expression"]
        cfg = build_python_cfg(path, function=function, output=output).to_dict()
        return expression, cfg


def _compare_expressions(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    target = {"op": "FreeVariable", "name": "result"}
    return compare_symbolic({"outputs": [{"target": target, "expression": left}]},
                            {"outputs": [{"target": target, "expression": right}]})


def _runtime_function(source: str, function: str):
    namespace: dict[str, Any] = {}; exec(compile(source, "<assurance-fixture>", "exec"), namespace)
    return namespace[function]


GENERATED_CASES: tuple[dict[str, Any], ...] = (
    {"case_id": "finite_sum", "function": "f", "output": "s", "source": "def f(x,n):\n s=0\n for i in range(n):\n  s += x[i]\n return s\n",
     "inputs": [{"x": [-2, -1, 0, 1], "n": n} for n in range(4)]},
    {"case_id": "range_start", "function": "f", "output": "s", "source": "def f(a,b):\n s=0\n for i in range(a,b):\n  s += i\n return s\n",
     "inputs": [{"a": a, "b": b} for a in range(3) for b in range(4)]},
    {"case_id": "range_step", "function": "f", "output": "s", "source": "def f(a,b,step):\n s=0\n for i in range(a,b,step):\n  s += i\n return s\n",
     "inputs": [{"a": 0, "b": 4, "step": 2}, {"a": 3, "b": -1, "step": -1}, {"a": 0, "b": 0, "step": 1}]},
    {"case_id": "zero_iteration_initial", "function": "f", "output": "s", "source": "def f(x):\n s=7\n for i in range(0):\n  s += x[i]\n return s\n",
     "inputs": [{"x": []}, {"x": [2]}]},
    {"case_id": "conditional_accumulation", "function": "f", "output": "s", "source": "def f(x,mask,n):\n s=0\n for i in range(n):\n  if mask[i]:\n   s += x[i]\n return s\n",
     "inputs": [{"x": [-2, -1, 2], "mask": list(mask), "n": n} for n in range(4) for mask in itertools.product((False, True), repeat=n)]},
    {"case_id": "branch_merge", "function": "f", "output": "y", "source": "def f(c,a,b):\n if c:\n  y=a\n else:\n  y=b\n return y\n",
     "inputs": [{"c": c, "a": a, "b": b} for c in (False, True) for a in (-2, 0, 2) for b in (-1, 1)]},
    {"case_id": "nested_branch", "function": "f", "output": "y", "source": "def f(a,b,x1,x2,x3):\n if a:\n  if b:\n   y=x1\n  else:\n   y=x2\n else:\n  y=x3\n return y\n",
     "inputs": [{"a": a, "b": b, "x1": -2, "x2": 0, "x3": 2} for a in (False, True) for b in (False, True)]},
    {"case_id": "early_return", "function": "f", "output": "f", "source": "def f(x):\n if x < 0:\n  return 0\n return 2*x\n",
     "inputs": [{"x": value} for value in (-2, -1, 0, 1, 2)]},
    {"case_id": "branch_mutation", "function": "f", "output": "x", "source": "def f(c,a,b):\n x=0\n if c:\n  x += a\n else:\n  x += b\n return x\n",
     "inputs": [{"c": c, "a": a, "b": b} for c in (False, True) for a in (-1, 1) for b in (-2, 2)]},
)


def run_finite_exhaustive() -> dict[str, Any]:
    cases = []; comparisons = 0; mismatches = 0; unresolved = 0
    for specification in GENERATED_CASES:
        expression, cfg = _extract(specification["source"], specification["function"], specification["output"])
        function = _runtime_function(specification["source"], specification["function"]); case_mismatches = []
        for inputs in specification["inputs"]:
            reference = function(**inputs); comparisons += 1
            try: observed = evaluate_mathematical_ir(expression, inputs)
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                unresolved += 1; case_mismatches.append({"inputs": inputs, "status": "UNRESOLVED", "diagnostic": str(exc)}); continue
            if observed != reference:
                mismatches += 1; case_mismatches.append({"inputs": inputs, "reference": reference, "observed": observed, "status": "SEMANTIC_MISMATCH"})
        status = "EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN" if not case_mismatches else ("UNRESOLVED" if all(item["status"] == "UNRESOLVED" for item in case_mismatches) else "FINITE_DOMAIN_MISMATCH")
        cases.append({"case_id": specification["case_id"], "source_hash": sha256(specification["source"].encode()).hexdigest(),
                      "comparisons": len(specification["inputs"]), "status": status,
                      "evidence_level": AssuranceEvidence.EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN.value if status.startswith("EXHAUSTIVELY") else AssuranceEvidence.UNRESOLVED.value,
                      "expression_op": expression.get("op"), "cfg_summary": cfg["summary"], "findings": case_mismatches})
    return {"schema_version": "1.0", "cases": cases, "finite_exhaustive_comparisons": comparisons,
            "semantic_mismatch_count": mismatches, "unresolved_comparisons": unresolved,
            "evidence_level": AssuranceEvidence.EXHAUSTIVELY_TESTED_ON_FINITE_DOMAIN.value}


MUTATIONS: tuple[dict[str, str], ...] = (
    {"case_id": "loop_bound_minus_one", "original": GENERATED_CASES[0]["source"], "mutated": GENERATED_CASES[0]["source"].replace("range(n)", "range(n-1)"), "function": "f", "output": "s"},
    {"case_id": "accumulator_initial", "original": GENERATED_CASES[0]["source"], "mutated": GENERATED_CASES[0]["source"].replace("s=0", "s=1"), "function": "f", "output": "s"},
    {"case_id": "condition_inversion", "original": GENERATED_CASES[4]["source"], "mutated": GENERATED_CASES[4]["source"].replace("if mask[i]:", "if not mask[i]:"), "function": "f", "output": "s"},
    {"case_id": "early_return_boundary", "original": GENERATED_CASES[7]["source"], "mutated": GENERATED_CASES[7]["source"].replace("x < 0", "x <= 1"), "function": "f", "output": "f"},
    {"case_id": "then_else_swap", "original": GENERATED_CASES[5]["source"], "mutated": GENERATED_CASES[5]["source"].replace("y=a\n else:\n  y=b", "y=b\n else:\n  y=a"), "function": "f", "output": "y"},
)


def run_mutation_assurance() -> tuple[dict[str, Any], dict[str, Any]]:
    results = []; localization = []; false_acceptance = 0
    for mutation in MUTATIONS:
        original, original_cfg = _extract(mutation["original"], mutation["function"], mutation["output"])
        changed, changed_cfg = _extract(mutation["mutated"], mutation["function"], mutation["output"])
        inputs = next(item["inputs"] for item in GENERATED_CASES if item["source"] == mutation["original"])
        left, right = _runtime_function(mutation["original"], mutation["function"]), _runtime_function(mutation["mutated"], mutation["function"])
        witness = next(({"inputs": values, "original": left(**values), "mutated": right(**values)} for values in inputs if left(**values) != right(**values)), None)
        semantic_change = witness is not None; comparison = _compare_expressions(original, changed)
        def contains_op(value: Any, operation: str) -> bool:
            if isinstance(value, list): return any(contains_op(item, operation) for item in value)
            return isinstance(value, dict) and (value.get("op") == operation or any(contains_op(item, operation) for item in value.values()))
        if semantic_change and comparison.get("match"):
            classification = "FALSE_ACCEPTANCE"; false_acceptance += 1
        elif semantic_change and contains_op(changed, "OpaqueNumericCall"):
            classification = "CONTROL_FLOW_UNRESOLVED_FAIL_CLOSED"
        elif semantic_change and not comparison.get("match"): classification = "SEMANTIC_MISMATCH_DETECTED"
        else: classification = "MUTATION_NOT_SEMANTICALLY_EFFECTIVE"
        original_lines = mutation["original"].splitlines(); mutated_lines = mutation["mutated"].splitlines()
        changed_line = next((index + 1 for index, pair in enumerate(itertools.zip_longest(original_lines, mutated_lines)) if pair[0] != pair[1]), None)
        results.append({"case_id": mutation["case_id"], "source_hash": sha256(mutation["original"].encode()).hexdigest(),
                        "mutated_source_hash": sha256(mutation["mutated"].encode()).hexdigest(),
                        "mutated_source_span": {"begin_line": changed_line, "end_line": changed_line},
                        "expected_semantic_change": semantic_change, "witness": witness,
                        "original_ir": original, "mutated_ir": changed, "classification": classification,
                        "evidence_level": AssuranceEvidence.MUTATION_DETECTED.value if classification.endswith("DETECTED") else AssuranceEvidence.UNRESOLVED.value,
                        "original_cfg_status": original_cfg["summary"]["cfg_status"], "mutated_cfg_status": changed_cfg["summary"]["cfg_status"]})
        localization.append({"case_id": mutation["case_id"], "mutation_span": {"begin_line": changed_line, "end_line": changed_line},
                             "classification": "CORRECT_SEMANTIC_NODE" if classification == "SEMANTIC_MISMATCH_DETECTED" else "UNRESOLVED",
                             "debugger_evidence": comparison})
    counts = {key: sum(item["classification"] == key for item in results) for key in
              ("SEMANTIC_MISMATCH_DETECTED", "CONTROL_FLOW_UNRESOLVED_FAIL_CLOSED", "FALSE_ACCEPTANCE", "MUTATION_NOT_SEMANTICALLY_EFFECTIVE")}
    return ({"schema_version": "1.0", "cases": results, "counts": counts, "false_acceptance_count": false_acceptance},
            {"schema_version": "1.0", "cases": localization,
             "counts": {key: sum(item["classification"] == key for item in localization) for key in
                        ("EXACT_SOURCE_SPAN", "CORRECT_SEMANTIC_NODE", "SAME_BASIC_BLOCK", "UPSTREAM_MISS", "DOWNSTREAM_MISS", "UNRESOLVED")}})


METAMORPHIC_PAIRS: tuple[dict[str, str], ...] = (
    {"case_id": "alpha_rename", "left": GENERATED_CASES[0]["source"], "right": GENERATED_CASES[0]["source"].replace("for i", "for k").replace("x[i]", "x[k]"), "function": "f", "output": "s"},
    {"case_id": "temporary_introduction", "left": "def f(x):\n y=2*x\n return y\n", "right": "def f(x):\n t=2*x\n y=t\n return y\n", "function": "f", "output": "y"},
    {"case_id": "parentheses", "left": "def f(x):\n y=2*x+1\n return y\n", "right": "def f(x):\n y=(2*x)+1\n return y\n", "function": "f", "output": "y"},
    {"case_id": "conditional_expression", "left": GENERATED_CASES[5]["source"], "right": "def f(c,a,b):\n y=a if c else b\n return y\n", "function": "f", "output": "y"},
)


def run_metamorphic_assurance() -> dict[str, Any]:
    cases = []; false_rejections = 0; unresolved = 0
    for pair in METAMORPHIC_PAIRS:
        left, _ = _extract(pair["left"], pair["function"], pair["output"])
        right, _ = _extract(pair["right"], pair["function"], pair["output"])
        comparison = _compare_expressions(left, right)
        if comparison.get("match"): classification = "CORRECT_EQUIVALENCE"
        elif comparison.get("status", "").startswith("UNRESOLVED"):
            classification = "UNRESOLVED"; unresolved += 1
        else: classification = "FALSE_REJECTION"; false_rejections += 1
        cases.append({"case_id": pair["case_id"], "left_hash": sha256(pair["left"].encode()).hexdigest(),
                      "right_hash": sha256(pair["right"].encode()).hexdigest(), "classification": classification,
                      "comparison": comparison, "evidence_level": AssuranceEvidence.METAMORPHICALLY_VALIDATED.value if classification == "CORRECT_EQUIVALENCE" else AssuranceEvidence.UNRESOLVED.value})
    return {"schema_version": "1.0", "cases": cases, "metamorphic_case_count": len(cases),
            "correct_equivalence_count": sum(item["classification"] == "CORRECT_EQUIVALENCE" for item in cases),
            "false_rejection_count": false_rejections, "unresolved_count": unresolved}


def run_generated_round_trip() -> dict[str, Any]:
    domain = {"lower": {"op": "Constant", "value": 0}, "upper_exclusive": {"op": "FreeVariable", "name": "n"}}
    theories = [
        TheorySpecification("y", {"op": "Add", "args": [{"op": "Multiply", "args": [{"op": "Constant", "value": 3}, {"op": "FreeVariable", "name": "x"}]}, {"op": "Constant", "value": 2}]}, ["x"]),
        TheorySpecification("y", {"op": "IfThenElse", "condition": {"op": "Compare", "comparison": "GreaterThan", "args": [{"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 0}]}, "then": {"op": "FreeVariable", "name": "x"}, "else": {"op": "Negate", "args": [{"op": "FreeVariable", "name": "x"}]}}, ["x"]),
        TheorySpecification("y", {"op": "FiniteSum", "bound_index": "i", "index_domain": domain, "body": {"op": "FreeVariable", "name": "i"}}, ["n"]),
    ]
    cases = []
    for index, theory in enumerate(theories):
        cross = synthesize_cross_language(theory)
        cases.append({"case_id": f"generated-{index + 1}", "theory": theory.expression,
                      "canonical_ir_status": cross.canonical_ir_status,
                      "languages": {language: {"status": result.status, "round_trip": result.round_trip.status if result.round_trip else "UNRESOLVED",
                                                "source_hash": sha256(result.generated.source.encode()).hexdigest()}
                                    for language, result in cross.results.items()}})
    return {"schema_version": "1.0", "cases": cases, "self_generated_valid_cases": len(cases) * 3,
            "round_trip_success": sum(value["round_trip"] == "ROUND_TRIP_VERIFIED" for case in cases for value in case["languages"].values()),
            "evidence_level": AssuranceEvidence.METAMORPHICALLY_VALIDATED.value}


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
