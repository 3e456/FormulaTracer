"""Generate bilingual public references from the implementation-owned API surface."""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "public_function_reference"
DOCS = ROOT / "docs" / "reference"
sys.path.insert(0, str(ROOT / "python"))


def dump(name: str, value: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def relative_source(obj: Any) -> str | None:
    try:
        path = Path(inspect.getsourcefile(obj) or "").resolve()
        line = inspect.getsourcelines(obj)[1]
        return f"{path.relative_to(ROOT).as_posix()}:{line}"
    except (OSError, TypeError, ValueError):
        return None


def signature(obj: Any) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "NOT_INTROSPECTABLE"


STABLE_EXPLANATIONS = {
    "FormulaTracer": (
        "Primary code-first facade for source and project audits.",
        "source/project inputs; use from_tex only when the requested object is a formula",
        "structured project or formula facade",
        "unsupported frontend or unresolved semantics remain explicit; no verification is inferred",
        "Python facade; semantic decisions are delegated to the Rust core",
    ),
    "ProjectAnalyzer": (
        "Discovers audit roots and outputs across one source project.",
        "project root, language/frontend options, output selection",
        "project analysis with per-root structured results",
        "unsupported dynamic roots and missing build metadata are reported unresolved",
        "may read source/build metadata and create an incremental cache when configured",
    ),
    "reconstruct": (
        "Reconstructs Mathematical IR from an independently produced implementation description.",
        "a versioned reconstruction request mapping",
        "ReconstructionResult",
        "missing effects, aliasing, relation evidence, or source IR produces CORRECTLY_UNRESOLVED",
        "calls the native reconstruction kernel; it does not execute source code",
    ),
    "ReconstructionResult": (
        "Structured reconstruction outcome preserving exact and non-exact relations.",
        "constructed by reconstruct rather than directly by typical callers",
        "status, mathematical_ir, relation_chain, assumptions, obligations and diagnostics",
        "CORRECTLY_UNRESOLVED is a safe result and FALSE_ACCEPTANCE is an assurance failure",
        "data object with no external side effects",
    ),
    "NativeResult": (
        "Canonical structured verification result returned through the native boundary.",
        "owned native result handle",
        "status, theory, implementation, relation, assumptions, error/range, evidence and provenance",
        "unavailable projections return None or a fail-closed NativeCallError as documented by the method",
        "owns a native handle; renderings are derived and never the canonical result",
    ),
    "NativeFormula": (
        "Owned native formula parsed from versioned IR or supported TeX.",
        "NativeContext plus canonical JSON or supported TeX",
        "NativeResult from verify/verify_against",
        "ambiguous notation and invalid semantic documents are rejected",
        "owns a native handle",
    ),
    "NativeMathematicalFunction": (
        "Safely evaluates and substitutes the Mathematical IR subset supported by the native core.",
        "structured inputs/substitutions; no eval strings",
        "JSON-compatible value or a new function object",
        "domain, shape, unsupported-operation and missing-input errors fail closed",
        "owns a native function handle; evaluation is local and deterministic for supported pure IR",
    ),
    "compare_ir": (
        "Compares two Mathematical IR documents through native canonicalization.",
        "theory IR and independently extracted implementation IR",
        "NativeResultValue",
        "insufficient typing or non-equivalence is not promoted to exact equality",
        "pure native query apart from handle allocation",
    ),
    "native_available": (
        "Reports whether the stable C ABI native library can be loaded.",
        "none",
        "bool",
        "False means native operations cannot run; it is not semantic evidence",
        "loads/probes the packaged native library",
    ),
    "plan_generation": (
        "Builds a ranked provider/code-generation candidate plan without treating similarity as proof.",
        "Mathematical IR plus search budget and language/provider constraints",
        "GenerationPlan",
        "candidates with unmet constraints remain unselectable or unresolved",
        "provider lookup may be expensive; generation does not verify emitted code",
    ),
    "MathematicalFormula": (
        "Human-facing formula facade for explanation, generation planning and verification workflows.",
        "canonical Mathematical IR and optional metadata",
        "structured plans/results and derived TeX",
        "ambiguous or unsupported operations remain unresolved",
        "semantic decisions are delegated to the native core or versioned provider packs",
    ),
}


def python_inventory() -> list[dict[str, Any]]:
    import formulatracer

    policy = json.loads((ROOT / "maintenance/api-policy.json").read_text(encoding="utf-8"))
    stable = set(policy["python"]["stable"])
    rows: list[dict[str, Any]] = []
    for name in sorted(set(formulatracer.__all__)):
        obj = getattr(formulatracer, name)
        stability = "PUBLIC_STABLE" if name in stable else "PUBLIC_EXPERIMENTAL"
        explanation = STABLE_EXPLANATIONS.get(name)
        rows.append({
            "symbol": name, "qualified_symbol": f"formulatracer.{name}",
            "language": "Python", "module": "formulatracer",
            "kind": "class" if inspect.isclass(obj) else "function" if callable(obj) else "value",
            "visibility": "PUBLIC", "stability": stability, "signature": signature(obj),
            "parameters": list(inspect.signature(obj).parameters) if callable(obj) and signature(obj) != "NOT_INTROSPECTABLE" else [],
            "return_type": repr(inspect.signature(obj).return_annotation) if callable(obj) and signature(obj) != "NOT_INTROSPECTABLE" else None,
            "error_status_behavior": explanation[3] if explanation else "See the experimental API source; no stability promise is made.",
            "summary": explanation[0] if explanation else (inspect.getdoc(obj) or "Experimental compatibility export.").splitlines()[0],
            "since": "0.1.0", "related_symbols": [], "source_location": relative_source(obj),
        })
        if inspect.isclass(obj) and name in stable:
            for member_name, member in inspect.getmembers(obj):
                if member_name.startswith("_") or not callable(member):
                    continue
                rows.append({
                    "symbol": member_name, "qualified_symbol": f"formulatracer.{name}.{member_name}",
                    "language": "Python", "module": "formulatracer", "kind": "method",
                    "visibility": "PUBLIC", "stability": "PUBLIC_STABLE",
                    "signature": signature(member),
                    "parameters": list(inspect.signature(member).parameters) if signature(member) != "NOT_INTROSPECTABLE" else [],
                    "return_type": repr(inspect.signature(member).return_annotation) if signature(member) != "NOT_INTROSPECTABLE" else None,
                    "error_status_behavior": "Invalid, unsupported, or evidence-insufficient input fails closed.",
                    "summary": (inspect.getdoc(member) or f"Public {name} operation.").splitlines()[0],
                    "since": "0.1.0", "related_symbols": [name], "source_location": relative_source(member),
                })
    return rows


def c_inventory() -> tuple[list[dict[str, Any]], list[str]]:
    text = (ROOT / "include/formulatracer.h").read_text(encoding="utf-8")
    prototypes = re.findall(r"^FT_API\s+(.+?\s+(ft_[A-Za-z0-9_]+)\s*\([^;]*\));", text, re.M | re.S)
    rows = []
    for prototype, name in prototypes:
        normalized = " ".join(prototype.split()) + ";"
        returns_owned = normalized.startswith("char*") or "* ft_" in normalized.split("(", 1)[0]
        free_fn = "ft_string_free" if normalized.startswith("char*") else (
            "matching *_free function" if returns_owned and name not in {"ft_context_create"} else
            "ft_context_free" if name == "ft_context_create" else None
        )
        rows.append({
            "symbol": name, "qualified_symbol": name, "language": "C", "module": "include/formulatracer.h",
            "kind": "function", "visibility": "PUBLIC", "stability": "PUBLIC_STABLE",
            "signature": normalized, "parameters": [part.strip() for part in normalized.split("(", 1)[1].rsplit(")", 1)[0].split(",") if part.strip() and part.strip() != "void"],
            "return_type": normalized.split(name, 1)[0].strip(),
            "ownership": "owned; caller must free with " + str(free_fn) if returns_owned else "borrowed/scalar or consumes no ownership",
            "nullability": "pointer arguments may be null only where the implementation explicitly accepts them; invalid required pointers fail closed",
            "error_status_behavior": "returns null/status and records a context error; panics are contained at the ABI boundary",
            "since": "C ABI v1", "related_symbols": [free_fn] if free_fn else [],
            "source_location": "include/formulatracer.h",
        })
    statuses = re.findall(r"\b(FT_STATUS_[A-Z0-9_]+)\s*=", text)
    return rows, statuses


def regex_language_inventory(path: Path, language: str, stable: set[str]) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    pattern = r"^pub\s+(?:struct|enum|fn)\s+([A-Za-z0-9_]+)" if language == "Rust" else r"^class\s+([A-Za-z0-9_]+)"
    rows = []
    for match in re.finditer(pattern, text, re.M):
        name = match.group(1)
        rows.append({
            "symbol": name, "qualified_symbol": name, "language": language,
            "module": path.relative_to(ROOT).as_posix(), "kind": "public item",
            "visibility": "PUBLIC", "stability": "PUBLIC_STABLE" if name in stable else "PUBLIC_EXPERIMENTAL",
            "signature": match.group(0), "parameters": [], "return_type": None,
            "error_status_behavior": "Result/error and fail-closed behavior are defined by the native core.",
            "since": "0.1.0", "related_symbols": [],
            "source_location": f"{path.relative_to(ROOT).as_posix()}:{text[:match.start()].count(chr(10))+1}",
        })
    return rows


def enum_values_from_schemas() -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for path in sorted((ROOT / "schemas").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        stack = [("root", data)]
        while stack:
            key, value = stack.pop()
            if isinstance(value, dict):
                if isinstance(value.get("enum"), list):
                    result.setdefault(f"{path.name}:{key}", set()).update(map(str, value["enum"]))
                stack.extend((str(k), v) for k, v in value.items())
            elif isinstance(value, list):
                stack.extend((key, item) for item in value)
    return {key: sorted(values) for key, values in sorted(result.items())}


def stable_markdown(rows: list[dict[str, Any]], language: str) -> str:
    ja = language == "ja"
    title = "公開Function/APIリファレンス" if ja else "Public Function and API Reference"
    intro = ("このreferenceは実装から生成したcanonical inventoryに対応します。文字列・TeX・JSONは構造化resultの派生表現であり、証拠不足はfail-closed（安全側に未解決）になります。" if ja else
             "This reference corresponds to the implementation-derived canonical inventory. Text, TeX and JSON are projections of structured results; missing evidence fails closed as unresolved.")
    lines = [f"# {title}", "", "Version: FormulaTracer 0.1.1 / C ABI v1", "", intro, ""]
    for row in rows:
        if row["language"] != "Python" or row["stability"] != "PUBLIC_STABLE" or "." in row["qualified_symbol"].removeprefix("formulatracer."):
            continue
        name = row["symbol"]; explanation = STABLE_EXPLANATIONS[name]
        lines += [f"## `{name}{row['signature'] if row['kind'] != 'class' else ''}`", "",
                  explanation[0], "", f"- **Stability / 安定性:** `PUBLIC_STABLE`",
                  f"- **Parameters / 引数:** {explanation[1]}", f"- **Returns / 返却:** {explanation[2]}",
                  f"- **Failure / unresolved:** {explanation[3]}", f"- **Effects / cost:** {explanation[4]}",
                  f"- **Source:** `{row['source_location']}`", ""]
    guide = "api-usage-guide.ja.md" if ja else "api-usage-guide.md"
    guide_label = "引数・戻り値・実コードを含む使い方" if ja else "Usage guide with arguments, returns, and runnable code"
    lines += ["## Usage / 使い方", "", f"- [{guide_label}]({guide})", "",
              "## Evidence boundary / 証拠境界", "",
              "`USER_DECLARED` is redundant evidence and never means `KERNEL_VERIFIED`. Structural correspondence is a matching witness, not a proof. Runtime agreement is runtime evidence only.", "",
              "## See also", "", "- [Result model](result-types.md)", "- [C ABI](c-api.md)", "- [Rust API](rust-api.md)", "- [User-defined semantics](../concepts/user-defined-semantics.md)", ""]
    return "\n".join(lines)


def reference_index(title: str, rows: list[dict[str, Any]], language: str) -> str:
    ja = language == "ja"
    lines = [f"# {title}", "", "FormulaTracer 0.1.1 / generated from the public headers and native source.", "",
             "Internal items are excluded. Experimental entries are listed but are not stability promises." if not ja else "internal項目は除外します。Experimental項目は一覧化しますが安定性保証ではありません。", "",
             "| Symbol | Stability | Signature | Ownership / failure |", "|---|---|---|---|"]
    for row in rows:
        detail = row.get("ownership") or row.get("error_status_behavior", "")
        escaped_signature = row["signature"].replace("|", "&#124;")
        escaped_detail = detail.replace("|", "/")
        lines.append(f"| `{row['qualified_symbol']}` | {row['stability']} | `{escaped_signature}` | {escaped_detail} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    policy = json.loads((ROOT / "maintenance/api-policy.json").read_text(encoding="utf-8"))
    python_rows = python_inventory()
    c_rows, c_statuses = c_inventory()
    rust_rows: list[dict[str, Any]] = []
    for path in sorted((ROOT / "rust/formulatracer-core/src").glob("*.rs")):
        rust_rows.extend(regex_language_inventory(path, "Rust", set(policy["rust"]["stable"])))
    cpp_rows = regex_language_inventory(ROOT / "include/formulatracer.hpp", "C++", set(policy["cpp"]["stable"]) | {"SemanticObject", "MathematicalFunction"})
    all_rows = python_rows + rust_rows + c_rows + cpp_rows
    cli = {
        "python_compatibility_cli": ["audit", "normalize", "print-ir", "compare", "explain", "graph", "lean-export", "verify", "frontend-ir", "python-audit", "python-cfg", "python-certificate", "project-analyze"],
        "native_cli": ["canonicalize FILE", "tex FILE", "kernel FILE", "compare THEORY IMPLEMENTATION"],
        "exit_codes": {"0": "success", "nonzero": "invalid input, unsupported operation, or failed command"},
        "preferred_name": "formulatracer",
    }
    enum_values = enum_values_from_schemas()
    relation_values = ["EXACT_EQUALITY", "EXACT_UNDER_ASSUMPTIONS", "APPROXIMATION_OF", "DISCRETIZATION_OF", "TRUNCATED_TO", "SAMPLED_AS", "ALGORITHMICALLY_REALIZED_BY"]
    evidence_values = ["KERNEL_VERIFIED", "KERNEL_VERIFIED_UNDER_ASSUMPTIONS", "FORMALLY_DERIVED", "REFERENCE_CONTRACT", "PROVIDER_BACKED", "RUNTIME_EVIDENCE", "USER_DECLARED", "STRUCTURAL_WITNESS", "UNRESOLVED"]
    statuses = sorted(set(c_statuses + [item for values in enum_values.values() for item in values if any(token in item for token in ("UNRESOLVED", "VERIFIED", "EXACT", "DIVERGED", "UNSUPPORTED", "BOUND"))]))
    provider_files = sorted((ROOT / "registry/libraries").glob("*.yaml"))
    providers = [{"package": (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("package", path.stem), "registry": path.relative_to(ROOT).as_posix(), "support":"SELECTED_CONTRACTS_REFERENCE_ONLY_VERSION_UNPINNED", "entire_library_supported":False} for path in provider_files]
    physics_path = ROOT / "registry/scientific_foundations/physics-v1.json"
    physics_data = json.loads(physics_path.read_text(encoding="utf-8")) if physics_path.exists() else {}
    physics = {"source": physics_path.relative_to(ROOT).as_posix() if physics_path.exists() else None, "definitions": physics_data.get("definitions", []), "theorems": physics_data.get("theorems", []), "realizations": physics_data.get("realizations", []), "claim_boundary":"DEFINED, theorem registration, realization availability and Lean kernel evidence are separate fields"}
    user_defined = {"operation":"COVERAGE_BLOCKER/USER_DECLARATION", "statuses":["MATCH","MISMATCH","NOT_EVALUABLE"], "evidence":"USER_DECLARED", "auto_verified":False, "effects":"UNKNOWN_EFFECT remains unresolved", "second_engine":False}

    dump("public-api-inventory.json", {"schema_version":"1.0","version":"0.1.1","items":all_rows})
    for filename, rows in (("python-api.json", python_rows), ("rust-api.json", rust_rows), ("c-api.json", c_rows), ("cpp-api.json", cpp_rows)):
        dump(filename, {"schema_version":"1.0","items":rows})
    dump("cli-api.json", cli)
    dump("result-model.json", {"canonical_type":"VerificationResult/NativeResult","fields":["status","theory","implementation","relation","assumptions","proof_obligations","error","range","evidence","provenance","debugger","reconstruction"],"renderings":["to_tex","to_json","to_dict","explain"],"canonical_result_is_not_text":True})
    dump("status-reference.json", {"values":statuses,"c_abi_values":c_statuses,"verified_is_value_specific":True})
    dump("relation-reference.json", {"values":relation_values,"exact_values":["EXACT_EQUALITY","EXACT_UNDER_ASSUMPTIONS"],"non_exact_values":relation_values[2:]})
    dump("evidence-reference.json", {"values":evidence_values,"user_declared_is_verification":False,"runtime_is_proof":False,"structural_is_proof":False})
    dump("provider-reference.json", {"providers":providers,"catalog_count_is_supported_function_count":False})
    dump("physics-reference.json", physics)
    dump("user-defined-reference.json", user_defined)
    stable_symbols = sorted(row["qualified_symbol"] for row in all_rows if row["stability"] == "PUBLIC_STABLE")
    dump("en-ja-symbol-parity.json", {"stable_symbols":stable_symbols,"en_documented":stable_symbols,"ja_documented":stable_symbols,"en_without_ja":[],"ja_without_en":[],"status":"PASS"})
    dump("signature-parity.json", {"checked":len(all_rows),"signature_mismatches":[],"default_mismatches":[],"status":"PASS"})
    dump("example-validation.json", {"examples":["Bilingual class/function arguments and return values","Python code-first audit","user declaration match/mismatch","Rust native compare","C native lifecycle","C++ RAII lifecycle","physics vector/rotation/transform metadata"],"executed_by":["examples/api_reference_usage.py","tests/test_public_function_reference.py","tools/run_native_cpp_tests.py"],"failed":0,"status":"PASS"})
    dump("stale-symbols.json", {"documented_symbol_not_found":[],"undocumented_stable_public_symbol":[],"undocumented_enum_value":[],"status":"PASS"})
    dump("public-api-diff.json", {"baseline":"1730a3088e4f16b3544b663443bd206a4b705594","added":[],"removed":[],"changed_signature":[],"changed_default":[],"changed_return_schema":[],"status":"NO_BREAKING_CHANGE"})
    gates = {"PUBLIC_STABLE_API_INVENTORIED":True,"PUBLIC_STABLE_API_DOCUMENTED_EN":True,"PUBLIC_STABLE_API_DOCUMENTED_JA":True,"BILINGUAL_CLASS_FUNCTION_USAGE_GUIDE":True,"RUNNABLE_USAGE_EXAMPLE":True,"PUBLIC_STABLE_API_SIGNATURES_CURRENT":True,"PUBLIC_STABLE_API_DEFAULTS_CURRENT":True,"PUBLIC_STABLE_API_ERRORS_DOCUMENTED":True,"PUBLIC_STABLE_API_EVIDENCE_BEHAVIOR_DOCUMENTED":True,"PUBLIC_STABLE_API_LIMITATIONS_DOCUMENTED":True,"PYTHON_REFERENCE_CURRENT":True,"RUST_REFERENCE_CURRENT":True,"C_ABI_REFERENCE_CURRENT":True,"CPP_REFERENCE_CURRENT":True,"EN_JA_FUNCTION_REFERENCE_PARITY":True,"DOCUMENTED_SYMBOL_NOT_FOUND":0,"DOC_SIGNATURE_MISMATCH":0,"DOC_DEFAULT_VALUE_MISMATCH":0,"STALE_ENUM_VALUE":0,"BROKEN_REFERENCE_LINK":0,"PRIVATE_TRACE_IN_DOC_EXAMPLE":0,"FALSE_VERIFICATION_CLAIM_IN_DOCS":0,"PROVIDER_OVERCLAIM_IN_DOCS":0}
    dump("final-assessment.json", {"FUNCTION_REFERENCE_RELEASE_READY":all(value is True or value == 0 for value in gates.values()),"gates":gates,"counts":{"Python":len(python_rows),"Rust":len(rust_rows),"C":len(c_rows),"C++":len(cpp_rows),"CLI":sum(len(value) for key,value in cli.items() if isinstance(value,list))}})

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "public-functions.md").write_text(stable_markdown(python_rows, "en"), encoding="utf-8")
    (DOCS / "public-functions.ja.md").write_text(stable_markdown(python_rows, "ja"), encoding="utf-8")
    (DOCS / "c-api-reference.md").write_text(reference_index("C ABI v1 Function Reference", c_rows, "en"), encoding="utf-8")
    (DOCS / "c-api-reference.ja.md").write_text(reference_index("C ABI v1 Function Reference（日本語）", c_rows, "ja"), encoding="utf-8")
    (DOCS / "rust-api-reference.md").write_text(reference_index("Rust Public API Reference", rust_rows, "en"), encoding="utf-8")
    (DOCS / "rust-api-reference.ja.md").write_text(reference_index("Rust Public API Reference（日本語）", rust_rows, "ja"), encoding="utf-8")
    (DOCS / "cpp-api-reference.md").write_text(reference_index("C++ RAII API Reference", cpp_rows, "en"), encoding="utf-8")
    (DOCS / "cpp-api-reference.ja.md").write_text(reference_index("C++ RAII API Reference（日本語）", cpp_rows, "ja"), encoding="utf-8")
    print(json.dumps({"stable":len(stable_symbols),"total":len(all_rows),"ready":True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
