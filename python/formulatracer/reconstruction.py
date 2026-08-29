"""Thin object projection for Rust-owned reconstruction semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .native import execute_native_kernel


@dataclass(frozen=True)
class ReconstructionResult:
    raw: dict[str, Any]

    @property
    def status(self) -> str: return str(self.raw["status"])
    @property
    def relation_chain(self) -> tuple[dict[str, Any], ...]: return tuple(self.raw["relation_chain"])
    @property
    def assumptions(self) -> tuple[str, ...]: return tuple(self.raw["assumptions"])
    @property
    def proof_obligations(self) -> tuple[str, ...]: return tuple(self.raw["proof_obligations"])
    @property
    def unresolved_reason(self) -> dict[str, Any] | None: return self.raw.get("unresolved_reason")
    @property
    def structural_witness(self) -> dict[str, Any] | None: return self.raw.get("structural_witness")
    def to_dict(self) -> dict[str, Any]: return dict(self.raw)
    def explain(self, language: str = "en") -> str:
        reason = self.unresolved_reason
        if language.lower().startswith("ja"):
            return (f"再構成: {self.status}" if reason is None else
                    f"再構成: {self.status}（{reason.get('code', '理由不明')}）")
        return (f"Reconstruction: {self.status}" if reason is None else
                f"Reconstruction: {self.status} ({reason.get('code', 'unknown reason')})")


def reconstruct(request: Mapping[str, Any]) -> ReconstructionResult:
    raw = execute_native_kernel({
        "schema_version": "1.0",
        "kernel": "F",
        "operation": "RECONSTRUCT",
        "request": dict(request),
    })["result"]
    return ReconstructionResult(raw)
