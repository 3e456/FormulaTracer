"""Runnable examples used by the English and Japanese API usage guides."""

from __future__ import annotations

from pathlib import Path

from formulatracer import FormulaTracer, compare_ir, native_available, reconstruct


ROOT = Path(__file__).resolve().parents[1]


def source_audit_example() -> None:
    tracer = FormulaTracer.from_source(
        ROOT / "examples/python_audit/weighted_sum.py",
        project_root=ROOT / "examples/python_audit",
    )
    result = tracer.analyze(targets="weighted_score")
    output = result.get_output("weighted_score")
    print(result.status, output.status)
    print(output.name, output.formula["op"])


def formula_and_generation_example() -> None:
    formula = FormulaTracer.from_tex("x + 2", language="en")
    formula.assume("x is real")
    print(formula.to_tex())
    print(formula.inspect()["expression"])

    plan = formula.plan_generation(language="python", search="normal")
    candidate = plan.select()
    print(candidate.contract.provider_id, candidate.verification_status)

    generated = formula.generate(language="python", auto_select=True, verify=True)
    print(generated.source)
    print(generated.status)


def structured_result_and_function_example() -> None:
    expression = {
        "op": "Add",
        "args": [
            {
                "op": "Power",
                "args": [
                    {"op": "FreeVariable", "name": "x"},
                    {"op": "Constant", "value": 2},
                ],
            },
            {"op": "FreeVariable", "name": "a"},
        ],
    }
    result = compare_ir(expression, expression)
    print(result.status, result.relation.kind)
    print(result.to_json())

    function = result.theory.as_function()
    try:
        assert function.evaluate(x=3, a=2) == 11.0
        fixed = function.substitute(a=2)
        try:
            assert fixed(x=4) == 18.0
            print(fixed.to_tex(), fixed.inspect()["variables"])
        finally:
            fixed.close()
    finally:
        function.close()


def reconstruction_example() -> None:
    expression = {"op": "Constant", "value": 2}
    request = {
        "original_theory": expression,
        "reconstructed_theory": expression,
        "structural_facts": {},
        "temporaries": [],
        "result_expression": None,
        "safety": {},
        "algorithm_ir": None,
        "provider_projection": None,
        "relation_chain": [],
        "assumptions": [],
        "proof_obligations": [],
        "exact_egraph_verified": False,
        "error": None,
        "range": None,
        "provenance": None,
    }
    result = reconstruct(request)
    print(result.status)
    print(result.explain("en"))


def main() -> None:
    if not native_available():
        raise SystemExit("FormulaTracer native core is unavailable")
    source_audit_example()
    formula_and_generation_example()
    structured_result_and_function_example()
    reconstruction_example()


if __name__ == "__main__":
    main()
