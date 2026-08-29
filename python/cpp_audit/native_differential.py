"""Migration-only Python-reference versus Rust-candidate differential checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from formulatracer.native import compare_ir
from .math_surface import _reference_canonical_equal, _reference_to_tex


@dataclass(frozen=True)
class NativeDifferentialResult:
    case_id: str
    python_equal: bool
    rust_status: str
    semantic_match: bool
    tex_match: bool
    false_acceptance: bool


def compare_case(case_id: str, theory: dict[str, Any], implementation: dict[str, Any]) -> NativeDifferentialResult:
    python_equal = _reference_canonical_equal(theory, implementation)
    native = compare_ir(theory, implementation)
    rust_equal = native.status == "EXACT_EQUALITY"
    expected_tex = _reference_to_tex(implementation)
    return NativeDifferentialResult(case_id, python_equal, native.status,
                                    python_equal == rust_equal, expected_tex == native.tex,
                                    rust_equal and not python_equal)


def run_native_differential(cases: Iterable[tuple[str, dict[str, Any], dict[str, Any]]], output: str | Path | None = None) -> dict[str, Any]:
    results = [compare_case(*case) for case in cases]
    report = {"schema_version":"1.0", "engine_mode":"MIGRATION_DUAL_ENGINE_ONLY",
              "results":[asdict(item) for item in results],
              "semantic_matches":sum(item.semantic_match for item in results),
              "tex_matches":sum(item.tex_match for item in results),
              "cases":len(results), "false_acceptance":sum(item.false_acceptance for item in results)}
    if output:
        target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report
