"""Thin inspection API for Rust-owned structural comparison aids."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .native import execute_native_kernel


@dataclass(frozen=True)
class QuotientNormalizationResult:
    raw: dict[str, Any]

    @property
    def status(self) -> str: return str(self.raw["status"])
    @property
    def representative(self) -> dict[str, Any]: return self.raw["representative"]
    @property
    def witness(self) -> dict[str, Any]: return self.raw["witness"]
    def to_dict(self) -> dict[str, Any]: return dict(self.raw)


@dataclass(frozen=True)
class StructuralIsomorphismResult:
    raw: dict[str, Any]

    @property
    def status(self) -> str: return str(self.raw["status"])
    @property
    def mapping(self) -> dict[str, str]: return dict(self.raw["witness"]["mapping"])
    @property
    def binder_mapping(self) -> dict[str, str]: return dict(self.raw["witness"]["binder_mapping"])
    @property
    def witness(self) -> dict[str, Any]: return self.raw["witness"]
    @property
    def comparison_may_proceed(self) -> bool: return bool(self.raw["comparison_may_proceed"])
    @property
    def establishes_mathematical_equality(self) -> bool: return False
    def to_dict(self) -> dict[str, Any]: return dict(self.raw)
    def explain(self, language: str = "en") -> str:
        if language.lower().startswith("ja"):
            return f"構造比較: {self.status}（比較補助であり、数学的証明ではありません）"
        return f"Structural comparison: {self.status} (comparison aid, not mathematical proof)"


def quotient_normalize(expression: Mapping[str, Any], *, facts: Mapping[str, Any] | None = None) -> QuotientNormalizationResult:
    raw = execute_native_kernel({"schema_version": "1.0", "kernel": "B",
                                 "operation": "QUOTIENT_NORMALIZE",
                                 "expression": dict(expression), "facts": dict(facts or {})})["result"]
    return QuotientNormalizationResult(raw)


def structural_isomorphism(left: Mapping[str, Any], right: Mapping[str, Any], *,
                           facts: Mapping[str, Any] | None = None) -> StructuralIsomorphismResult:
    raw = execute_native_kernel({"schema_version": "1.0", "kernel": "B",
                                 "operation": "STRUCTURAL_ISOMORPHISM",
                                 "left": dict(left), "right": dict(right),
                                 "facts": dict(facts or {})})["result"]
    return StructuralIsomorphismResult(raw)
