from __future__ import annotations

import ast
from fractions import Fraction
import json
from pathlib import Path
import tempfile

import jsonschema
import pytest
import yaml

from cpp_audit import (
    AlgebraicStructure,
    BitRepresentation,
    DomainSemantics,
    MathematicalFactEngine,
    MathematicalKnowledgeRegistry,
    NumericDomain,
    PhysicalDimension,
    Quantity,
    ShiftSemantics,
    Unit,
    analyze_piecewise_domains,
    canonical_equal,
    canonicalize_logic,
    decode_bits,
    encode_bits,
    evaluate_logic,
    evaluate_bit_operation,
    mathematical_primitive_registry,
    recognize_bit_field_extract,
    run_exhaustive_bit_assurance,
    run_knowledge_assurance,
    saturate_and_match,
    select,
)
from cpp_audit.math_surface import parse_tex, to_tex
from cpp_audit.python_audit import audit_python


ROOT = Path(__file__).resolve().parents[1]


def v(name: str) -> dict:
    return {"op": "FreeVariable", "name": name}


def c(value: int) -> dict:
    return {"op": "Constant", "value": value}


def test_numeral_radix_is_presentation_but_value_is_canonical() -> None:
    source = "def calculate():\n    return 0xff + 0b1 + 0o2 + 3\n"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "radix.py"; path.write_text(source, encoding="utf-8")
        result = audit_python(path, function="calculate", mode="REPORT_ONLY", verify_lean=False)
    expression = result.implementation["outputs"][0]["expression"]
    constants = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, int)]
    assert sorted(item.value for item in constants) == [1, 2, 3, 255]
    rendered = json.loads(result.renderings["json"])
    radices = []
    def walk(node):
        if isinstance(node, dict):
            if "numeral_representation" in node: radices.append(node["numeral_representation"]["radix"])
            for value in node.values(): walk(value)
        elif isinstance(node, list):
            for value in node: walk(value)
    walk(rendered)
    assert sorted(radices) == [2, 8, 10, 16]
    assert canonical_equal(c(255), {"op": "Constant", "value": 255,
                                   "numeral_representation": {"radix": 16, "original_text": "0xff"}})
    assert expression["op"] == "Add"


def test_signed_unsigned_width_and_python_unbounded_semantics_are_distinct() -> None:
    u8 = BitRepresentation.unsigned(8)
    i8 = BitRepresentation.signed_twos_complement(8)
    assert encode_bits(255, u8) == 255 and decode_bits(255, u8) == 255
    assert encode_bits(-1, i8) == 255 and decode_bits(255, i8) == -1
    with pytest.raises(ValueError, match="NEGATIVE_VALUE"):
        encode_bits(-1, u8)
    assert evaluate_bit_operation("BitNot", (0,), u8) == 255
    assert evaluate_bit_operation("BitNot", (0,), BitRepresentation.python_int()) == -1
    assert evaluate_bit_operation("ShiftRight", (-2, 1), i8,
                                  shift_semantics=ShiftSemantics.ARITHMETIC_RIGHT) == -1
    assert evaluate_bit_operation("ShiftRight", (-2, 1), i8,
                                  shift_semantics=ShiftSemantics.LOGICAL_RIGHT) == 127
    with pytest.raises(ValueError, match="SHIFT_COUNT_OUT_OF_RANGE"):
        evaluate_bit_operation("ShiftLeft", (1, 8), u8)


def test_python_frontend_separates_bitwise_boolean_and_modulo() -> None:
    source = "def calculate(x, y, p, q):\n    return ((x & y) % 16, p and q, not p, x >> 2)\n"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bits.py"; path.write_text(source, encoding="utf-8")
        result = audit_python(path, function="calculate", mode="REPORT_ONLY", verify_lean=False)
    text = result.renderings["json"]
    assert '"op": "BitAnd"' in text and '"op": "Modulo"' in text
    assert '"op": "LogicalAnd"' in text and '"op": "LogicalNot"' in text
    assert '"semantic_domain": "UnresolvedBitDomain"' in text


def test_bitfield_recognition_requires_fixed_representation() -> None:
    rep = BitRepresentation.unsigned(32).to_dict()
    shifted = {"op": "ShiftRight", "args": [v("x"), c(8)], "bit_representation": rep}
    masked = {"op": "BitAnd", "args": [shifted, c(255)], "bit_representation": rep}
    result = recognize_bit_field_extract(masked)
    assert result and result["op"] == "BitFieldExtract"
    assert (result["offset"], result["width"]) == (8, 8)
    assert recognize_bit_field_extract({"op": "BitAnd", "args": [shifted, c(250)]}) is None


def test_declarative_bit_knowledge_requires_algebraic_structure_fact() -> None:
    left = {"op": "BitAnd", "args": [v("x"), c(255)], "semantic_domain": "UnboundedIntegerBits"}
    right = {"op": "Modulo", "args": [v("x"), c(256)]}
    blocked = saturate_and_match(left, right, authorized_rule_ids=["python_bitand_mask8_mod"],
                                 motifs=["bitvector", "mask", "modulo"])
    assert blocked.status == "EGRAPH_NO_EXACT_MATCH"
    assert any("algebraic_structure_one_of" in condition for item in blocked.saturation.blocked_rewrites
               for condition in item.missing_conditions)
    accepted = saturate_and_match(left, right, authorized_rule_ids=["python_bitand_mask8_mod"],
        facts=["algebraic_structure:COMMUTATIVE_RING"], motifs=["bitvector", "mask", "modulo"])
    assert accepted.status == "EGRAPH_EXACT_MATCH"


def test_nonexact_solver_and_sampling_knowledge_never_enter_exact_egraph() -> None:
    registry = MathematicalKnowledgeRegistry.default()
    assert registry.get("equation_newton_iteration").relation_kind == "APPROXIMATION"
    assert registry.get("continuous_fourier_sampling").relation_kind == "SAMPLING"
    exact_ids = {item.knowledge_id for item in registry.entries(exact_only=True)}
    assert "equation_newton_iteration" not in exact_ids
    assert "continuous_fourier_sampling" not in exact_ids


def test_fact_engine_rejects_domain_and_predicate_conflicts() -> None:
    facts = MathematicalFactEngine(["x > 0"])
    assert not facts.assert_fact("x <= 0") and facts.conflicts
    domains = MathematicalFactEngine(["numeric_domain:REAL"])
    assert not domains.assert_fact("numeric_domain:COMPLEX") and domains.conflicts
    structures = MathematicalFactEngine(["algebraic_structure:FIELD"])
    assert structures.knows("algebraic_structure:RING")


def test_logic_piecewise_preserves_branch_specific_assumptions() -> None:
    source = {"op": "IfThenElse", "condition": {"op": "Compare", "comparison": "NotEqual",
              "args": [v("x"), c(0)]}, "then": {"op": "Divide", "args": [c(1), v("x")]}, "else": c(0)}
    canonical = canonicalize_logic(source)
    assert canonical["op"] == "Select" and canonical["condition"]["op"] == "Predicate"
    domains = analyze_piecewise_domains(canonical)
    assert domains.status == "BRANCH_DOMAINS_PRESERVED" and len(domains.branches) == 2
    assert not domains.global_assumptions
    assert "cases" in to_tex(canonical)


def test_native_logic_truth_tables_and_select_preserve_lazy_branching() -> None:
    condition = {"op": "Predicate", "expression": {"op": "Constant", "value": True},
                 "codomain": "Boolean"}
    expression = select(condition["expression"], c(7), c(9))
    visited: list[int | bool] = []

    def evaluator(node: dict, _env: dict) -> int | bool:
        value = node["value"]
        visited.append(value)
        return value

    assert evaluate_logic(expression, {}, evaluator) == 7
    assert visited == [True, 7]
    implies = {"op": "Implies", "args": [c(True), c(False)]}
    assert evaluate_logic(implies, {}, evaluator) is False


def test_surface_dsl_supports_logic_bits_modulo_and_complex_primitives() -> None:
    _, selection, _ = parse_tex("select(x > 0, bitand(x, 255), mod(x, 256))")
    assert selection["op"] == "Select"
    assert selection["then"]["op"] == "BitAnd"
    assert selection["else"]["op"] == "Modulo"
    _, conjugate, _ = parse_tex("conj(z)")
    assert conjugate["op"] == "Conjugate"


def test_knowledge_registry_schema_metrics_and_directions() -> None:
    registry = MathematicalKnowledgeRegistry.default()
    metrics = registry.metrics()
    assert metrics["entries"] >= 30
    assert {"BITVECTOR", "LOGIC_CONDITIONS", "SETS_RELATIONS", "COMPLEX", "POLYNOMIALS",
            "EQUATIONS_SOLVERS", "UNITS_DIMENSIONS"} <= set(metrics["categories"])
    assert not registry.validate()
    schema = json.loads((ROOT / "schemas/mathematical-knowledge-registry.schema.json").read_text(encoding="utf-8"))
    for path in (ROOT / "registry/mathematical_knowledge").glob("*.yaml"):
        jsonschema.Draft202012Validator(schema).validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_knowledge_assurance_schema_and_soundness_gates() -> None:
    report = run_knowledge_assurance(bit_width=4)
    payload = report.to_dict()
    schema = json.loads((ROOT / "schemas/knowledge-assurance-report.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert payload["release_gates"]["CRITICAL_EGRAPH_FALSE_MERGE_OPEN"] == 0
    assert payload["release_gates"]["CRITICAL_BITVECTOR_FALSE_ACCEPTANCE_OPEN"] == 0


def test_primitive_registry_has_no_duplicates_and_covers_foundational_tiers() -> None:
    primitives = mathematical_primitive_registry(); names = [item.name for item in primitives]
    assert len(names) == len(set(names))
    categories = {item.category for item in primitives}
    assert {"ALGEBRAIC_STRUCTURES", "BINDERS", "LOGIC_CONDITIONS", "SETS_RELATIONS",
            "INTEGER_BITVECTOR", "POLYNOMIALS", "EQUATIONS_SOLVERS", "UNITS_DIMENSIONS"} <= categories
    assert len(primitives) >= 150


def test_domain_hierarchy_units_and_exhaustive_unsigned8_assurance() -> None:
    real = DomainSemantics.for_domain(NumericDomain.REAL)
    assert real.satisfies([AlgebraicStructure.FIELD, AlgebraicStructure.RING])
    natural = DomainSemantics.for_domain(NumericDomain.NATURAL)
    assert natural.satisfies([AlgebraicStructure.COMMUTATIVE_SEMIRING])
    assert not natural.satisfies([AlgebraicStructure.RING])
    length = PhysicalDimension.from_mapping({"L": 1})
    metre = Unit("m", length); centimetre = Unit("cm", length, Fraction(1, 100))
    assert Quantity(Fraction(100), centimetre).convert_to(metre).value == 1
    with pytest.raises(ValueError, match="UNIT_DIMENSION_MISMATCH"):
        Quantity(Fraction(1), metre).convert_to(Unit("s", PhysicalDimension.from_mapping({"T": 1})))
    assurance = run_exhaustive_bit_assurance(width=8)
    assert assurance.cases == 3 * 256 * 256 + 256
    assert assurance.failed == assurance.false_acceptance == 0
