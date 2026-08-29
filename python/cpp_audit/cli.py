"""Command line interface for cpp-audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

from .core import (AuditError, audit, extract_ir, json_text, load_registry,
                   load_spec, normalize, registry_hash, render_dot,
                   render_markdown)
from .pipeline import (canonical_graph_interpret, human_reference,
                       implementation_ir_interpret, load_implementation_ir,
                       normalize_clang_ir, run_frontend)
from .expression import (compare_exact, expression_from_file, expression_report,
                         load_formula, load_transformation_rule,
                         load_transformation_set, normalize_exact,
                         render_expression, select_transformation)
from .dependency import build_dependency_graph, extract_output_slice
from .python_audit import AuditMode, audit_python, render_python_report
from .audit_execution import execute_audit, write_certificate
from .python_cfg import build_python_cfg
from .numeric_types import analyze_numeric_types
from .ieee754 import RoundingMode
from .parallel_semantics import analyze_parallel_semantics
from .transformations import apply_transformation_set
from .library_contracts import (LibraryContractRegistry, write_inventory_candidates,
                                write_inventory_coverage)
from .project import FormulaTracer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cpp-audit")
    parser.add_argument("--registry", default="registry/std")
    parser.add_argument("--standard", choices=["cpp17", "cpp20"], default="cpp20")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("parse", "extract-ir", "normalize"):
        item = sub.add_parser(command); item.add_argument("source")
    for command in ("compare", "explain", "graph", "lean-export", "verify"):
        item = sub.add_parser(command); item.add_argument("spec"); item.add_argument("source")
    item = sub.add_parser("frontend-ir")
    item.add_argument("source"); item.add_argument("--frontend", required=True)
    item.add_argument("--build-dir", required=True); item.add_argument("--function", required=True)
    item.add_argument("--output", required=True)
    for command in ("normalize-ir", "verify-ir", "lean-export-ir"):
        item = sub.add_parser(command); item.add_argument("spec"); item.add_argument("implementation_ir")
    item = sub.add_parser("interpret")
    item.add_argument("spec"); item.add_argument("implementation_ir"); item.add_argument("inputs")
    item = sub.add_parser("registry-status")
    item.add_argument("--format", choices=["json", "markdown"], default="json")
    item = sub.add_parser("expression")
    item.add_argument("--ir", required=True)
    item.add_argument("--format", choices=["latex", "unicode", "markdown", "json"], default="unicode")
    item = sub.add_parser("formula-parse")
    item.add_argument("--formula", required=True)
    item.add_argument("--format", choices=["latex", "unicode", "markdown", "json"], default="json")
    for command in ("dependency-graph", "output-slice"):
        item = sub.add_parser(command); item.add_argument("--ir", required=True)
    for command in ("compare-formulas", "expression-report"):
        item = sub.add_parser(command)
        item.add_argument("--human-formula", required=True)
        item.add_argument("--implementation-ir", required=True)
        item.add_argument("--transformation-set")
        item.add_argument("--selection-profile", choices=["minimum_cost", "minimum_error", "frequency_fidelity", "stability", "locality"], default="minimum_cost")
        item.add_argument("--require-observable", action="append", default=[])
        if command == "expression-report": item.add_argument("--output", required=True)
    item = sub.add_parser("python-audit")
    item.add_argument("source")
    item.add_argument("--function")
    item.add_argument("--output")
    item.add_argument("--mode", choices=[item.value for item in AuditMode], default=AuditMode.STRICT.value)
    item.add_argument("--report")
    item.add_argument("--json-output")
    item.add_argument("--lean-file")
    item.add_argument("--no-lean", action="store_true")
    item.add_argument("--library-version", action="append", default=[], metavar="PACKAGE=VERSION")
    item = sub.add_parser("python-cfg")
    item.add_argument("source")
    item.add_argument("--function", required=True)
    item.add_argument("--output")
    item = sub.add_parser("python-certificate")
    item.add_argument("source")
    item.add_argument("--inputs", required=True)
    item.add_argument("--function")
    item.add_argument("--output")
    item.add_argument("--mode", choices=[item.value for item in AuditMode], default=AuditMode.STRICT.value)
    item.add_argument("--json-output", required=True)
    item.add_argument("--latex-output", required=True)
    item.add_argument("--lean-file")
    item.add_argument("--source-provenance")
    item.add_argument("--input-dtypes", help="JSON file mapping input names to dtype contracts")
    item.add_argument("--rounding-mode", choices=[item.value for item in RoundingMode], default=RoundingMode.ROUND_TO_NEAREST_TIES_TO_EVEN.value)
    item.add_argument("--transformation-set")
    item.add_argument("--transformation-rule", action="append", default=[])
    item.add_argument("--transformation-assumption", action="append", default=[])
    item.add_argument("--transformation-context", help="JSON file containing hard-constraint evidence")
    item.add_argument("--error-specification", help="JSON file defining metric and tolerance policy")
    item.add_argument("--error-propagation", help="JSON file defining conservative graph propagation contracts")
    item.add_argument("--selection-profile", choices=["minimum_cost", "minimum_error", "frequency_fidelity", "stability", "locality"], default="minimum_cost")
    item.add_argument("--no-lean", action="store_true")
    item = sub.add_parser("python-dtypes")
    item.add_argument("source")
    item.add_argument("--function", required=True)
    item.add_argument("--output")
    item.add_argument("--inputs")
    item.add_argument("--input-dtypes")
    item = sub.add_parser("python-parallel")
    item.add_argument("source")
    item.add_argument("--function", required=True)
    item.add_argument("--inputs")
    item.add_argument("--input-dtypes")
    item = sub.add_parser("library-contract-candidates")
    item.add_argument("--inventory", required=True)
    item.add_argument("--output", required=True)
    item.add_argument("--library-registry", default="registry/libraries")
    item.add_argument("--coverage-output")
    item.add_argument("--type-evidence")
    item = sub.add_parser("project-analyze")
    item.add_argument("source")
    item.add_argument("--project-root")
    item.add_argument("--target", action="append", default=[])
    item.add_argument("--json-output")
    item.add_argument("--latex-output")
    return parser


def _transformation_set_path(value: str) -> Path:
    path = Path(value)
    if path.is_file(): return path
    built_in = Path("registry/transformations/sets") / f"{value}.yaml"
    if built_in.is_file(): return built_in
    raise AuditError(f"TransformationSet not found: {value}")


def _load_set_rules(item: dict[str, object]) -> list[dict[str, object]]:
    rules = []
    for rule_id in item.get("approximation_rules", []):
        path = Path("registry/transformations/rules") / f"{rule_id}.yaml"
        if not path.is_file(): raise AuditError(f"TransformationRule not found: {rule_id}")
        rules.append(load_transformation_rule(path))
    return rules


def _expression_command(args: argparse.Namespace) -> int:
    if args.command in {"dependency-graph", "output-slice"}:
        graph = build_dependency_graph(load_implementation_ir(args.ir))
        value = graph if args.command == "dependency-graph" else extract_output_slice(graph)
        print(json_text(value), end="")
        wanted = "DEPENDENCY_GRAPH_BUILT" if args.command == "dependency-graph" else "OUTPUT_SLICE_EXTRACTED"
        return 0 if value["status"] == wanted else 1
    if args.command == "expression":
        expression = expression_from_file(args.ir, args.registry)
        print(render_expression(expression, args.format), end="")
        return 0 if expression["status"] == "EXPRESSION_EXTRACTED" else 1
    if args.command == "formula-parse":
        formula = load_formula(args.formula)
        rendered = normalize_exact(formula) if args.format == "json" else formula
        print(json_text(rendered) if args.format == "json" else render_expression(formula, args.format), end="")
        return 0
    implementation, human = expression_from_file(args.implementation_ir, args.registry), load_formula(args.human_formula)
    if implementation["status"] != "EXPRESSION_EXTRACTED":
        print(json_text(implementation), end=""); return 1
    comparison = compare_exact(implementation, human)
    transformation_set = selection = None
    if args.transformation_set:
        transformation_set = load_transformation_set(_transformation_set_path(args.transformation_set))
        if comparison["match"]:
            selection = {"status": "EXACT_MATCH_APPROXIMATION_NOT_REQUIRED", "selected": None,
                         "candidates": [], "selection_reason": "exact canonical formulas already match"}
        else:
            selection = select_transformation(transformation_set, _load_set_rules(transformation_set),
                                              args.require_observable, args.selection_profile)
    if args.command == "compare-formulas":
        print(json_text({"comparison": comparison, "transformation_set": transformation_set,
                         "selection": selection, "selection_profile": args.selection_profile}), end="")
        return 0 if comparison["match"] else 1
    report = expression_report(implementation, human, comparison, transformation_set, selection)
    Path(args.output).write_text(report, encoding="utf-8")
    print(json_text({"status": comparison["status"], "output": str(args.output)}), end="")
    return 0 if comparison["match"] else 1


def _provenance_lean(ir: dict[str, object]) -> str:
    digest, function = str(ir["source_hash"]), str(ir["function"])
    namespace = "WeightedSumInnerProduct" if ir.get("analysis", {}).get("style") == "inner_product" else "WeightedSumLoop"
    implementation = "cppInnerProductWeightedSum" if ir.get("analysis", {}).get("style") == "inner_product" else "cppLoopWeightedSum"
    return f'''import CppAudit.Graph.Graph
import CppAudit.Representation.Isomorphism
import CppAudit.Refinement.WeightedSum

namespace CppAudit.Generated.{namespace}

/-- Generated from Clang Implementation IR for `{function}`. -/
def implementationSourceHash : String := "{digest}"

def generatedImplementation := {implementation}

def generatedGraph : Graph :=
  {{ values := [{{ id := "quantity", kind := .input }},
                {{ id := "factor", kind := .input }},
                {{ id := "result", kind := .output }}]
    operations := [{{ id := "multiply", kind := .multiply, effect := .pure }},
                   {{ id := "fold-input", kind := .transformReduce, effect := .pure }}]
    edges := [{{ source := "quantity", target := "multiply", argumentIndex := 0, argumentRole := "lhs" }},
              {{ source := "factor", target := "multiply", argumentIndex := 1, argumentRole := "rhs" }},
              {{ source := "multiply", target := "fold-input", argumentIndex := 0, argumentRole := "input" }}] }}

theorem generated_graph_well_formed : generatedGraph.wellFormed := by
  simp [Graph.wellFormed, Graph.effectsKnown, generatedGraph]

theorem generated_representation_valid (input : HumanInput) :
    (encodeInput input).factor = input.factor := by rfl

theorem generated_implementation_refines (quantity factor : List Int) :
    generatedImplementation quantity factor = humanWeightedSum quantity factor := by rfl

end CppAudit.Generated.{namespace}
'''


def _ir_command(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    ir = load_implementation_ir(args.implementation_ir)
    result = normalize_clang_ir(ir, spec, args.registry)
    if args.command == "lean-export-ir":
        if result.status != "PASS":
            print(json_text({"status": result.status, "diagnostics": result.diagnostics}), end=""); return 1
        print(_provenance_lean(ir), end=""); return 0
    if args.command == "normalize-ir":
        print(json_text({"status": result.status, "canonical_graph": result.canonical_graph,
                         "diagnostics": result.diagnostics, "registry_usage": result.registry_usage}), end="")
        return 0 if result.status == "PASS" else 1
    if args.command == "verify-ir":
        print(json_text({"status": result.status, "proof_level": result.proof_level,
                         "diagnostics": result.diagnostics, "assumptions": result.assumptions,
                         "registry_usage": result.registry_usage,
                         "canonical_graph": result.canonical_graph}), end="")
        return 0 if result.status == "PASS" else 1
    if result.status != "PASS":
        print(json_text({"status": result.status, "diagnostics": result.diagnostics}), end=""); return 1
    inputs = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
    quantity, factor = inputs["quantity"], inputs["factor"]
    values = {"implementation_ir": implementation_ir_interpret(ir, quantity, factor),
              "canonical_graph": canonical_graph_interpret(result.canonical_graph, quantity, factor),
              "human_reference": human_reference(quantity, factor)}
    values["all_equal"] = values["implementation_ir"] == values["canonical_graph"] == values["human_reference"]
    print(json_text(values), end=""); return 0 if values["all_equal"] else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        if args.command == "project-analyze":
            result = FormulaTracer(args.source, project_root=args.project_root).analyze(args.target or None)
            if args.json_output: result.write_json(args.json_output)
            if args.latex_output: result.write_latex(args.latex_output)
            if not args.json_output and not args.latex_output: print(result.to_json(), end="")
            return 1 if result.status == "PROJECT_FAILED" else 0
        if args.command == "python-cfg":
            graph = build_python_cfg(args.source, function=args.function, output=args.output)
            print(json_text(graph.to_dict()), end="")
            return 0 if graph.summary["cfg_status"] == "CFG_RESOLVED" else 1
        if args.command == "python-dtypes":
            inputs = json.loads(Path(args.inputs).read_text(encoding="utf-8")) if args.inputs else {}
            dtypes = json.loads(Path(args.input_dtypes).read_text(encoding="utf-8")) if args.input_dtypes else {}
            result = analyze_numeric_types(args.source, function=args.function, output=args.output,
                                           inputs=inputs, input_dtypes=dtypes)
            print(json_text(result.to_dict()), end="")
            return 0 if result.status == "TYPE_RESOLVED" else 1
        if args.command == "python-parallel":
            inputs = json.loads(Path(args.inputs).read_text(encoding="utf-8")) if args.inputs else {}
            dtypes = json.loads(Path(args.input_dtypes).read_text(encoding="utf-8")) if args.input_dtypes else {}
            types = analyze_numeric_types(args.source, function=args.function, inputs=inputs, input_dtypes=dtypes)
            result = analyze_parallel_semantics(args.source, function=args.function, numeric_types=types)
            print(json_text(result.to_dict()), end="")
            return 0 if result.status == "PARALLEL_SEMANTICS_RESOLVED" else 1
        if args.command == "python-certificate":
            inputs = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
            dtypes = json.loads(Path(args.input_dtypes).read_text(encoding="utf-8")) if args.input_dtypes else None
            provenance = json.loads(Path(args.source_provenance).read_text(encoding="utf-8")) if args.source_provenance else None
            transformation_context = json.loads(Path(args.transformation_context).read_text(encoding="utf-8")) if args.transformation_context else None
            error_specification = json.loads(Path(args.error_specification).read_text(encoding="utf-8")) if args.error_specification else None
            error_propagation = json.loads(Path(args.error_propagation).read_text(encoding="utf-8")) if args.error_propagation else None
            result = execute_audit(args.source, inputs=inputs, output=args.output, function=args.function,
                                   mode=args.mode, verify_lean=not args.no_lean, lean_file=args.lean_file,
                                   source_provenance=provenance, input_dtypes=dtypes, rounding_mode=args.rounding_mode,
                                   transformation_set=args.transformation_set,
                                   requested_transformations=args.transformation_rule or None,
                                   transformation_assumptions=args.transformation_assumption,
                                   transformation_context=transformation_context,
                                   error_specification=error_specification,
                                   error_propagation=error_propagation,
                                   selection_profile=args.selection_profile)
            write_certificate(result, json_path=args.json_output, latex_path=args.latex_output)
            print(json_text({"status": result.status, "audit_id": result.audit_id,
                             "json": str(Path(args.json_output)), "latex": str(Path(args.latex_output))}), end="")
            return 0 if result.status != "VERIFICATION_FAILED" or args.mode == AuditMode.REPORT_ONLY.value else 1
        if args.command == "library-contract-candidates":
            payload = write_inventory_candidates(args.inventory, args.output,
                                                 LibraryContractRegistry(args.library_registry),
                                                 args.type_evidence)
            coverage = (write_inventory_coverage(args.inventory, args.coverage_output,
                                                  LibraryContractRegistry(args.library_registry),
                                                  args.type_evidence)
                        if args.coverage_output else None)
            print(json_text({"status": payload["status"], "candidate_count": len(payload["candidates"]),
                             "output": str(Path(args.output)),
                             "coverage_output": str(Path(args.coverage_output)) if coverage else None,
                             "coverage": coverage["counts"] if coverage else None}), end="")
            return 0
        if args.command == "python-audit":
            versions = {}
            for value in args.library_version:
                if "=" not in value:
                    raise AuditError("--library-version must be PACKAGE=VERSION")
                package, version = value.split("=", 1)
                versions[package] = version
            result = audit_python(args.source, output=args.output, function=args.function, mode=args.mode,
                                  lean_file=args.lean_file, verify_lean=not args.no_lean,
                                  library_versions=versions)
            report = render_python_report(result)
            if args.report: Path(args.report).write_text(report, encoding="utf-8")
            if args.json_output: Path(args.json_output).write_text(json_text(result.to_dict()), encoding="utf-8")
            if not args.report and not args.json_output: print(report, end="")
            return 0 if result.status in {"PASS", "PASS_WITH_FINDINGS"} else 1
        if args.command in {"dependency-graph", "output-slice", "expression", "formula-parse", "compare-formulas", "expression-report"}:
            return _expression_command(args)
        if args.command == "frontend-ir":
            data = run_frontend(args.frontend, args.build_dir, args.source, args.function, args.output)
            print(json_text(data), end=""); return 0
        if args.command in {"normalize-ir", "verify-ir", "lean-export-ir", "interpret"}:
            return _ir_command(args)
        if args.command == "registry-status":
            entities = load_registry(args.registry, args.standard)
            states: dict[str, int] = {}
            for entry in entities.values(): states[entry["proof_status"]] = states.get(entry["proof_status"], 0) + 1
            total = len(entities)
            result = {"standard_version": args.standard, "registered_entities": total,
                      "classification_rate": 1.0 if total else 0.0,
                      "semantic_adapter_rate": sum(bool(x.get("lowering")) for x in entities.values()) / total if total else 0.0,
                      "lean_verified_entities": sum(x["proof_status"] == "SEMANTICALLY_VERIFIED" for x in entities.values()),
                      "environment_dependent_entities": sum(x["proof_status"] == "ENVIRONMENT_DEPENDENT" for x in entities.values()),
                      "unsupported_entities": sum(x["proof_status"] == "UNSUPPORTED_SEMANTICS" for x in entities.values()),
                      "states": states, "registry_hash": registry_hash(args.registry),
                      "global_coverage": "GLOBAL_COVERAGE_NOT_AVAILABLE"}
            print(json_text(result), end=""); return 0
        if args.command == "parse":
            ir = extract_ir(args.source, args.standard, args.registry)
            print(json_text({"function": ir["function"], "implementation_style": ir["implementation_style"], "diagnostics": ir["diagnostics"]}), end="")
            return 1 if ir["diagnostics"] else 0
        if args.command == "extract-ir": print(json_text(extract_ir(args.source, args.standard, args.registry)), end=""); return 0
        if args.command == "normalize": print(json_text(normalize(extract_ir(args.source, args.standard, args.registry))), end=""); return 0
        if args.command == "verify":
            raise AuditError("direct source verification is disabled; run frontend-ir then verify-ir")
        result = audit(args.spec, args.source, args.standard, args.registry)
        if args.command == "compare": print(json_text(result.to_dict()), end="")
        elif args.command == "explain": print(render_markdown(result), end="")
        elif args.command == "graph": print(render_dot(result.semantic_graph))
        elif args.command == "lean-export":
            raise AuditError("source-based Lean export is disabled; use lean-export-ir")
        return 0 if result.status == "PASS" else 1
    except (AuditError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"cpp-audit: error: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
