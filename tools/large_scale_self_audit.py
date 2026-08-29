from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from cpp_audit.self_audit import DEFAULT_SEED, run_large_scale_self_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic multi-library FormulaTracer self-audit")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    payloads = run_large_scale_self_audit(args.root, output_dir=args.output, seed=args.seed)
    print(json.dumps(payloads["summary.json"], indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if payloads["summary.json"]["release_criterion"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
