from __future__ import annotations

import json
import tempfile
import unittest
import zlib
from pathlib import Path

import pytest

from cpp_audit.library_contracts import LibraryContractRegistry, integrate_reference_harvest
from cpp_audit.reference_harvester import (
    ContractKind, HarvestError, InventoryEntry, LibrarySpec, classify_contract,
    harvest_library, is_public, parse_sphinx_inventory, run, version_matches,
)


def inventory(*lines: str, version: str = "1.2.3") -> bytes:
    header = ("# Sphinx inventory version 2\n# Project: Demo\n"
              f"# Version: {version}\n"
              "# The remainder of this file is compressed using zlib.\n").encode()
    return header + zlib.compress(("\n".join(lines) + "\n").encode())


def spec() -> LibrarySpec:
    return LibrarySpec("demo", "1.2.3", "https://example.test/1.2/",
                       "https://example.test/objects.inv", ("demo",), "demo")


def test_version_pin_and_stable_difference() -> None:
    assert version_matches("1.2.3", "1.2.3", "exact")
    assert not version_matches("1.2.3", "1.2.4", "exact")
    with pytest.raises(HarvestError):
        harvest_library(spec(), inventory("demo.sum py:function 1 api.html#sum -", version="2.0"))


def test_private_property_alias_and_provenance() -> None:
    result = harvest_library(spec(), inventory(
        "demo._secret py:function 1 api.html#secret -",
        "demo.sum py:function 1 api.html#sum -",
        "demo.Array.sum py:method 1 api.html#sum -",
        "demo.Array.shape py:attribute 1 api.html#shape -"), {"etag": "abc"})
    assert result["coverage"]["PRIVATE_EXCLUDED"] == 1
    assert result["coverage"]["ALIAS_COUNT"] == 1
    assert any(item["object_kind"] == "property_or_attribute" for item in result["inventory"])
    assert result["provenance"]["http_etag"] == "abc"
    assert len(result["provenance"]["content_sha256"]) == 64


def test_publicness_and_dollar_uri() -> None:
    public, reason = is_public(InventoryEntry("other.sum", "py:function", 1, "x", "-"), spec())
    assert not public and reason == "outside_package_public_namespace"
    assert parse_sphinx_inventory(inventory("demo.sum py:function 1 api.html#$ -")).entries[0].uri.endswith("demo.sum")


def test_family_and_dask_execution_overlay() -> None:
    contract, family, _, _ = classify_contract("scipy.optimize.minimize", "function", "scipy")
    assert contract == ContractKind.ALGORITHM_INVOCATION and family == "OptimizationInvocation"
    contract, family, _, overlay = classify_contract("dask.array.sum", "function", "dask")
    assert contract == ContractKind.PARALLEL_EXECUTION and family == "Reduction"
    assert overlay["lazy"] and "split_every" in overlay["preserve_parameters"]


def test_random_contract_does_not_claim_sequence_identity() -> None:
    contract, _, _, overlay = classify_contract("numpy.random.normal", "function", "numpy")
    assert contract == ContractKind.DISTRIBUTION
    assert overlay["sequence_identity"] == "SEQUENCE_IDENTICAL_NOT_CLAIMED"


def test_registry_precedence_does_not_promote_candidates() -> None:
    registry = LibraryContractRegistry.default()
    before = len(registry.registered_callables())
    report = harvest_library(spec(), inventory("demo.sum py:function 1 api.html#sum -"))
    integrated = integrate_reference_harvest(report, registry)
    assert integrated["inventory"][0]["registry_resolution"]["status"] == "NEEDS_REVIEW"
    assert len(registry.registered_callables()) == before


def test_unknown_reference_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        specs = root / "specs.json"
        specs.write_text(json.dumps({"libraries": [{"package": "missing", "package_version": "1.0",
            "documentation_root": "https://invalid/", "inventory_url": "https://invalid/objects.inv",
            "public_prefixes": ["missing"], "runtime_module": "missing"}]}), encoding="utf-8")
        with pytest.raises(HarvestError):
            run(specs, root / "out", root / "cache", None, True, False)


class ReferenceHarvesterTests(unittest.TestCase):
    test_version_pin_and_stable_difference = staticmethod(test_version_pin_and_stable_difference)
    test_private_property_alias_and_provenance = staticmethod(test_private_property_alias_and_provenance)
    test_publicness_and_dollar_uri = staticmethod(test_publicness_and_dollar_uri)
    test_family_and_dask_execution_overlay = staticmethod(test_family_and_dask_execution_overlay)
    test_random_contract_does_not_claim_sequence_identity = staticmethod(test_random_contract_does_not_claim_sequence_identity)
    test_registry_precedence_does_not_promote_candidates = staticmethod(test_registry_precedence_does_not_promote_candidates)
    test_unknown_reference_fails_closed = staticmethod(test_unknown_reference_fails_closed)
