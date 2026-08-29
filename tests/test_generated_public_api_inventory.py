from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from cpp_audit.library_contracts import LibraryContractRegistry
from cpp_audit.reference_harvester import ContractKind


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "registry" / "generated" / "public_api"


def reports() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in GENERATED.glob("*-*.json")]


def test_all_target_libraries_and_exact_inventory_total() -> None:
    summary = json.loads((GENERATED / "coverage_summary.json").read_text(encoding="utf-8"))
    assert summary["library_count"] == 12
    assert summary["coverage"]["TOTAL_PUBLIC_API"] == 14864


def test_every_report_validates_against_public_inventory_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "public-api-inventory.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for report in reports():
        validator.validate(report)


def test_inventory_counts_and_closed_contract_kinds() -> None:
    allowed = {kind.value for kind in ContractKind}
    for report in reports():
        assert len(report["inventory"]) == report["coverage"]["TOTAL_PUBLIC_API"]
        assert all(item["contract_kind"] in allowed for item in report["inventory"])


def test_harvest_candidates_never_expand_verified_registry() -> None:
    registry = LibraryContractRegistry.default()
    assert len(registry.registered_callables()) == 396
    summary = json.loads((GENERATED / "coverage_summary.json").read_text(encoding="utf-8"))
    assert summary["research_observed_baseline"]["registered_api_count"] == 393
    assert summary["coverage"]["RESEARCH_OBSERVED_API_COVERAGE"] == 1.0


def test_dask_execution_and_netcdf_value_metadata_are_preserved() -> None:
    dask = json.loads((GENERATED / "dask-2026.3.0.json").read_text(encoding="utf-8"))
    parallel = [item for item in dask["inventory"] if item["contract_kind"] == "PARALLEL_EXECUTION"]
    assert parallel and all(item["execution_ir"].get("lazy") is True for item in parallel)
    netcdf = json.loads((GENERATED / "netCDF4-1.7.4.json").read_text(encoding="utf-8"))
    io_items = [item for item in netcdf["inventory"] if item["contract_kind"] == "IO_BOUNDARY"]
    assert any("scale_factor" in item["execution_ir"].get("preserve", []) for item in io_items)


def test_provenance_hashes_raw_and_parsed_content() -> None:
    for report in reports():
        assert len(report["provenance"]["content_sha256"]) == 64
        assert len(report["provenance"]["parsed_inventory_sha256"]) == 64


class GeneratedPublicApiInventoryTests(unittest.TestCase):
    test_all_target_libraries_and_exact_inventory_total = staticmethod(test_all_target_libraries_and_exact_inventory_total)
    test_every_report_validates_against_public_inventory_schema = staticmethod(test_every_report_validates_against_public_inventory_schema)
    test_inventory_counts_and_closed_contract_kinds = staticmethod(test_inventory_counts_and_closed_contract_kinds)
    test_harvest_candidates_never_expand_verified_registry = staticmethod(test_harvest_candidates_never_expand_verified_registry)
    test_dask_execution_and_netcdf_value_metadata_are_preserved = staticmethod(test_dask_execution_and_netcdf_value_metadata_are_preserved)
    test_provenance_hashes_raw_and_parsed_content = staticmethod(test_provenance_hashes_raw_and_parsed_content)
