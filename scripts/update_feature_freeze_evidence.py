from __future__ import annotations

from datetime import date
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "output/feature_freeze/native-migration-current.json"


def main() -> int:
    baseline = json.loads((ROOT / "output/native_migration/migration-status.json").read_text(encoding="utf-8"))
    components = []
    for component in baseline["components"]:
        current = dict(component)
        if current["component"] == "audit_bundle":
            current.update({
                "rust_status": "NATIVE_INTEGRITY_PROTECTED_CANDIDATE",
                "semantic_match": False,
                "python_retired": False,
                "note": "Native object/C ABI/Python facade implemented; legacy Python bundle differential and retirement remain open.",
            })
        elif current["component"] == "tex_parser":
            current.update({
                "rust_status": "EXPANDED_FAIL_CLOSED_CANDIDATE",
                "semantic_match": False,
                "python_retired": False,
                "accepted_roles": [
                    "arithmetic", "fraction", "unambiguous_power", "function_application",
                    "finite_sum", "infinite_series", "finite_product", "infinite_product",
                    "definite_integral", "limit", "ordinary_derivative",
                ],
                "note": "Piecewise and declaration-driven standalone indexed notation remain open; ambiguity is rejected.",
            })
        components.append(current)
    inventory = json.loads((ROOT / "output/feature_freeze/python-semantic-inventory.json").read_text(encoding="utf-8"))
    taxonomy = json.loads((ROOT / "output/feature_freeze/reconstruction-root-causes.json").read_text(encoding="utf-8"))
    blockers = [
        f"{inventory['summary'].get('TO_BE_RETIRED', 0)} Python modules still require native differential and retirement",
        "fact/constraint, exact e-graph, relation, unification, pack, error/range, provenance/cache/debugger parity gates remain open",
        "native TeX piecewise and declaration-driven indexed notation are incomplete",
        f"external Formula-to-Code-to-Formula reconstruction remains unresolved for {taxonomy['unresolved_count']} sealed outcomes",
        "native AuditBundle has no legacy Python bundle differential gate yet",
    ]
    payload = {
        "schema_version": "1.0",
        "generated": str(date.today()),
        "baseline_sha": baseline["baseline_sha"],
        "status": "FEATURE_FREEZE_BLOCKED",
        "feature_freeze_ready": False,
        "critical_false_acceptance_open": 0,
        "completed_in_this_pass": [
            "semantic-noise invariance regression",
            "semantic-string no-execution fail-closed boundary",
            "explicit custom operator overload fail-closed boundary",
            "native TeX structural binder expansion",
            "native integrity-protected AuditBundle candidate and C ABI projection",
            "complete Python module/symbol retirement inventory",
            "sealed 20-case reconstruction root-cause taxonomy",
        ],
        "components": components,
        "blockers": blockers,
        "gate_policy": "No migration, retirement, reconstruction, or RC gate is promoted without measured differential evidence.",
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
