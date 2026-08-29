"""Minimal exact physical-dimension and affine unit-conversion semantics."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping


def _fraction(value: Fraction) -> dict[str, str]:
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _unit(value: "Unit") -> dict[str, object]:
    return {"symbol": value.symbol, "dimension": [list(item) for item in value.dimension.exponents],
            "scale": _fraction(value.scale), "offset": _fraction(value.offset)}


def _native(action: str, **payload: object) -> dict[str, object]:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "A",
            "operation": "UNITS", "action": action, **payload})["result"]


def _result_fraction(value: object) -> Fraction:
    if not isinstance(value, dict): raise ValueError("UNIT_NATIVE_RESULT_INVALID")
    return Fraction(int(value["numerator"]), int(value["denominator"]))


@dataclass(frozen=True)
class PhysicalDimension:
    exponents: tuple[tuple[str, int], ...]

    @classmethod
    def from_mapping(cls, values: Mapping[str, int]) -> "PhysicalDimension":
        result = _native("DIMENSION_FROM_MAPPING", values=dict(values))
        return cls(tuple((str(key), int(exponent)) for key, exponent in result["exponents"]))

    def multiply(self, other: "PhysicalDimension") -> "PhysicalDimension":
        result = _native("DIMENSION_MULTIPLY", left=[list(item) for item in self.exponents],
                         right=[list(item) for item in other.exponents])
        return PhysicalDimension(tuple((str(key), int(exponent)) for key, exponent in result["exponents"]))

    def divide(self, other: "PhysicalDimension") -> "PhysicalDimension":
        result = _native("DIMENSION_DIVIDE", left=[list(item) for item in self.exponents],
                         right=[list(item) for item in other.exponents])
        return PhysicalDimension(tuple((str(key), int(exponent)) for key, exponent in result["exponents"]))


@dataclass(frozen=True)
class Unit:
    symbol: str
    dimension: PhysicalDimension
    scale: Fraction = Fraction(1)
    offset: Fraction = Fraction(0)


@dataclass(frozen=True)
class Quantity:
    value: Fraction
    unit: Unit

    def convert_to(self, target: Unit) -> "Quantity":
        from formulatracer.native import NativeCallError
        try:
            result = _native("CONVERT", value=_fraction(self.value), source=_unit(self.unit), target=_unit(target))
        except NativeCallError as error:
            if "UNIT_DIMENSION_MISMATCH" in str(error): raise ValueError("UNIT_DIMENSION_MISMATCH") from error
            raise
        return Quantity(_result_fraction(result["value"]), target)

    def add(self, other: "Quantity") -> "Quantity":
        from formulatracer.native import NativeCallError
        try:
            result = _native("ADD", left_value=_fraction(self.value), left_unit=_unit(self.unit),
                             right_value=_fraction(other.value), right_unit=_unit(other.unit))
        except NativeCallError as error:
            if "UNIT_DIMENSION_MISMATCH" in str(error): raise ValueError("UNIT_DIMENSION_MISMATCH") from error
            raise
        return Quantity(_result_fraction(result["value"]), self.unit)


# Static declarations avoid invoking the interop layer while the public package
# facade itself is still importing this module.
MASS = PhysicalDimension((("M", 1),))
LENGTH = PhysicalDimension((("L", 1),))
TIME = PhysicalDimension((("T", 1),))
TEMPERATURE = PhysicalDimension((("Theta", 1),))
