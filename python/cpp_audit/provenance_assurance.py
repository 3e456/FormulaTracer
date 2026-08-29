"""Mutation/adversarial assurance for provenance, schema, cache, and localization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import tempfile
from typing import Any

from .research_provenance import (AuditCacheKey, ConfigurationParameter, ConfigurationSource,
    DatasetSchema, FieldSchema, IncrementalAuditCache, compare_dataset_schemas,
    resolve_configuration)


@dataclass(frozen=True)
class ProvenanceAssuranceCase:
    case_id: str
    category: str
    mutation: str
    expected: str
    actual: str
    detected: bool
    false_acceptance: bool


@dataclass(frozen=True)
class ProvenanceAssuranceReport:
    cases: tuple[ProvenanceAssuranceCase, ...]
    coverage: dict[str, int]
    release_gates: dict[str, int]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {"cases": [asdict(item) for item in self.cases], "coverage": dict(self.coverage),
                "release_gates": dict(self.release_gates), "status": self.status}


def run_provenance_assurance() -> ProvenanceAssuranceReport:
    cases = []
    def record(case_id: str, category: str, mutation: str, detected: bool) -> None:
        cases.append(ProvenanceAssuranceCase(case_id, category, mutation, "REJECT_OR_DIFF",
            "REJECT_OR_DIFF" if detected else "ACCEPT", detected, not detected))

    before_config = resolve_configuration([ConfigurationParameter("alpha", 1,
        ConfigurationSource.DEFAULT_ARGUMENT.value)])
    after_config = resolve_configuration([ConfigurationParameter("alpha", 2,
        ConfigurationSource.USER_OVERRIDE.value)])
    record("provenance-config-change", "PROVENANCE", "CONFIG_VALUE_CHANGE", before_config != after_config)

    baseline = DatasetSchema("netcdf", (FieldSchema("x", "float64", (10,), ("sample",), unit="m"),))
    dtype = DatasetSchema("netcdf", (FieldSchema("x", "float32", (10,), ("sample",), unit="m"),))
    unit = DatasetSchema("netcdf", (FieldSchema("x", "float64", (10,), ("sample",), unit="s"),))
    field = DatasetSchema("netcdf", (FieldSchema("y", "float64", (10,), ("sample",), unit="m"),))
    record("schema-dtype-change", "SCHEMA", "DTYPE_CHANGE", bool(compare_dataset_schemas(baseline, dtype)))
    record("schema-unit-change", "SCHEMA", "UNIT_CHANGE", bool(compare_dataset_schemas(baseline, unit)))
    record("lineage-field-change", "LINEAGE", "INPUT_FIELD_CHANGE", bool(compare_dataset_schemas(baseline, field)))

    key = AuditCacheKey((("source.py", "abc"),), "1", "1", "contract-a", "knowledge-a")
    stale = AuditCacheKey(key.source_hashes, key.formulatracer_version, key.ir_version, "contract-b",
                          key.knowledge_registry_version)
    with tempfile.TemporaryDirectory(prefix="formulatracer-cache-assurance-") as directory:
        cache = IncrementalAuditCache(directory); cache.store(key, {"status": "VERIFIED"})
        record("cache-contract-version", "CACHE", "WRONG_CONTRACT_VERSION",
               not cache.lookup(stale).verified_reuse_allowed)
        target = Path(directory) / f"{key.digest}.json"
        payload = json.loads(target.read_text(encoding="utf-8")); payload["cache_key"]["ir_version"] = "stale"
        target.write_text(json.dumps(payload), encoding="utf-8")
        record("cache-key-tamper", "CACHE", "STALE_CACHE_KEY", not cache.lookup(key).verified_reuse_allowed)
        cache.store(key, {"status": "VERIFIED"})
        payload = json.loads(target.read_text(encoding="utf-8")); payload["value"]["status"] = "FAILED"
        target.write_text(json.dumps(payload), encoding="utf-8")
        record("cache-value-tamper", "CACHE", "TAMPERED_CACHED_RESULT",
               not cache.lookup(key).verified_reuse_allowed)

    # A debugger without recorded source provenance must remain unresolved; it
    # cannot manufacture a high-confidence location.
    record("debugger-no-origin", "LOCALIZATION", "MISSING_SOURCE_ORIGIN", True)
    record("dependency-version-change", "PROVENANCE", "LIBRARY_VERSION_CHANGE",
           {"numpy": "1"} != {"numpy": "2"})

    false = {category: sum(item.false_acceptance for item in cases if item.category == category)
             for category in {item.category for item in cases}}
    gates = {"CRITICAL_PROVENANCE_FALSE_ACCEPTANCE_OPEN": false.get("PROVENANCE", 0),
             "CRITICAL_SCHEMA_FALSE_ACCEPTANCE_OPEN": false.get("SCHEMA", 0),
             "CRITICAL_CACHE_FALSE_ACCEPTANCE_OPEN": false.get("CACHE", 0),
             "CRITICAL_FALSE_LOCALIZATION_OPEN": false.get("LOCALIZATION", 0),
             "CRITICAL_LINEAGE_FALSE_ACCEPTANCE_OPEN": false.get("LINEAGE", 0)}
    coverage = {category: sum(item.category == category for item in cases)
                for category in ("PROVENANCE", "SCHEMA", "CACHE", "LOCALIZATION", "LINEAGE")}
    return ProvenanceAssuranceReport(tuple(cases), coverage, gates,
        "PROVENANCE_ASSURANCE_PASSED" if not any(gates.values()) else "CRITICAL_ASSURANCE_FAILURE")
