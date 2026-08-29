"""Join production runtime counters to semantic-owner modules and SCCs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path,
                        default=ROOT / "<PRIVATE_AUDIT_OUTPUT>/runtime-semantic-paths.json")
    parser.add_argument("--graph", type=Path,
                        default=ROOT / "output/native_migration/ownership-graph.json")
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text(encoding="utf-8"))
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    nodes = {item["module"]: item for item in graph["nodes"]}
    production_python = int(runtime.get("paths_by_scope", {}).get("PRODUCTION", {}).get(
        "PYTHON_REFERENCE", runtime.get("PYTHON_REFERENCE_CALLS", 0)))
    total = int(runtime.get("calls_by_scope", {}).get("PRODUCTION",
                                                       runtime.get("TOTAL_SEMANTIC_CALLS", 0)))
    owners = []
    calls_by_scc: Counter[int] = Counter()
    calls_by_kernel: Counter[str] = Counter()
    for owner, calls in runtime.get("calls_by_owner", {}).items():
        module = owner if owner.startswith("cpp_audit.") else None
        node = nodes.get(module or "")
        kernel = node["kernel"] if node else "NATIVE_OR_NON_OWNER"
        scc = node["scc"] if node else None
        calls = int(calls)
        if scc is not None:
            calls_by_scc[scc] += calls
        calls_by_kernel[kernel] += calls
        owners.append({
            "owner": owner,
            "calls": calls,
            "percentage_of_production_calls": (100.0 * calls / total) if total else 0.0,
            "percentage_of_direct_python_calls": (100.0 * calls / production_python)
            if production_python and node else None,
            "kernel": kernel,
            "scc": scc,
            "status": node["classification"] if node else "RUST_NATIVE_OR_NON_SEMANTIC_OWNER",
        })
    owners.sort(key=lambda item: (-item["calls"], item["owner"]))
    operations = [{"operation": name, "calls": int(calls),
                   "percentage_of_production_calls": (100.0 * int(calls) / total) if total else 0.0}
                  for name, calls in runtime.get("calls_by_operation", {}).items()]
    operations.sort(key=lambda item: (-item["calls"], item["operation"]))
    owner_payload = {
        "schema_version": "1.0",
        "measurement_scope": "PRODUCTION",
        "total_production_semantic_calls": total,
        "direct_python_semantic_reference_calls": production_python,
        "owners": owners,
        "operations": operations,
    }
    scc_payload = {
        "schema_version": "1.0",
        "measurement_scope": "PRODUCTION",
        "total_production_semantic_calls": total,
        "sccs": [{"scc": item["scc"], "modules": item["modules"],
                  "kernels": item["kernels"], "calls": calls_by_scc[item["scc"]],
                  "percentage_of_production_calls":
                      (100.0 * calls_by_scc[item["scc"]] / total) if total else 0.0}
                 for item in graph["strongly_connected_components"]],
        "calls_by_kernel_from_owners": dict(sorted(calls_by_kernel.items())),
    }
    write(ROOT / "output/native_migration/runtime-owner-profile.json", owner_payload)
    write(ROOT / "output/native_migration/runtime-scc-profile.json", scc_payload)
    print(json.dumps({"top_owners": owners[:10], "top_operations": operations[:10]},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
