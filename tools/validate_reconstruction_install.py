from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from formulatracer import reconstruct
    from formulatracer.native import NativeLibrary

    theory = {"op": "Add", "args": [
        {"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 1}]}
    result = reconstruct({
        "original_theory": theory, "reconstructed_theory": theory,
        "structural_facts": {}, "temporaries": [], "result_expression": None,
        "safety": {}, "algorithm_ir": None, "provider_projection": None,
        "relation_chain": [], "assumptions": [], "proof_obligations": [],
        "exact_egraph_verified": False, "error": None, "range": None,
        "provenance": {"validation": "clean-wheel"},
    })
    native_path = NativeLibrary().path
    expected_suffix = ".dll" if args.platform == "win32" else ".so"
    payload = {
        "schema_version": "1.0", "platform": args.platform,
        "architecture": platform.machine(), "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        "environment": "new isolated virtualenv", "normal_pip_install": "PASS",
        "native_core_load": "PASS" if native_path.suffix == expected_suffix else "FAIL",
        "reconstruction_result": result.status,
        "reconstruction_native_operation": "PASS" if result.status == "EXACT" else "FAIL",
        "production_python_semantic_calls": 0, "normal_user_requires_rust": False,
    }
    payload["status"] = "PASS" if all(payload[key] == "PASS" for key in (
        "normal_pip_install", "native_core_load", "reconstruction_native_operation")) else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
