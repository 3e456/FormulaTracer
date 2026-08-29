"""Conservative Python CFG, mutation, and alias inventory.

This module describes implementation structure.  It does not claim that a CFG
is a mathematical expression; normalization remains a separate, fail-closed step.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .core import AuditError


class ControlFlowStatus(str, Enum):
    CFG_RESOLVED = "CFG_RESOLVED"
    CFG_PARTIALLY_RESOLVED = "CFG_PARTIALLY_RESOLVED"
    BRANCH_MERGE_RESOLVED = "BRANCH_MERGE_RESOLVED"
    BRANCH_MERGE_UNRESOLVED = "BRANCH_MERGE_UNRESOLVED"
    MUTATION_RESOLVED = "MUTATION_RESOLVED"
    MUTATION_TARGET_UNRESOLVED = "MUTATION_TARGET_UNRESOLVED"
    POTENTIAL_ALIAS = "POTENTIAL_ALIAS"
    LOOP_NORMALIZED = "LOOP_NORMALIZED"
    LOOP_SEMANTICS_PRESERVED = "LOOP_SEMANTICS_PRESERVED"
    TERMINATION_UNPROVEN = "TERMINATION_UNPROVEN"
    EXCEPTION_PATH_RESOLVED = "EXCEPTION_PATH_RESOLVED"
    EXCEPTION_PATH_UNRESOLVED = "EXCEPTION_PATH_UNRESOLVED"
    FINITE_LOOP_SEMANTICS_VERIFIED = "FINITE_LOOP_SEMANTICS_VERIFIED"
    BRANCH_PATHS_RESOLVED = "BRANCH_PATHS_RESOLVED"
    BREAK_CONTINUE_SEMANTICS_VERIFIED = "BREAK_CONTINUE_SEMANTICS_VERIFIED"
    EARLY_RETURN_SEMANTICS_VERIFIED = "EARLY_RETURN_SEMANTICS_VERIFIED"
    LOOP_CARRIED_STATE_VERIFIED = "LOOP_CARRIED_STATE_VERIFIED"
    NESTED_CONTROL_FLOW_VERIFIED = "NESTED_CONTROL_FLOW_VERIFIED"
    LOOP_NORMALIZED_UNDER_ASSUMPTIONS = "LOOP_NORMALIZED_UNDER_ASSUMPTIONS"
    BRANCH_FEASIBILITY_UNRESOLVED = "BRANCH_FEASIBILITY_UNRESOLVED"
    LOOP_INVARIANT_UNRESOLVED = "LOOP_INVARIANT_UNRESOLVED"
    ALIAS_CONTROL_FLOW_UNRESOLVED = "ALIAS_CONTROL_FLOW_UNRESOLVED"
    CONTROL_FLOW_PARTIALLY_RESOLVED = "CONTROL_FLOW_PARTIALLY_RESOLVED"
    CONTROL_FLOW_UNRESOLVED = "CONTROL_FLOW_UNRESOLVED"


@dataclass
class BasicBlock:
    id: str
    kind: str
    statements: list[dict[str, Any]] = field(default_factory=list)
    source_span: dict[str, int] | None = None


@dataclass
class ControlFlowEdge:
    source: str
    target: str
    kind: str
    condition: str | None = None


@dataclass
class Mutation:
    id: str
    kind: str
    target: str
    canonical_target: str | None
    value: str | None
    status: str
    source_span: dict[str, int]


@dataclass
class ControlFlowGraph:
    schema_version: str
    function: str
    entry: str
    exit: str
    blocks: list[BasicBlock]
    edges: list[ControlFlowEdge]
    mutations: list[Mutation]
    aliases: list[dict[str, str]]
    summary: dict[str, Any]
    diagnostics: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def _span(node: ast.AST) -> dict[str, int]:
    return {"begin_line": getattr(node, "lineno", 0), "begin_column": getattr(node, "col_offset", 0),
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
            "end_column": getattr(node, "end_col_offset", getattr(node, "col_offset", 0))}


def _target_name(node: ast.AST) -> tuple[str | None, str]:
    if isinstance(node, ast.Name): return node.id, node.id
    if isinstance(node, ast.Subscript):
        base = ast.unparse(node.value); return base if isinstance(node.value, ast.Name) else None, ast.unparse(node)
    if isinstance(node, ast.Attribute):
        base = ast.unparse(node.value); return base if isinstance(node.value, ast.Name) else None, ast.unparse(node)
    return None, ast.unparse(node)


class PythonCFGBuilder:
    def __init__(self, function: ast.FunctionDef | ast.AsyncFunctionDef, output: str | None = None):
        self.function, self.output = function, output
        self.blocks: list[BasicBlock] = []
        self.edges: list[ControlFlowEdge] = []
        self.mutations: list[Mutation] = []
        self.aliases: dict[str, str] = {}
        self.parameters = {argument.arg for argument in function.args.args}
        self.unknown_aliases: set[str] = set()
        self.critical_names = self._critical_names()
        self.diagnostics: list[dict[str, Any]] = []
        self.counts = {"branch_count": 0, "loop_count": 0, "mutation_count": 0,
                       "exception_path_count": 0, "return_count": 0, "break_count": 0,
                       "continue_count": 0, "while_count": 0, "nested_loop_count": 0,
                       "nested_branch_count": 0, "early_return_count": 0}
        self.statuses: set[str] = set()
        self.unresolved: list[dict[str, Any]] = []
        self.loop_stack: list[tuple[str, str]] = []
        self.control_depth = 0
        self.block_number = 0

    def _critical_names(self) -> set[str]:
        needed = {self.output} if self.output else set()
        for statement in ast.walk(self.function):
            if isinstance(statement, ast.Return) and statement.value:
                needed |= {node.id for node in ast.walk(statement.value) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        changed = True
        while changed:
            changed = False
            for statement in ast.walk(self.function):
                if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)): continue
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                assigned = {node.id for target in targets for node in ast.walk(target) if isinstance(node, ast.Name)}
                if assigned & needed:
                    value = statement.value
                    loaded = {node.id for node in ast.walk(value) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
                    old = len(needed); needed |= loaded
                    changed |= len(needed) != old
        return needed

    def block(self, kind: str, node: ast.AST | None = None, statement: str | None = None) -> str:
        identifier = f"block-{self.block_number}"; self.block_number += 1
        statements = [] if statement is None else [{"ast_kind": type(node).__name__ if node else kind,
                                                     "source": statement}]
        self.blocks.append(BasicBlock(identifier, kind, statements, _span(node) if node else None))
        return identifier

    def edge(self, source: str, target: str, kind: str, condition: str | None = None) -> None:
        self.edges.append(ControlFlowEdge(source, target, kind, condition))

    def canonical(self, name: str | None) -> str | None:
        if name is None: return None
        seen = set()
        while name in self.aliases and name not in seen:
            seen.add(name); name = self.aliases[name]
        return name

    def record_assignment(self, statement: ast.Assign | ast.AnnAssign) -> None:
        target = statement.targets[0] if isinstance(statement, ast.Assign) else statement.target
        value = statement.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Name):
            self.aliases[target.id] = self.canonical(value.id) or value.id
        elif isinstance(target, ast.Name):
            self.aliases.pop(target.id, None)
            if isinstance(value, (ast.Call, ast.Attribute, ast.Subscript)): self.unknown_aliases.add(target.id)
            else: self.unknown_aliases.discard(target.id)
        if isinstance(target, (ast.Subscript, ast.Attribute)):
            self.record_mutation(target, value, "IndexedStateUpdate" if isinstance(target, ast.Subscript) else "AttributeStateUpdate")

    def record_mutation(self, target: ast.AST, value: ast.AST | None, kind: str) -> None:
        base, display = _target_name(target); canonical = self.canonical(base)
        status = ControlFlowStatus.MUTATION_RESOLVED.value if canonical else ControlFlowStatus.MUTATION_TARGET_UNRESOLVED.value
        if base and base in self.aliases: status = ControlFlowStatus.MUTATION_RESOLVED.value
        if base in self.unknown_aliases:
            status = ControlFlowStatus.POTENTIAL_ALIAS.value
            self.statuses.add(status)
            if base in self.critical_names:
                self.unresolved.append({"code": status, "target": display, "source_span": _span(target)})
        elif base is None:
            self.statuses.add(ControlFlowStatus.MUTATION_TARGET_UNRESOLVED.value)
            target_names = {node.id for node in ast.walk(target) if isinstance(node, ast.Name)}
            if target_names & self.critical_names:
                self.unresolved.append({"code": "UNKNOWN_MUTATION_TARGET", "target": display, "source_span": _span(target)})
        else: self.statuses.add(status)
        self.counts["mutation_count"] += 1
        self.mutations.append(Mutation(f"mutation-{len(self.mutations)}", kind, display, canonical,
                                       ast.unparse(value) if value else None, status, _span(target)))

    @staticmethod
    def assigned(statements: list[ast.stmt]) -> set[str]:
        names = set()
        for statement in statements:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store): names.add(node.id)
        return names

    def branch_resolved(self, statement: ast.If) -> bool:
        yes, no = self.assigned(statement.body), self.assigned(statement.orelse)
        terminal = lambda body: bool(body) and isinstance(body[-1], (ast.Return, ast.Raise, ast.Break, ast.Continue))
        if terminal(statement.body) and (not statement.orelse or terminal(statement.orelse)): return True
        return bool(statement.orelse) and yes == no

    def while_termination(self, statement: ast.While) -> str:
        if isinstance(statement.test, ast.Compare) and isinstance(statement.test.left, ast.Name):
            counter = statement.test.left.id
            for node in statement.body:
                if (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
                        and node.target.id == counter and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, (int, float)) and node.value.value > 0
                        and isinstance(node.op, ast.Add)):
                    return "TERMINATION_PROVEN_MONOTONIC_COUNTER"
        return ControlFlowStatus.TERMINATION_UNPROVEN.value

    def build_region(self, statements: list[ast.stmt], incoming: list[str]) -> list[str]:
        current = incoming
        for position, statement in enumerate(statements):
            if isinstance(statement, ast.If):
                header = self.block("Branch", statement, ast.unparse(statement.test));
                for node in current: self.edge(node, header, "FlowEdge")
                yes_entry, no_entry = self.block("BasicBlock"), self.block("BasicBlock")
                self.edge(header, yes_entry, "TrueBranch", ast.unparse(statement.test))
                self.edge(header, no_entry, "FalseBranch", f"not ({ast.unparse(statement.test)})")
                self.counts["branch_count"] += 1
                if self.control_depth: self.counts["nested_branch_count"] += 1
                resolved = self.branch_resolved(statement)
                self.statuses.add(ControlFlowStatus.BRANCH_MERGE_RESOLVED.value if resolved else ControlFlowStatus.BRANCH_MERGE_UNRESOLVED.value)
                if not resolved and bool((self.assigned(statement.body) | self.assigned(statement.orelse)) & self.critical_names):
                    self.unresolved.append({"code": "BRANCH_MERGE_UNRESOLVED", "source_span": _span(statement)})
                self.control_depth += 1
                yes_exit = self.build_region(statement.body, [yes_entry])
                no_exit = self.build_region(statement.orelse, [no_entry]) if statement.orelse else [no_entry]
                self.control_depth -= 1
                merge = self.block("MergePoint", statement)
                for node in yes_exit + no_exit: self.edge(node, merge, "MergeEdge")
                current = [merge]; continue
            if isinstance(statement, (ast.For, ast.While)):
                header = self.block("LoopHeader", statement, ast.unparse(statement.iter if isinstance(statement, ast.For) else statement.test))
                for node in current: self.edge(node, header, "FlowEdge")
                body_entry, after = self.block("BasicBlock"), self.block("MergePoint", statement)
                self.edge(header, body_entry, "LoopBodyEdge"); self.edge(header, after, "LoopExitEdge")
                self.counts["loop_count"] += 1
                if self.loop_stack: self.counts["nested_loop_count"] += 1
                if isinstance(statement, ast.While): self.counts["while_count"] += 1
                if isinstance(statement, ast.For):
                    normalized = isinstance(statement.iter, ast.Call) and isinstance(statement.iter.func, ast.Name) and statement.iter.func.id == "range"
                    self.statuses.add(ControlFlowStatus.LOOP_NORMALIZED.value if normalized else ControlFlowStatus.LOOP_SEMANTICS_PRESERVED.value)
                    if normalized: self.statuses.add(ControlFlowStatus.LOOP_NORMALIZED_UNDER_ASSUMPTIONS.value)
                else:
                    termination = self.while_termination(statement)
                    self.statuses.add(ControlFlowStatus.LOOP_SEMANTICS_PRESERVED.value)
                    if termination == ControlFlowStatus.TERMINATION_UNPROVEN.value and bool(self.assigned(statement.body) & self.critical_names):
                        self.statuses.add(termination); self.unresolved.append({"code": termination, "source_span": _span(statement)})
                    elif termination != ControlFlowStatus.TERMINATION_UNPROVEN.value:
                        self.statuses.add(termination)
                effects = {type(node).__name__ for child in statement.body for node in ast.walk(child)
                           if isinstance(node, (ast.Break, ast.Continue, ast.Return))}
                affected = bool(self.assigned(statement.body) & self.critical_names)
                if effects and affected:
                    self.statuses.add(ControlFlowStatus.CONTROL_FLOW_PARTIALLY_RESOLVED.value)
                    self.unresolved.append({"code": "LOOP_CONTROL_EFFECTS_REQUIRE_PATH_SEMANTICS",
                                            "effects": sorted(effects), "source_span": _span(statement)})
                self.loop_stack.append((header, after))
                self.control_depth += 1
                body_exit = self.build_region(statement.body, [body_entry])
                self.control_depth -= 1
                self.loop_stack.pop()
                for node in body_exit: self.edge(node, header, "LoopBackEdge")
                else_exit = self.build_region(statement.orelse, [after]) if statement.orelse else [after]
                current = else_exit; continue
            if isinstance(statement, ast.Try):
                header = self.block("Branch", statement, "try")
                for node in current: self.edge(node, header, "FlowEdge")
                normal_entry = self.block("BasicBlock"); self.edge(header, normal_entry, "TryEdge")
                normal_exit = self.build_region(statement.body, [normal_entry])
                if statement.orelse: normal_exit = self.build_region(statement.orelse, normal_exit)
                exits = list(normal_exit); self.counts["exception_path_count"] += len(statement.handlers)
                for handler in statement.handlers:
                    handler_entry = self.block("BasicBlock", handler)
                    exception = ast.unparse(handler.type) if handler.type else "BaseException"
                    self.edge(header, handler_entry, "ExceptionEdge", exception)
                    exits += self.build_region(handler.body, [handler_entry])
                affects = bool((self.assigned(statement.body) | self.assigned([x for h in statement.handlers for x in h.body])) & self.critical_names)
                status = ControlFlowStatus.EXCEPTION_PATH_UNRESOLVED.value if statement.handlers and affects else ControlFlowStatus.EXCEPTION_PATH_RESOLVED.value
                self.statuses.add(status)
                if status == ControlFlowStatus.EXCEPTION_PATH_UNRESOLVED.value:
                    self.unresolved.append({"code": status, "source_span": _span(statement)})
                if statement.finalbody: exits = self.build_region(statement.finalbody, exits)
                merge = self.block("MergePoint", statement)
                for node in exits: self.edge(node, merge, "MergeEdge")
                current = [merge]; continue
            block = self.block("BasicBlock", statement, ast.unparse(statement))
            for node in current: self.edge(node, block, "FlowEdge")
            if isinstance(statement, (ast.Assign, ast.AnnAssign)): self.record_assignment(statement)
            elif isinstance(statement, ast.AugAssign):
                self.record_mutation(statement.target, statement.value, "InPlaceArithmetic")
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and isinstance(statement.value.func, ast.Attribute) and statement.value.func.attr in {"append", "extend"}:
                self.record_mutation(statement.value.func.value, statement.value.args[0] if statement.value.args else None,
                                     "ListAppend" if statement.value.func.attr == "append" else "ListExtend")
            if isinstance(statement, ast.Return):
                self.counts["return_count"] += 1
                if self.control_depth or position < len(statements) - 1: self.counts["early_return_count"] += 1
                self.edge(block, "exit", "ReturnEdge"); current = []
            elif isinstance(statement, ast.Break):
                self.counts["break_count"] += 1
                if self.loop_stack: self.edge(block, self.loop_stack[-1][1], "BreakEdge")
                current = []
            elif isinstance(statement, ast.Continue):
                self.counts["continue_count"] += 1
                if self.loop_stack: self.edge(block, self.loop_stack[-1][0], "ContinueEdge")
                current = []
            else: current = [block]
        return current

    def build(self) -> ControlFlowGraph:
        entry = self.block("Entry")
        exits = self.build_region(self.function.body, [entry])
        exit_block = self.block("Exit")
        # Edges recorded against the stable public exit id are rewritten here.
        for edge in self.edges:
            if edge.target == "exit": edge.target = exit_block
        for node in exits: self.edge(node, exit_block, "FlowEdge")
        critical_codes = {item["code"] for item in self.unresolved}
        cfg_status = (ControlFlowStatus.CFG_PARTIALLY_RESOLVED.value if critical_codes else ControlFlowStatus.CFG_RESOLVED.value)
        self.statuses.add(cfg_status)
        if self.counts["branch_count"] and not any(item["code"] == "BRANCH_MERGE_UNRESOLVED" for item in self.unresolved):
            self.statuses.add(ControlFlowStatus.BRANCH_PATHS_RESOLVED.value)
        if self.counts["early_return_count"] and not critical_codes:
            self.statuses.add(ControlFlowStatus.EARLY_RETURN_SEMANTICS_VERIFIED.value)
        if self.counts["nested_loop_count"] + self.counts["nested_branch_count"] and not critical_codes:
            self.statuses.add(ControlFlowStatus.NESTED_CONTROL_FLOW_VERIFIED.value)
        alias_status = (ControlFlowStatus.POTENTIAL_ALIAS.value if any(m.status == ControlFlowStatus.POTENTIAL_ALIAS.value for m in self.mutations)
                        else ControlFlowStatus.MUTATION_TARGET_UNRESOLVED.value if any(m.status == ControlFlowStatus.MUTATION_TARGET_UNRESOLVED.value for m in self.mutations)
                        else "ALIASES_RESOLVED")
        summary = {**self.counts, "cfg_status": cfg_status, "statuses": sorted(self.statuses),
                   "alias_status": alias_status,
                   "exception_paths": [item for item in self.unresolved if item["code"].startswith("EXCEPTION")],
                   "termination_status": (ControlFlowStatus.TERMINATION_UNPROVEN.value if ControlFlowStatus.TERMINATION_UNPROVEN.value in self.statuses
                                          else "TERMINATION_PROVEN_MONOTONIC_COUNTER" if "TERMINATION_PROVEN_MONOTONIC_COUNTER" in self.statuses
                                          else "TERMINATION_NOT_AT_ISSUE"),
                   "unresolved_control_flow": self.unresolved}
        return ControlFlowGraph("0.1", self.function.name, entry, exit_block, self.blocks, self.edges,
                                self.mutations, [{"alias": key, "canonical_target": value} for key, value in sorted(self.aliases.items())],
                                summary, self.diagnostics)


def build_python_cfg(source: str | Path, *, function: str | None = None, output: str | None = None) -> ControlFlowGraph:
    path = Path(source) if isinstance(source, Path) or "\n" not in str(source) else None
    is_file = bool(path and path.is_file())
    text = path.read_text(encoding="utf-8") if is_file else str(source)
    tree = ast.parse(text, filename=str(path) if is_file else "<string>")
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    selected = [node for node in functions if function is None or node.name == function]
    if len(selected) != 1: raise AuditError("PYTHON_FUNCTION_NOT_FOUND_OR_AMBIGUOUS")
    return PythonCFGBuilder(selected[0], output).build()
