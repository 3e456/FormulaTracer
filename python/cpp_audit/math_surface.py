"""TeX/DSL surface syntax, notation resolution, and typed unification."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Iterable, Mapping

from .math_semantics import OriginSet, SourceOrigin


class NotationResolutionError(ValueError):
    pass


@dataclass
class MathSurfaceAST:
    kind: str
    value: str | None = None
    children: list["MathSurfaceAST"] = field(default_factory=list)
    subscript: str | None = None
    superscript: str | None = None
    source_span: tuple[int, int] | None = None
    original_tex: str | None = None
    style: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SymbolDeclaration:
    canonical_name: str
    namespace: str = "user"
    role: str = "scalar"
    shape: tuple[Any, ...] = ()
    named_dimensions: tuple[str, ...] = ()
    domain: str | None = None


class CanonicalSymbolRegistry:
    def __init__(self) -> None:
        self._symbols: dict[str, SymbolDeclaration] = {}

    def declare(self, spelling: str, declaration: SymbolDeclaration) -> None:
        if spelling in self._symbols and self._symbols[spelling] != declaration:
            raise NotationResolutionError(f"AMBIGUOUS_SYMBOL_DECLARATION: {spelling}")
        self._symbols[spelling] = declaration

    def resolve(self, spelling: str) -> SymbolDeclaration | None:
        return self._symbols.get(spelling)


def _node(op: str, **values: Any) -> dict[str, Any]:
    return {"op": op, **values}


def _from_python(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.Constant): return _node("Constant", value=node.value)
    if isinstance(node, ast.Name): return _node("FreeVariable", name=node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return _node("Negate", args=[_from_python(node.operand)])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert): return _node("BitNot", args=[_from_python(node.operand)])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not): return _node("LogicalNot", args=[_from_python(node.operand)])
    if isinstance(node, ast.BinOp):
        ops = {ast.Add: "Add", ast.Sub: "Subtract", ast.Mult: "Multiply", ast.Div: "Divide",
               ast.FloorDiv: "FloorDivide", ast.Mod: "Modulo", ast.Pow: "Power",
               ast.BitAnd: "BitAnd", ast.BitOr: "BitOr", ast.BitXor: "BitXor",
               ast.LShift: "ShiftLeft", ast.RShift: "ShiftRight"}
        op = ops.get(type(node.op))
        if op: return _node(op, args=[_from_python(node.left), _from_python(node.right)])
    if isinstance(node, ast.BoolOp):
        return _node("LogicalAnd" if isinstance(node.op, ast.And) else "LogicalOr",
                     args=[_from_python(item) for item in node.values])
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        comparisons = {ast.Eq: "Equal", ast.NotEq: "NotEqual", ast.Lt: "LessThan",
                       ast.LtE: "LessEqual", ast.Gt: "GreaterThan", ast.GtE: "GreaterEqual"}
        return _node("Compare", comparison=comparisons[type(node.ops[0])],
                     args=[_from_python(node.left), _from_python(node.comparators[0])])
    if isinstance(node, ast.IfExp):
        return _node("Select", condition=_node("Predicate", expression=_from_python(node.test)),
                     then=_from_python(node.body), **{"else": _from_python(node.orelse)})
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [_from_python(item) for item in node.args]
        keywords = {item.arg: _from_python(item.value) for item in node.keywords if item.arg}
        primitive = {"bitand": "BitAnd", "bitor": "BitOr", "bitxor": "BitXor", "bitnot": "BitNot",
                     "shl": "ShiftLeft", "shr": "ShiftRight", "rotl": "RotateLeft", "rotr": "RotateRight",
                     "extract_bits": "BitFieldExtract", "insert_bits": "BitFieldInsert",
                     "indicator": "Indicator", "select": "Select", "piecewise": "Piecewise",
                     "min": "Minimum", "max": "Maximum", "clamp": "Clamp",
                     "re": "RealPart", "im": "ImagPart", "conj": "Conjugate", "arg": "Argument",
                     "mod": "Modulo", "quotient": "Quotient", "divmod": "DivMod"}.get(node.func.id)
        if primitive:
            if primitive == "Select" and len(args) == 3:
                return _node("Select", condition=_node("Predicate", expression=args[0]),
                             then=args[1], **{"else": args[2]})
            if primitive == "Indicator" and args:
                return _node("Indicator", predicate=_node("Predicate", expression=args[0]))
            result = _node(primitive, args=args)
            result.update(keywords)
            return result
        if node.func.id in {"bits", "encode_bits"}:
            return _node("EncodeBits", value=args[0] if args else _node("Missing"),
                         width=keywords.get("width"), signed=keywords.get("signed"), representation="TWOS_COMPLEMENT")
        return _node("FunctionCall", name=node.func.id, args=args, keywords=keywords)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        indices = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        return _node("IndexedValue", name=node.value.id, indices=[_from_python(item) for item in indices])
    raise NotationResolutionError(f"UNSUPPORTED_SURFACE_NODE: {type(node).__name__}")


def _balanced_group(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] != "{": raise NotationResolutionError("EXPECTED_TEX_GROUP")
    depth = 0
    for pos in range(start, len(text)):
        if text[pos] == "{": depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0: return text[start + 1:pos], pos + 1
    raise NotationResolutionError("UNCLOSED_TEX_GROUP")


def _replace_frac(text: str) -> str:
    while "\\frac" in text:
        pos = text.rfind("\\frac"); num, end = _balanced_group(text, pos + 5)
        den, finish = _balanced_group(text, end)
        text = text[:pos] + f"(({_replace_frac(num)})/({_replace_frac(den)}))" + text[finish:]
    return text


def _simple_tex(text: str) -> dict[str, Any]:
    value = _replace_frac(text.strip())
    value = re.sub(r"\\(sin|cos|sqrt|exp|log)\s+([A-Za-z][A-Za-z0-9]*)\b",
                   lambda match: rf"\{match.group(1)}({match.group(2)})", value)
    replacements = {"\\cdot": "*", "\\times": "*", "\\pi": "pi", "\\infty": "inf",
                    "^": "**", "\\exp": "exp", "\\log": "log", "\\sin": "sin",
                    "\\cos": "cos", "\\sqrt": "sqrt"}
    for old, new in replacements.items(): value = value.replace(old, new)
    value = re.sub(r"([A-Za-z][A-Za-z0-9]*)_\{([^{}]+)\}",
                   lambda m: m.group(1) + "[" + ",".join(m.group(2).replace(" ", "")) + "]", value)
    value = re.sub(r"([A-Za-z][A-Za-z0-9]*)_([A-Za-z0-9])", r"\1[\2]", value)
    value = value.replace("{", "(").replace("}", ")")
    value = re.sub(r"(?<=\d)\s*(?=[A-Za-z(])|(?<=\))\s*(?=[A-Za-z0-9(])", "*", value)
    value = re.sub(r"(?<=[A-Za-z0-9\]])\s+(?=[A-Za-z(])", "*", value)
    try: return _from_python(ast.parse(value, mode="eval").body)
    except (SyntaxError, NotationResolutionError) as exc:
        raise NotationResolutionError(f"AMBIGUOUS_FORMULA_PARSE: {text}: {exc}") from exc


def _bind_and_simplify(node: Any, bound: set[str]) -> Any:
    if isinstance(node, list): return [_bind_and_simplify(item, bound) for item in node]
    if not isinstance(node, dict): return node
    result = {key: _bind_and_simplify(value, bound) for key, value in node.items()}
    if result.get("op") == "FreeVariable" and result.get("name") in bound: result["op"] = "BoundVariable"
    if result.get("op") == "Add" and len(result.get("args", [])) == 2:
        left, right = result["args"]
        if right == _node("Constant", value=1) and left.get("op") == "Subtract" and left.get("args", [None, None])[1] == _node("Constant", value=1):
            return left["args"][0]
    return result


def parse_tex(tex: str, *, registry: CanonicalSymbolRegistry | None = None,
              assumptions: Iterable[str] = ()) -> tuple[MathSurfaceAST, dict[str, Any], OriginSet]:
    """Parse the supported TeX-first surface and fail closed on ambiguity."""
    source = tex.strip()
    surface = MathSurfaceAST("Expression", source_span=(0, len(tex)), original_tex=tex)
    origin = OriginSet([SourceOrigin(tex, (0, len(tex)), "tex")])
    assumption_set = set(assumptions)
    repeated_indices = re.findall(r"_\{?([A-Za-z])\}?", source)
    if "einstein" not in assumption_set and any(
            repeated_indices.count(item) > 1 for item in set(repeated_indices)) and "\\sum" not in source:
        raise NotationResolutionError("AMBIGUOUS_IMPLICIT_EINSTEIN_SUMMATION")
    if any(token in source for token in ("\\cdot", "\\times", "*", "|", "'", "\\bar", "\\overline")):
        raise NotationResolutionError("AMBIGUOUS_NOTATION: overloaded operator role")
    if ("<" in source or ">" in source) and not re.search(r"(?:<=|>=|\w\s*[<>]\s*[-+]?\d)", source):
        raise NotationResolutionError("AMBIGUOUS_NOTATION: comparison or bracket role")
    if "\\sum" not in source and "\\int" not in source and "\\lim" not in source:
        for exponent in re.findall(r"\^\{?([^{}\s]+)\}?", source):
            if not re.fullmatch(r"(?:\d+(?:\.\d+)?)", exponent):
                raise NotationResolutionError("AMBIGUOUS_NOTATION: superscript role")
        indexed = re.findall(r"\b([A-Za-z][A-Za-z0-9]*)_\{?([A-Za-z0-9]+)\}?", source)
        for base, _ in indexed:
            declaration = registry.resolve(base) if registry else None
            if "einstein" not in assumption_set and "index_notation" not in assumption_set and (
                    declaration is None or declaration.role not in {"tensor", "indexed"}):
                raise NotationResolutionError("AMBIGUOUS_NOTATION: subscript role")
    # Binder constructs below resolve their own index roles syntactically.
    match = re.match(r"\\sum_\{([A-Za-z]\w*)\s*=\s*([^{}]+)\}\^\{\\infty\}\s*(.+)$", source)
    if match:
        index, lower, body = match.groups()
        return surface, _node("InfiniteSeries", bound_index=index, lower=_simple_tex(lower),
                              body=_bind_and_simplify(_simple_tex(body), {index})), origin
    match = re.match(r"\\sum_\{([A-Za-z]\w*)\s*=\s*([^{}]+)\}\^\{([^{}]+)\}\s*(.+)$", source)
    if match:
        index, lower, upper, body = match.groups()
        canonical = _node("FiniteSum", bound_index=index,
            index_domain={"lower": _simple_tex(lower),
                          "upper_exclusive": _node("Add", args=[_simple_tex(upper), _node("Constant", value=1)])},
            body=_bind_and_simplify(_simple_tex(body), {index}))
        canonical["index_domain"] = _bind_and_simplify(canonical["index_domain"], set())
        return surface, canonical, origin
    match = re.match(r"\\int_\{([^{}]+)\}\^\{([^{}]+)\}\s*(.+)\\,?d([A-Za-z]\w*)$", source)
    if match:
        lower, upper, body, variable = match.groups()
        return surface, _node("Integral", variable=variable, lower=_simple_tex(lower), upper=_simple_tex(upper),
                              integrand=_simple_tex(body)), origin
    match = re.match(r"\\lim_\{([A-Za-z]\w*)\\to([^{}]+)\}\s*(.+)$", source)
    if match:
        variable, target, body = match.groups()
        return surface, _node("Limit", variable=variable, target=_simple_tex(target), body=_simple_tex(body)), origin
    return surface, _simple_tex(source), origin


def _tex(node: dict[str, Any]) -> str:
    op = node.get("op")
    if op == "Constant": return str(node.get("value"))
    if op in {"FreeVariable", "BoundVariable"}: return str(node.get("name"))
    if op == "IndexedValue": return str(node.get("name")) + "_{" + ",".join(_tex(x) for x in node.get("indices", [])) + "}"
    if op == "Negate": return "-" + _tex(node["args"][0])
    binary = {"Add": "+", "Subtract": "-", "Multiply": r"\,", "Divide": "/", "FloorDivide": "//",
              "Modulo": r"\bmod", "Power": "^", "BitAnd": r"\mathbin{\&}", "BitOr": r"\mathbin{|}",
              "BitXor": r"\mathbin{\oplus}", "ShiftLeft": r"\ll", "ShiftRight": r"\gg",
              "LogicalAnd": r"\land", "LogicalOr": r"\lor"}
    if op in binary:
        a, b = node["args"]
        if op == "Divide": return rf"\frac{{{_tex(a)}}}{{{_tex(b)}}}"
        return "{" + _tex(a) + binary[op] + _tex(b) + "}"
    if op == "FunctionCall": return "\\" + str(node.get("name")) + "(" + ",".join(_tex(x) for x in node.get("args", [])) + ")"
    if op in {"BitNot", "LogicalNot"}: return (r"\operatorname{bitnot}" if op == "BitNot" else r"\neg") + "(" + _tex(node["args"][0]) + ")"
    if op in {"RotateLeft", "RotateRight", "BitFieldExtract", "BitFieldInsert", "PopCount",
              "Minimum", "Maximum", "Clamp", "Indicator", "RealPart", "ImagPart", "Conjugate",
              "Argument", "Magnitude", "Quotient", "DivMod", "EncodeBits", "DecodeBits"}:
        args = node.get("args", [])
        if not args and "value" in node: args = [node["value"]]
        width = node.get("bit_representation", {}).get("width")
        suffix = "_{" + str(width) + "}" if width is not None and op.startswith(("Bit", "Rotate")) else ""
        return rf"\operatorname{{{op}}}{suffix}(" + ",".join(_tex(x) for x in args) + ")"
    if op == "Predicate": return _tex(node["expression"])
    if op == "Select":
        condition = node["condition"].get("expression", node["condition"])
        return rf"\begin{{cases}} {_tex(node['then'])}, & {_tex(condition)} \\ {_tex(node['else'])}, & \text{{otherwise}} \end{{cases}}"
    if op == "Piecewise":
        rows = [f"{_tex(case['expression'])}, & {_tex(case['predicate'].get('expression', case['predicate']))}" for case in node.get("cases", [])]
        if "otherwise" in node: rows.append(f"{_tex(node['otherwise'])}, & \\text{{otherwise}}")
        return r"\begin{cases} " + r" \\ ".join(rows) + r" \end{cases}"
    if op == "FiniteSum":
        domain = node["index_domain"]; upper = domain["upper_exclusive"]
        upper_text = _tex(upper)
        return rf"\sum_{{{node['bound_index']}={_tex(domain['lower'])}}}^{{{upper_text}-1}} {_tex(node['body'])}"
    if op == "InfiniteSeries": return rf"\sum_{{{node['bound_index']}={_tex(node['lower'])}}}^{{\infty}} {_tex(node['body'])}"
    if op == "Integral": return rf"\int_{{{_tex(node['lower'])}}}^{{{_tex(node['upper'])}}} {_tex(node['integrand'])}\,d{node['variable']}"
    if op == "Limit": return rf"\lim_{{{node['variable']}\to{_tex(node['target'])}}} {_tex(node['body'])}"
    return rf"\operatorname{{{op}}}"


def _reference_to_tex(node: dict[str, Any]) -> str:
    """Frozen migration oracle; never used by the production semantic path."""
    return _tex(node)


def to_tex(node: dict[str, Any]) -> str:
    """Render canonical TeX through the native semantic core."""
    from formulatracer.native import execute_native_kernel

    response = execute_native_kernel({
        "schema_version": "1.0",
        "kernel": "B",
        "operation": "RENDER_TEX",
        "expression": node,
    })
    return str(response["result"]["tex"])
def to_dsl(node: dict[str, Any]) -> str: return json.dumps(node, ensure_ascii=False, sort_keys=True)
def to_unicode(node: dict[str, Any]) -> str:
    value = to_tex(node)
    replacements = {r"\sum": "Σ", r"\prod": "Π", r"\int": "∫", r"\infty": "∞",
                    r"\to": "→", r"\pi": "π", r"\,": " "}
    for old, new in replacements.items(): value = value.replace(old, new)
    return value.replace("{", "").replace("}", "")


def to_markdown(node: dict[str, Any]) -> str: return "$$\n" + to_tex(node) + "\n$$\n"


def to_json(node: dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(node, indent=indent, ensure_ascii=False, sort_keys=True) + "\n"


class MathBuilder:
    @staticmethod
    def constant(value: Any) -> dict[str, Any]: return _node("Constant", value=value)
    @staticmethod
    def var(name: str) -> dict[str, Any]: return _node("FreeVariable", name=name)
    @staticmethod
    def indexed(name: str, *indices: str) -> dict[str, Any]:
        return _node("IndexedValue", name=name, indices=[_node("BoundVariable", name=item) for item in indices])
    @staticmethod
    def call(name: str, *args: dict[str, Any]) -> dict[str, Any]: return _node("FunctionCall", name=name, args=list(args))
    @staticmethod
    def sum(index: str, lower: dict[str, Any], upper_exclusive: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        return _node("FiniteSum", bound_index=index, index_domain={"lower": lower, "upper_exclusive": upper_exclusive}, body=body)
    @staticmethod
    def integral(variable: str, lower: dict[str, Any], upper: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        return _node("Integral", variable=variable, lower=lower, upper=upper, integrand=body)


@dataclass(frozen=True)
class TypedPattern:
    pattern: dict[str, Any]
    metavariables: dict[str, SymbolDeclaration]


@dataclass(frozen=True)
class UnificationResult:
    status: str
    substitution: dict[str, Any]
    obligations: tuple[str, ...] = ()


@dataclass(frozen=True)
class MathematicalSubstitution:
    metavariable: str
    value: Any
    expected_type: SymbolDeclaration | None = None
    type_status: str = "TYPE_UNRESOLVED"
    shape_status: str = "SHAPE_UNRESOLVED"


@dataclass(frozen=True)
class AntiUnificationResult:
    status: str
    pattern: Any
    left_substitution: Mapping[str, Any]
    right_substitution: Mapping[str, Any]


def _reference_anti_unify(left: Any, right: Any) -> AntiUnificationResult:
    """Conservative least-general generalization; semantic operators/constants stay fixed."""
    left_sub: dict[str, Any] = {}; right_sub: dict[str, Any] = {}; counter = 0
    def visit(a: Any, b: Any) -> Any:
        nonlocal counter
        if a == b: return a
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b): return [visit(x, y) for x, y in zip(a, b)]
        if isinstance(a, dict) and isinstance(b, dict) and a.get("op") == b.get("op"):
            if a.get("op") == "Constant": raise NotationResolutionError("ANTI_UNIFICATION_WOULD_GENERALIZE_CONSTANT")
            keys = set(a) | set(b)
            return {key: visit(a.get(key), b.get(key)) for key in keys}
        if isinstance(a, str) and isinstance(b, str):
            key = f"$g{counter}"; counter += 1; left_sub[key] = a; right_sub[key] = b
            return key
        raise NotationResolutionError("ANTI_UNIFICATION_WOULD_ERASE_SEMANTIC_STRUCTURE")
    try: return AntiUnificationResult("ANTI_UNIFICATION_SUCCEEDED", visit(left, right), left_sub, right_sub)
    except NotationResolutionError:
        return AntiUnificationResult("ANTI_UNIFICATION_REJECTED", None, left_sub, right_sub)


def anti_unify(left: Any, right: Any) -> AntiUnificationResult:
    """Conservatively anti-unify through the Rust semantic owner."""
    from formulatracer.native import execute_native_kernel

    result = execute_native_kernel({
        "schema_version": "1.0", "kernel": "B", "operation": "ANTI_UNIFY",
        "left": left, "right": right,
    })["result"]
    return AntiUnificationResult(result["status"], result.get("pattern"),
                                 result.get("left_substitution", {}),
                                 result.get("right_substitution", {}))


def _reference_generalize(node: Any, declarations: Mapping[str, SymbolDeclaration] | None = None) -> TypedPattern:
    declarations = dict(declarations or {}); mapping: dict[str, str] = {}; metavars: dict[str, SymbolDeclaration] = {}
    def visit(value: Any, bound: dict[str, str]) -> Any:
        if isinstance(value, list): return [visit(item, bound) for item in value]
        if not isinstance(value, dict): return value
        op = value.get("op")
        local = dict(bound)
        ignored = {"source_spans", "source_node_ids", "source_span", "operator_span", "callable_span", "argument_spans", "keyword_spans", "condition_span", "shape_constraints", "numeral_representation", "mathematical_semantic",
                   "alignment_constraints", "resolution_trace", "reduction_order", "lowered_from"}
        if op in {"FiniteSum", "FiniteProduct", "InfiniteSeries"}:
            old = str(value.get("bound_index")); new = f"$i{len(bound)}"; local[old] = new
            result = {key: visit(item, local) for key, item in sorted(value.items()) if key != "bound_index" and key not in ignored}; result["bound_index"] = new
            return result
        if op in {"FreeVariable", "BoundVariable"}:
            name = str(value.get("name"))
            base = {key: item for key, item in sorted(value.items()) if key not in ignored}
            if name in local: return {**base, "name": local[name]}
            placeholder = mapping.setdefault(name, f"$v{len(mapping)}")
            metavars.setdefault(placeholder, declarations.get(name, SymbolDeclaration(name)))
            return {**base, "name": placeholder}
        if op == "IndexedValue":
            name = str(value.get("name")); placeholder = mapping.setdefault(name, f"$v{len(mapping)}")
            decl = declarations.get(name, SymbolDeclaration(name, role="tensor", shape=(None,) * len(value.get("indices", []))))
            metavars.setdefault(placeholder, decl)
            base = {key: item for key, item in sorted(value.items()) if key not in ignored}
            return {**base, "name": placeholder, "indices": visit(value.get("indices", []), local)}
        return {key: visit(item, local) for key, item in sorted(value.items()) if key not in ignored}
    return TypedPattern(visit(node, {}), metavars)


def generalize(node: Any, declarations: Mapping[str, SymbolDeclaration] | None = None) -> TypedPattern:
    """Generalize symbols and binders through the Rust semantic owner."""
    from formulatracer.native import execute_native_kernel

    result = execute_native_kernel({
        "schema_version": "1.0", "kernel": "B", "operation": "GENERALIZE",
        "expression": node,
        "declarations": {name: asdict(value) for name, value in (declarations or {}).items()},
    })["result"]
    metavariables = {
        name: SymbolDeclaration(
            canonical_name=value["canonical_name"],
            namespace=value.get("namespace", "user"), role=value.get("role", "scalar"),
            shape=tuple(value.get("shape", ())),
            named_dimensions=tuple(value.get("named_dimensions", ())),
            domain=value.get("domain"),
        )
        for name, value in result.get("metavariables", {}).items()
    }
    return TypedPattern(result["pattern"], metavariables)


def _reference_typed_unify(pattern: TypedPattern, candidate: dict[str, Any],
                           candidate_declarations: Mapping[str, SymbolDeclaration] | None = None) -> UnificationResult:
    substitutions: dict[str, Any] = {}; obligations: list[str] = []; declarations = dict(candidate_declarations or {})
    def unify(left: Any, right: Any, bound: dict[str, str]) -> bool:
        if isinstance(left, list): return isinstance(right, list) and len(left) == len(right) and all(unify(a, b, bound) for a, b in zip(left, right))
        if not isinstance(left, dict): return left == right
        if not isinstance(right, dict) or left.get("op") != right.get("op"): return False
        if left.get("op") in {"FreeVariable", "BoundVariable"} and str(left.get("name", "")).startswith("$"):
            key = left["name"]
            if key in substitutions: return substitutions[key] == right
            substitutions[key] = right; return True
        if left.get("op") == "IndexedValue" and str(left.get("name", "")).startswith("$"):
            key = left["name"]; rank = len(right.get("indices", [])); expected = pattern.metavariables[key]
            if expected.shape and len(expected.shape) != rank: return False
            symbol = str(right.get("name")); actual = declarations.get(symbol)
            if actual and expected.named_dimensions and actual.named_dimensions != expected.named_dimensions:
                obligations.append(f"named dimensions: {expected.named_dimensions} = {actual.named_dimensions}")
            substitutions[key] = _node("FreeVariable", name=symbol)
            return unify(left.get("indices", []), right.get("indices", []), bound)
        ignored = {"source_spans", "source_node_ids", "source_span", "operator_span", "callable_span", "argument_spans", "keyword_spans", "condition_span", "original_tex", "numeral_representation", "mathematical_semantic"}
        keys = (set(left) | set(right)) - ignored
        return all(unify(left.get(key), right.get(key), bound) for key in keys)
    ok = unify(pattern.pattern, candidate, {})
    return UnificationResult("TYPED_UNIFICATION_SUCCEEDED" if ok else "TYPED_UNIFICATION_FAILED", substitutions, tuple(obligations))


def _native_unification_pattern(value: Any, pattern: TypedPattern) -> Any:
    if isinstance(value, list): return [_native_unification_pattern(item, pattern) for item in value]
    if not isinstance(value, dict): return value
    op, name = value.get("op"), str(value.get("name", ""))
    if op in {"FreeVariable", "BoundVariable"} and name.startswith("$v"):
        return {"op": "PatternVariable", "name": name, "required_op": op}
    if op == "IndexedValue" and name.startswith("$v"):
        declaration = pattern.metavariables.get(name)
        native = {"op": "PatternVariable", "name": name, "required_op": "IndexedValue"}
        if declaration and declaration.shape:
            native["required_rank"] = len(declaration.shape)
        if declaration and declaration.named_dimensions:
            native["required_named_dimensions"] = list(declaration.named_dimensions)
        return native
    return {key: _native_unification_pattern(item, pattern) for key, item in value.items()}


def _candidate_with_declarations(value: Any, declarations: Mapping[str, SymbolDeclaration]) -> Any:
    if isinstance(value, list): return [_candidate_with_declarations(item, declarations) for item in value]
    if not isinstance(value, dict): return value
    result = {key: _candidate_with_declarations(item, declarations) for key, item in value.items()}
    if value.get("op") == "IndexedValue" and (declaration := declarations.get(str(value.get("name")))):
        if declaration.shape: result["shape"] = list(declaration.shape)
        if declaration.named_dimensions: result["named_dimensions"] = list(declaration.named_dimensions)
    return result


def typed_unify(pattern: TypedPattern, candidate: dict[str, Any],
                candidate_declarations: Mapping[str, SymbolDeclaration] | None = None) -> UnificationResult:
    """Run typed unification in Rust; Python converts public pattern metadata only."""
    from formulatracer.native import execute_native_kernel

    response = execute_native_kernel({
        "schema_version": "1.0", "kernel": "B", "operation": "TYPED_UNIFY",
        "pattern": _native_unification_pattern(pattern.pattern, pattern),
        "candidate": _candidate_with_declarations(candidate, dict(candidate_declarations or {})),
    })["result"]
    native_substitution = response.get("substitution", {})
    substitutions = {}
    for key, value in native_substitution.get("symbols", {}).items():
        substitutions[key] = (_node("FreeVariable", name=value.get("name"))
                              if isinstance(value, dict) and value.get("op") == "IndexedValue"
                              else value)
    matched = response.get("status") in {"MATCH", "MATCH_WITH_OBLIGATIONS"}
    return UnificationResult(
        "TYPED_UNIFICATION_SUCCEEDED" if matched else "TYPED_UNIFICATION_FAILED",
        substitutions, tuple(native_substitution.get("obligations", ())),
    )


def _reference_instantiate(node: Any, substitution: Mapping[str, Any]) -> Any:
    if isinstance(node, list): return [_reference_instantiate(item, substitution) for item in node]
    if not isinstance(node, dict): return node
    if node.get("op") in {"FreeVariable", "BoundVariable"} and node.get("name") in substitution:
        return substitution[node["name"]]
    result = {key: _reference_instantiate(value, substitution) for key, value in node.items()}
    if node.get("op") == "IndexedValue" and node.get("name") in substitution:
        result["name"] = substitution[node["name"]].get("name")
    return result


def _native_substitution_expression(value: Any, substitution_names: set[str]) -> Any:
    if isinstance(value, list): return [_native_substitution_expression(item, substitution_names) for item in value]
    if not isinstance(value, dict): return value
    if value.get("op") in {"FreeVariable", "BoundVariable"} and value.get("name") in substitution_names:
        return {"op": "PatternVariable", "name": value["name"]}
    return {key: _native_substitution_expression(item, substitution_names) for key, item in value.items()}


def instantiate(node: Any, substitution: Mapping[str, Any]) -> Any:
    """Apply capture-avoiding substitution in the native semantic core."""
    from formulatracer.native import execute_native_kernel

    return execute_native_kernel({
        "schema_version": "1.0", "kernel": "B", "operation": "SUBSTITUTE",
        "expression": _native_substitution_expression(node, set(substitution)), "mapping": dict(substitution),
    })["result"]


def _reference_canonical_equal(left: Any, right: Any) -> bool:
    """Frozen migration oracle; never used by the production semantic path."""
    return _reference_generalize(left).pattern == _reference_generalize(right).pattern


def canonical_equal(left: Any, right: Any) -> bool:
    """Decide alpha/canonical equality in the native semantic core."""
    from formulatracer.native import execute_native_kernel

    response = execute_native_kernel({
        "schema_version": "1.0",
        "kernel": "B",
        "operation": "EQUAL",
        "left": left,
        "right": right,
    })
    return bool(response["result"]["equal"])
