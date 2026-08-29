from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from cpp_audit import AuditError, load_spec


ROOT = Path(__file__).resolve().parents[1]


def test_stable_python_symbols_remain_importable() -> None:
    policy = json.loads((ROOT / "maintenance/api-policy.json").read_text(encoding="utf-8"))
    module = importlib.import_module("formulatracer")
    assert all(hasattr(module, name) for name in policy["python"]["stable"])


def test_unsupported_algorithm_schema_version_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({
        "schema_version": "999.0", "algorithm_id": "weighted_sum",
        "algorithm_version": "1", "inputs": {}, "outputs": {}, "steps": {},
        "numeric_model": "AbstractReal",
    }), encoding="utf-8")
    with pytest.raises(AuditError, match="unsupported schema_version"):
        load_spec(path)


def test_c_abi_v1_and_schema_policies_are_explicit() -> None:
    header = (ROOT / "include/formulatracer.h").read_text(encoding="utf-8")
    assert "#define FT_ABI_VERSION 1u" in header
    schema_policy = json.loads((ROOT / "maintenance/schema-policy.json").read_text(encoding="utf-8"))
    assert schema_policy["rules"]["unsupported_future_versions"] == "FAIL_CLOSED"
    assert schema_policy["rules"]["silent_downgrade"] is False
