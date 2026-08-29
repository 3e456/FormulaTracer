"""Focused native-ownership gate for exact unit semantics."""

from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path

from cpp_audit.units import PhysicalDimension, Quantity, Unit
from formulatracer.runtime_paths import reset_semantic_runtime_metrics, semantic_runtime_snapshot


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    reset_semantic_runtime_metrics()
    length = PhysicalDimension.from_mapping({"L": 1})
    time = PhysicalDimension.from_mapping({"T": 1})
    velocity = length.divide(time)
    metre = Unit("m", length)
    centimetre = Unit("cm", length, Fraction(1, 100))
    celsius = Unit("degC", PhysicalDimension.from_mapping({"Theta": 1}), Fraction(1), Fraction(27315, 100))
    kelvin = Unit("K", celsius.dimension)
    converted = Quantity(Fraction(20), celsius).convert_to(kelvin)
    added = Quantity(Fraction(1), metre).add(Quantity(Fraction(50), centimetre))
    mismatch_closed = False
    try:
        Quantity(Fraction(1), metre).convert_to(Unit("s", time))
    except ValueError as error:
        mismatch_closed = str(error) == "UNIT_DIMENSION_MISMATCH"
    runtime = semantic_runtime_snapshot()
    checks = {
        "dimension_division": dict(velocity.exponents) == {"L": 1, "T": -1},
        "affine_conversion": converted.value == Fraction(5863, 20),
        "addition_with_conversion": added.value == Fraction(3, 2),
        "dimension_mismatch_fail_closed": mismatch_closed,
        "native_path_only": runtime["RUST_NATIVE_SEMANTIC_CALLS"] >= 6
            and runtime["PYTHON_REFERENCE_CALLS"] == 0
            and runtime["PYTHON_SEMANTIC_FALLBACK_COUNT"] == 0
            and runtime["UNSUPPORTED_COUNT"] == 0
            and runtime["UNRESOLVED_COUNT"] == 1,
    }
    payload = {"schema_version":"1.0","component":"cpp_audit.units","native_operation":"A/UNITS",
               "status":"PASS" if all(checks.values()) else "FAIL","checks":checks,"runtime":runtime}
    destination = ROOT / "output/native_migration/final/units-parity.json"
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
