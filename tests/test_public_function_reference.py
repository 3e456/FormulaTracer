from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from cpp_audit import theory
from formulatracer import native_available


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "public_function_reference"


def load(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_all_stable_symbols_have_bilingual_entries_and_current_signatures() -> None:
    inventory = load("public-api-inventory.json")["items"]
    stable = {row["qualified_symbol"] for row in inventory if row["stability"] == "PUBLIC_STABLE"}
    parity = load("en-ja-symbol-parity.json")
    assert set(parity["en_documented"]) == stable
    assert set(parity["ja_documented"]) == stable
    assert parity["en_without_ja"] == parity["ja_without_en"] == []
    signatures = load("signature-parity.json")
    assert signatures["signature_mismatches"] == []
    assert signatures["default_mismatches"] == []


def test_evidence_and_provider_claim_boundaries_are_not_overstated() -> None:
    evidence = load("evidence-reference.json")
    assert evidence["user_declared_is_verification"] is False
    assert evidence["runtime_is_proof"] is False
    assert evidence["structural_is_proof"] is False
    providers = load("provider-reference.json")
    assert providers["catalog_count_is_supported_function_count"] is False
    assert all(item["entire_library_supported"] is False for item in providers["providers"])


def test_user_theory_decorator_is_metadata_only() -> None:
    @theory(output="y", expression="y = sum(i=0..n-1, x[i])")
    def custom_sum(x):
        return sum(x)

    assert custom_sum([1, 2, 3]) == 6
    assert custom_sum.__audit_theory__["output"] == "y"


def test_reference_assessment_has_no_stale_or_false_claim_gate() -> None:
    result = load("final-assessment.json")
    assert result["FUNCTION_REFERENCE_RELEASE_READY"] is True
    assert result["gates"]["DOCUMENTED_SYMBOL_NOT_FOUND"] == 0
    assert result["gates"]["FALSE_VERIFICATION_CLAIM_IN_DOCS"] == 0
    assert result["gates"]["PROVIDER_OVERCLAIM_IN_DOCS"] == 0


def test_bilingual_usage_guides_document_reference_level_details() -> None:
    english = (ROOT / "docs/reference/api-usage-guide.md").read_text(encoding="utf-8")
    japanese = (ROOT / "docs/reference/api-usage-guide.ja.md").read_text(encoding="utf-8")
    common = [
        "FormulaTracer", "MathematicalFormula", "ProjectAnalyzer",
        "GenerationPlan", "NativeContext", "NativeFormula", "NativeResult",
        "NativeMathematicalFunction", "ReconstructionResult", "compare_ir",
        "native_available", "plan_generation", "reconstruct",
        "examples/api_reference_usage.py",
    ]
    for symbol in common:
        assert symbol in english
        assert symbol in japanese
    assert "Argument" in english and "Returns" in english and "Failure" in english
    assert "引数" in japanese and "戻り値" in japanese and "失敗" in japanese
    assert english.count("```python") >= 8
    assert japanese.count("```python") >= 8


def test_bilingual_purpose_and_result_guides_match_the_public_api() -> None:
    purpose_en = (ROOT / "docs/reference/api-purpose-guide.md").read_text(encoding="utf-8")
    purpose_ja = (ROOT / "docs/reference/api-purpose-guide.ja.md").read_text(encoding="utf-8")
    result_en = (ROOT / "docs/reference/result-types.md").read_text(encoding="utf-8")
    result_ja = (ROOT / "docs/reference/result-types.ja.md").read_text(encoding="utf-8")
    usage_en = (ROOT / "docs/reference/api-usage-guide.md").read_text(encoding="utf-8")
    usage_ja = (ROOT / "docs/reference/api-usage-guide.ja.md").read_text(encoding="utf-8")

    symbols = [
        "FormulaTracer", "ProjectAuditResult", "MathematicalFormula",
        "GenerationPlan", "CandidateMatch", "ProjectAnalyzer",
        "ReconstructionResult", "NativeContext", "NativeFormula",
        "NativeResult", "NativeMathematicalFunction", "compare_ir",
        "reconstruct", "native_available",
    ]
    for symbol in symbols:
        assert symbol in purpose_en
        assert symbol in purpose_ja
    for guide in (result_en, result_ja):
        assert "FULLY_VERIFIED" in guide
        assert "PROJECT_UNRESOLVED" in guide
        assert "CORRECTLY_UNRESOLVED" in guide
        assert "USER_DECLARED" in guide
        assert "LEAN_KERNEL_VERIFIED" in guide
    assert "api-purpose-guide.md" in usage_en
    assert "api-purpose-guide.ja.md" in usage_ja
    assert "from cpp_audit import theory" in usage_en
    assert "from cpp_audit import theory" in usage_ja


@pytest.mark.skipif(not native_available(), reason="native core not built")
def test_api_reference_runnable_example() -> None:
    runpy.run_path(str(ROOT / "examples/api_reference_usage.py"), run_name="__main__")
