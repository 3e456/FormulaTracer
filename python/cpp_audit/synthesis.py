"""Canonical theory-to-code synthesis with mandatory frontend round trips."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


@dataclass
class TheorySpecification:
    output: str
    expression: dict[str, Any]
    inputs: list[str]
    assumptions: list[str] = field(default_factory=list)


@dataclass
class ImplementationConstraints:
    language: str
    transformation_set: dict[str, Any] | None = None
    numeric_domain: str = "real"
    allowed_approximations: list[str] = field(default_factory=list)
    readability: str = "CANONICAL"


@dataclass
class AlgorithmIR:
    algorithm_id: str
    expression: dict[str, Any]
    selected_transformations: list[dict[str, Any]]
    status: str


@dataclass
class ExpectedImplementationIR:
    expression: dict[str, Any]
    language: str
    output: str


@dataclass
class SynthesisDivergence:
    stage: str
    type: str
    expected: Any
    actual: Any
    status: str


@dataclass
class RoundTripVerification:
    status: str
    observed_implementation_ir: Any
    observed_mathematical_ir: Any
    comparison: dict[str, Any]
    first_synthesis_divergence: SynthesisDivergence | None
    end_to_end_status: str | None


@dataclass
class GeneratedImplementation:
    generation_id: str
    language: str
    source: str
    filename: str
    algorithm_ir: AlgorithmIR
    expected_implementation_ir: ExpectedImplementationIR
    status: str
    source_path: str | None = None
    round_trip: RoundTripVerification | None = None

    def write(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.source, encoding="utf-8"); self.source_path = str(target); return target


@dataclass
class CodeSynthesisResult:
    theory: TheorySpecification
    constraints: ImplementationConstraints
    transformed_theory: Any
    algorithm_ir: AlgorithmIR
    expected_implementation_ir: ExpectedImplementationIR
    generated: GeneratedImplementation
    round_trip: RoundTripVerification | None
    pipeline_trace: list[dict[str, Any]]
    status: str
    generation_decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]: return _serial(self)
    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True) + "\n"
    def write_json(self, path: str | Path) -> Path:
        target = Path(path); target.write_text(self.to_json(), encoding="utf-8"); return target


@dataclass
class RepairCandidate:
    repair_id: str
    divergence_type: str
    source_file: str
    source_span: dict[str, Any]
    expected_semantics: Any
    actual_semantics: Any
    replacement_text: str | None
    status: str = "CANDIDATE_ONLY"


@dataclass
class RepairVerificationResult:
    candidate: RepairCandidate
    reanalysis_status: str
    end_to_end_status: str | None
    debug_status: str | None
    status: str


@dataclass
class CrossLanguageSynthesisResult:
    results: dict[str, CodeSynthesisResult]
    canonical_ir_status: str


def _serial(value: Any) -> Any:
    if is_dataclass(value): return {key: _serial(item) for key, item in asdict(value).items()}
    if isinstance(value, dict): return {str(key): _serial(item) for key, item in value.items()}
    if isinstance(value, list): return [_serial(item) for item in value]
    return value


def _id(prefix: str, value: Any) -> str:
    return prefix + ":" + sha256(json.dumps(_serial(value), sort_keys=True).encode()).hexdigest()[:16]


def _native_synthesis(action: str, **payload: Any) -> Any:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "D",
            "operation": "LEGACY_SYNTHESIS", "action": action, **payload})["result"]


def _name(value: str) -> str:
    result = re.sub(r"\W", "_", value)
    return "value_" + result if result[:1].isdigit() else result


def _render(node: dict[str, Any], language: str) -> str:
    op = node.get("op")
    if op == "Constant":
        value = node.get("value")
        if language == "rust" and isinstance(value, int): return f"{value}.0"
        if language == "cpp" and isinstance(value, int): return f"{value}.0"
        return repr(value)
    if op in {"FreeVariable", "BoundVariable"}: return _name(str(node.get("name", "x")).rsplit(".", 1)[-1])
    if op == "IndexedValue":
        base = _name(str(node.get("name") or node.get("base", {}).get("name", "x")).rsplit(".", 1)[-1])
        for index in node.get("indices", []): base += f"[{_render(index, language)}]"
        return base
    args = node.get("args", [])
    binary = {"Add": "+", "Subtract": "-", "Multiply": "*", "Divide": "/", "Power": "**" if language == "python" else None}
    if op in binary and len(args) == 2:
        if op == "Power" and language == "rust": return f"({_render(args[0], language)}).powf({_render(args[1], language)})"
        if op == "Power" and language == "cpp": return f"std::pow({_render(args[0], language)}, {_render(args[1], language)})"
        return f"({_render(args[0], language)} {binary[op]} {_render(args[1], language)})"
    if op == "Negate": return f"(-{_render(args[0], language)})"
    if op == "IfThenElse":
        condition, yes, no = (_render(node[key], language) for key in ("condition", "then", "else"))
        if language == "python": return f"({yes} if {condition} else {no})"
        if language == "rust": return f"(if {condition} {{ {yes} }} else {{ {no} }})"
        return f"({condition} ? {yes} : {no})"
    if op == "Compare" and len(args) == 2:
        operators = {"GreaterThan": ">", "GreaterEqual": ">=", "LessThan": "<", "LessEqual": "<=", "Equal": "==", "NotEqual": "!="}
        return f"({_render(args[0], language)} {operators.get(node.get('comparison'), '<')} {_render(args[1], language)})"
    if op in {"FiniteSum", "FiniteProduct", "FoldLeft", "TransformReduce"}:
        raise ValueError("STRUCTURED_REDUCTION_REQUIRES_STATEMENTS")
    if op == "FunctionCall":
        functions = {"sqrt": "math.sqrt" if language == "python" else "sqrt",
                     "abs": "abs", "exp": "math.exp" if language == "python" else "exp",
                     "log": "math.log" if language == "python" else "log"}
        function = functions.get(str(node.get("name")).rsplit(".", 1)[-1], str(node.get("name")))
        return f"{function}({', '.join(_render(item, language) for item in args)})"
    if op == "DiscreteDifference":
        source = _name(str(node.get("function", "f"))); variable = _name(str(node.get("variable", "x")))
        spacing = _name(str(node.get("spacing", "h"))); family = node.get("family_id")
        if family not in {"central_difference_first_derivative", "forward_difference_first_derivative"}:
            raise ValueError("APPROXIMATION_NOT_AUTHORIZED")
        return (f"(({source}({variable} + {spacing}) - {source}({variable} - {spacing})) / (2 * {spacing}))"
                if family.startswith("central") else f"(({source}({variable} + {spacing}) - {source}({variable})) / {spacing})")
    if op in {"Map", "Filter"}:
        index = _name(str(node.get("bound_index", "i"))); domain = node.get("index_domain", {})
        lower = _render(domain.get("lower", {"op": "Constant", "value": 0}), language)
        upper = _render(domain.get("upper_exclusive"), language)
        body = _render(node.get("body"), language)
        condition = _render(node.get("condition", {"op": "Constant", "value": True}), language)
        predicate = f" if {condition}" if op == "Filter" else ""
        if language == "python": return f"[{body} for {index} in range(int({lower}), int({upper})){predicate}]"
        filter_part = f".filter(|&{index}| {condition})" if op == "Filter" else ""
        if language == "rust": return f"(({lower} as usize)..({upper} as usize)){filter_part}.map(|{index}| {body}).collect::<Vec<f64>>()"
        guard = f"if ({condition}) " if op == "Filter" else ""
        return (f"([&]() {{ std::vector<double> out; for (std::size_t {index}=static_cast<std::size_t>({lower}); "
                f"{index}<static_cast<std::size_t>({upper}); ++{index}) {{ {guard}out.push_back({body}); }} return out; }}())")
    if op == "Quadrature":
        method = str(node.get("method", "trapezoidal")); function = _name(str(node.get("function", "f")))
        lower, upper, panels = (_render(node.get(key), language) for key in ("lower", "upper", "panels"))
        if method not in {"trapezoidal", "midpoint"}: raise ValueError("APPROXIMATION_NOT_AUTHORIZED")
        if language == "python":
            sample = (f"({function}({lower}) + {function}({upper}) + 2*sum({function}({lower}+i*h) for i in range(1, int({panels}))))/2"
                      if method == "trapezoidal" else f"sum({function}({lower}+(i+0.5)*h) for i in range(int({panels})))")
            return f"((({upper}-{lower})/{panels}) * ({sample}))"
        raise ValueError("QUADRATURE_STATEMENT_LOWERING_REQUIRED")
    raise ValueError(f"UNSUPPORTED_SYNTHESIS_IR: {op}")


def _reduction_source(theory: TheorySpecification, language: str) -> str:
    node = theory.expression; op = node.get("op")
    index = _name(str(node.get("bound_index", "i"))); domain = node.get("index_domain", {})
    lower, upper = _render(domain.get("lower", {"op": "Constant", "value": 0}), language), _render(domain.get("upper_exclusive"), language)
    body = _render(node.get("body") or node.get("transform"), language)
    multiply = op == "FiniteProduct" or node.get("operation") == "Multiply" or node.get("reduction") == "Multiply"
    identity, operator = ("1.0", "*=") if multiply else ("0.0", "+=")
    if language == "python":
        return f"    result = {identity}\n    for {index} in range({lower}, {upper}):\n        result {operator} {body}\n    return result"
    if language == "rust":
        return f"    let mut result: f64 = {identity};\n    for {index} in ({lower} as usize)..({upper} as usize) {{\n        result {operator} {body};\n    }}\n    result"
    return f"    double result = {identity};\n    for (std::size_t {index} = static_cast<std::size_t>({lower}); {index} < static_cast<std::size_t>({upper}); ++{index}) {{\n        result {operator} {body};\n    }}\n    return result;"


def _source(theory: TheorySpecification, language: str) -> tuple[str, str]:
    parameters = [_name(item) for item in theory.inputs]
    structured = theory.expression.get("op") in {"FiniteSum", "FiniteProduct", "FoldLeft", "TransformReduce"}
    body = _reduction_source(theory, language) if structured else None
    expression = None if structured else _render(theory.expression, language)
    output = _name(theory.output)
    if language == "python":
        imports = "import math\n\n"
        code = body if structured else f"    {output} = {expression}\n    return {output}"
        return imports + f"def compute({', '.join(parameters)}):\n{code}\n", "generated.py"
    if language == "rust":
        signature = ", ".join(f"{item}: f64" for item in parameters)
        code = body if structured else f"    let {output}: f64 = {expression};\n    {output}"
        return f"pub fn compute({signature}) -> f64 {{\n{code}\n}}\n", "lib.rs"
    if language == "cpp":
        signature = ", ".join(f"double {item}" for item in parameters)
        code = body if structured else f"    double {output} = {expression};\n    return {output};"
        return f"#include <cmath>\n#include <cstddef>\n#include <vector>\n\ndouble compute({signature}) {{\n{code}\n}}\n", "generated.cpp"
    raise ValueError(f"UNSUPPORTED_SYNTHESIS_LANGUAGE: {language}")


def synthesize(theory: TheorySpecification, *, language: str,
               constraints: ImplementationConstraints | None = None,
               output_path: str | Path | None = None, verify: bool = True) -> CodeSynthesisResult:
    language = language.lower(); constraints = constraints or ImplementationConstraints(language)
    decision = _native_synthesis("DECIDE", language=language, expression=theory.expression,
        constraints=_serial(constraints), assumptions=theory.assumptions, provider=None)
    if "LANGUAGE_CONSTRAINT_MATCH" in decision["remaining_obligations"]:
        raise ValueError("SYNTHESIS_LANGUAGE_CONSTRAINT_MISMATCH")
    if any(item.startswith("AUTHORIZED_APPROXIMATION:") for item in decision["remaining_obligations"]):
        raise ValueError("APPROXIMATION_NOT_AUTHORIZED")
    if "SUPPORTED_TARGET_LANGUAGE" in decision["remaining_obligations"]:
        raise ValueError(f"UNSUPPORTED_SYNTHESIS_LANGUAGE: {language}")
    algorithm = AlgorithmIR(_id("algorithm", theory.expression), theory.expression, [], decision["status"])
    expected = ExpectedImplementationIR(theory.expression, language, theory.output)
    source, filename = _source(theory, language)
    generated = GeneratedImplementation(_id("generated", [language, source]), language, source, filename,
                                        algorithm, expected, "SOURCE_GENERATED")
    if output_path: generated.write(output_path)
    result = CodeSynthesisResult(theory, constraints, theory.expression, algorithm, expected, generated, None,
        [{"stage": "THEORY", "value": theory.expression}, {"stage": "ALGORITHM_IR", "value": theory.expression},
         {"stage": "GENERATED_SOURCE", "hash": sha256(source.encode()).hexdigest()}], "SOURCE_GENERATED")
    result.generation_decision = decision
    if verify: verify_round_trip(result)
    return result


def _normalize(node: Any) -> Any:
    return _native_synthesis("NORMALIZE", node=node)


def verify_round_trip(result: CodeSynthesisResult) -> RoundTripVerification:
    from .project import FormulaTracer
    generated = result.generated
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / generated.filename; path.write_text(generated.source, encoding="utf-8")
        if generated.language == "rust":
            (root / "Cargo.toml").write_text('[package]\nname = "formulatracer_generated"\nversion = "0.1.0"\nedition = "2021"\n\n[lib]\npath = "lib.rs"\n', encoding="utf-8")
            path = root / "Cargo.toml"
        try:
            analyzed = FormulaTracer(path, project_root=root).analyze()
            output = analyzed.outputs[0]
            observed = output.formula
            native = _native_synthesis("ROUND_TRIP", expected=result.expected_implementation_ir.expression, actual=observed)
            comparison = native["comparison"]
            divergence = SynthesisDivergence(**native["divergence"]) if native.get("divergence") else None
            status = native["status"]
            round_trip = RoundTripVerification(status, output.implementation, observed, comparison, divergence,
                                               output.end_to_end_status)
        except Exception as exc:
            native = _native_synthesis("ROUND_TRIP", expected=result.expected_implementation_ir.expression, error=str(exc))
            divergence = SynthesisDivergence(**native["divergence"])
            round_trip = RoundTripVerification(native["status"], None, None, native["comparison"], divergence, None)
    generated.round_trip = round_trip; result.round_trip = round_trip
    result.pipeline_trace += [{"stage": "OBSERVED_IMPLEMENTATION_IR", "value": round_trip.observed_implementation_ir},
                              {"stage": "OBSERVED_MATHEMATICAL_IR", "value": round_trip.observed_mathematical_ir}]
    result.status = round_trip.status
    return round_trip


def synthesize_cross_language(theory: TheorySpecification, *, languages: tuple[str, ...] = ("python", "rust", "cpp")) -> CrossLanguageSynthesisResult:
    results = {language: synthesize(theory, language=language) for language in languages}
    normalized = [_normalize(item.round_trip.observed_mathematical_ir) for item in results.values()
                  if item.round_trip and item.round_trip.observed_mathematical_ir]
    status = "SAME_CANONICAL_MATHEMATICAL_IR" if normalized and all(item == normalized[0] for item in normalized) else "CROSS_LANGUAGE_CANONICAL_IR_UNRESOLVED"
    return CrossLanguageSynthesisResult(results, status)


def propose_repair(finding: Any) -> RepairCandidate | None:
    native = _native_synthesis("PROPOSE_REPAIR", finding={
        "finding_id": finding.finding_id, "type": finding.type, "source": finding.source,
        "expected": finding.expected, "actual": finding.actual})
    return RepairCandidate(**native) if native else None


def verify_repair(candidate: RepairCandidate, repaired_source: str | Path, *, project_root: str | Path | None = None,
                  analyze_options: Mapping[str, Any] | None = None) -> RepairVerificationResult:
    from .project import FormulaTracer
    result = FormulaTracer(repaired_source, project_root=project_root).analyze(**dict(analyze_options or {}))
    debug = result.debug()
    native = _native_synthesis("VERIFY_REPAIR", debug_status=debug.status,
        end_to_end_status=result.end_to_end_status)
    candidate.status = native["candidate_status"]
    return RepairVerificationResult(candidate, result.status, result.end_to_end_status, debug.status,
                                    native["status"])
