"""Source-level fail-closed checks for the built LibTooling frontend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import jsonschema

from cpp_audit.core import load_spec
from cpp_audit.pipeline import normalize_clang_ir, run_frontend


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root, build = Path(args.root).resolve(), Path(args.build_dir).resolve()
    source = root / "tests/negative/frontend_fail_closed.cpp"
    spec = load_spec(root / "examples/weighted_sum/algorithm.yaml")
    schema = json.loads((root / "schemas/implementation-ir.schema.json").read_text(encoding="utf-8"))
    cases = {
        "weighted_sum_unknown_external": "UNRESOLVED_CALL",
        "weighted_sum_wrong_overload": "UNRESOLVED_CALL",
        "weighted_sum_narrowing": "UNKNOWN_IMPLICIT_CAST",
        "weighted_sum_obvious_alias": "FORBIDDEN_ALIAS",
        "weighted_sum_short_bound": "LOOP_BOUND_MISMATCH",
        "weighted_sum_inclusive_bound": "LOOP_CONDITION_MISMATCH",
        "weighted_sum_factor_r": "FACTOR_INDEX_MISMATCH",
        "weighted_sum_transposed": "ROW_MAJOR_INDEX_MISMATCH",
        "weighted_sum_initial_one": "INITIAL_VALUE_MISMATCH",
        "weighted_sum_addition": "TRANSFORM_MISMATCH",
        "weighted_sum_result_i": "OUTPUT_INDEX_MISMATCH",
        "weighted_sum_store_inside": "STORE_POSITION_MISMATCH",
        "weighted_sum_reduce": "REDUCTION_ORDER_MISMATCH",
        "weighted_sum_invalid_end": "ITERATOR_RANGE_MISMATCH",
    }
    for function, expected in cases.items():
        output = build / f"{function}.ir.json"
        ir = run_frontend(args.frontend, build, source, function, output)
        jsonschema.validate(ir, schema)
        result = normalize_clang_ir(ir, spec, root / "registry/std")
        codes = {item["code"] for item in result.diagnostics}
        if result.status != "FAILED" or expected not in codes or result.canonical_graph is not None:
            raise AssertionError((function, expected, sorted(codes), result.status))
        print(f"{function}: {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
