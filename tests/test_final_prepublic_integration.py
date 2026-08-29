from __future__ import annotations

from pathlib import Path
import sys

from formulatracer.native import NativeContext


ROOT = Path(__file__).resolve().parents[1]


def coverage(action: str, **payload):
    with NativeContext() as context:
        return context.execute_kernel({
            "schema_version": "1.0", "kernel": "C",
            "operation": "COVERAGE_BLOCKER", "action": action, **payload,
        })["result"]


def test_user_declaration_is_redundant_evidence_not_verification() -> None:
    result = coverage(
        "USER_DECLARATION",
        declared_ir={"op": "Constant", "value": 1},
        implementation_ir={"op": "Constant", "value": 2},
        metadata={"effects": "PURE", "units": "m"},
    )
    assert result["status"] == "MISMATCH"
    assert result["evidence"] == [{
        "kind": "USER_DECLARED", "proves_implementation": False, "verified": False,
    }]
    assert result["auto_verified"] is False
    assert result["verification_status"] == "UNRESOLVED"


def test_finite_dynamic_information_requires_exhaustiveness() -> None:
    full = coverage(
        "CONTAINER_ACCESS", key_is_static=False, effects_known_pure=True,
        container_kind="DICT", container="p", key={"op": "FreeVariable", "name": "k"},
        possible_keys=["a", "b"], possible_values={"a": 1, "b": 2},
        candidate_set_exhaustive_proven=True,
    )
    assert full["status"] == "FULL_RECONSTRUCTION"
    partial = coverage(
        "FINITE_DISPATCH", receiver="x", candidate_set_exhaustive_proven=False,
        targets=[{"condition": True, "callee_ir": {"op": "Constant", "value": 1},
                  "effects_known_pure": True}],
    )
    assert partial["status"] == "PARTIAL_RECONSTRUCTION"
    assert partial["unresolved"][0]["code"] == "DISPATCH_EXHAUSTIVENESS_UNPROVEN"


def test_user_declared_callback_preserves_value_but_not_unknown_effects() -> None:
    result = coverage(
        "HIGHER_ORDER_CALL", algorithm="CUSTOM_INTEGRATOR",
        callback_ir={"op": "Power", "base": "x", "exponent": 2},
        callback_evidence_kind="USER_DECLARED", callback_effects="UNKNOWN_EFFECT",
        callback_effects_known_pure=False,
    )
    assert result["status"] == "PARTIAL_RECONSTRUCTION"
    assert result["semantic_object"]["callback"]["op"] == "Power"
    assert result["unresolved"][0]["code"] == "USER_DECLARED_EFFECTS_UNVERIFIED"


def test_public_docs_have_first_class_english_and_japanese_boundaries() -> None:
    for path in (ROOT / "README.md", ROOT / "README.ja.md"):
        text = path.read_text(encoding="utf-8")
        assert "User-defined semantics" in text
        assert "Physics foundation" in text
        assert "UNKNOWN_EFFECT" in text


def test_public_api_inventory_never_contains_worktree_absolute_paths() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from public_release_audit import regex_exports

    rows = regex_exports(
        ROOT / "include" / "formulatracer.h", "C",
        r"\b(ft_[A-Za-z0-9_]+)\s*\(", "function",
    )
    assert rows
    assert {row["module"] for row in rows} == {"include/formulatracer.h"}


def test_public_assurance_does_not_probe_private_research_evidence(monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_final_native_assurance import private_runtime_evidence

    monkeypatch.delenv("FORMULATRACER_PRIVATE_RUNTIME_EVIDENCE", raising=False)
    evidence = private_runtime_evidence()
    assert evidence["status"] == "NOT_AVAILABLE_IN_PUBLIC_RELEASE_ENVIRONMENT"
    assert evidence["validation_completed"] is False
    assert evidence["PRODUCTION_PYTHON_SEMANTIC_CALLS"] is None
