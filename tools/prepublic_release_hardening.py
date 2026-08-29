"""Generate lightweight SBOM and fail-closed semantic-claim assurance."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "prepublic_semantic_upgrade"


def sha_text(path: Path) -> str:
    """Hash locked text inputs independently of checkout line endings."""
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cargo_packages():
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    return [{"SPDXID":f"SPDXRef-Cargo-{item['name']}-{item['version']}",
             "name":item["name"], "versionInfo":item["version"],
             "downloadLocation":"NOASSERTION", "licenseConcluded":"NOASSERTION",
             "supplier":"NOASSERTION", "externalRefs":[{"referenceCategory":"PACKAGE-MANAGER",
                 "referenceType":"purl", "referenceLocator":f"pkg:cargo/{item['name']}@{item['version']}"}]}
            for item in lock["package"]]


def python_packages():
    result = []
    for line in (ROOT / "requirements" / "ci.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        name, version = line.split("==", 1)
        result.append({"SPDXID":f"SPDXRef-PyPI-{name}-{version}", "name":name,
                       "versionInfo":version, "downloadLocation":"NOASSERTION",
                       "licenseConcluded":"NOASSERTION", "supplier":"NOASSERTION",
                       "externalRefs":[{"referenceCategory":"PACKAGE-MANAGER",
                           "referenceType":"purl", "referenceLocator":f"pkg:pypi/{name}@{version}"}]})
    return result


def claims_gate():
    failures = []
    provider = (ROOT / "rust" / "formulatracer-core" / "src" / "provider_execution.rs").read_text(encoding="utf-8")
    forbidden = "DASK_" + "GUARANTEED_ERROR_BOUND"
    if forbidden in provider: failures.append("derived bound mislabeled as upstream Dask guarantee")
    inventory = json.loads((OUT / "dask-reference-guarantee-inventory.json").read_text(encoding="utf-8"))
    if not inventory.get("prohibited_claims"): failures.append("Dask claim boundary missing")
    final = json.loads((OUT / "final-coverage.json").read_text(encoding="utf-8"))
    for record in final["records"]:
        semantic = (record.get("result") or {}).get("result", {})
        if semantic.get("exact_promotion") is True:
            failures.append(f"unexpected exact promotion: {record['case_id']}")
        if semantic.get("certified_promotion") is True:
            failures.append(f"unexpected certified promotion: {record['case_id']}")
        certificate = semantic.get("error_certificate", {})
        if certificate.get("certified") is True:
            failures.append(f"uncorroborated error certificate: {record['case_id']}")
    return failures


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    commit = os.environ.get("FORMULATRACER_ASSESSED_REVISION") or subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()
    packages = cargo_packages() + python_packages()
    sbom = {"spdxVersion":"SPDX-2.3", "dataLicense":"CC0-1.0", "SPDXID":"SPDXRef-DOCUMENT",
            "name":"FormulaTracer-prepublic-build-inputs", "documentNamespace":f"https://github.com/3e456/FormulaTracer/sbom/{commit}",
            "creationInfo":{"created":"2026-08-29T00:00:00Z","creators":["Tool: FormulaTracer-prepublic-release-hardening"]},
            "packages":packages, "source":{"commit":commit,"cargo_lock_sha256":sha_text(ROOT/'Cargo.lock'),
            "ci_requirements_sha256":sha_text(ROOT/'requirements'/'ci.txt')}}
    (OUT / "sbom.spdx.json").write_text(json.dumps(sbom,indent=2)+"\n",encoding="utf-8")
    failures = claims_gate()
    report = {"schema_version":"1.0", "source_commit":commit,
              "semantic_claims_gate":"PASS" if not failures else "FAIL",
              "sbom_format":"SPDX-2.3", "sbom_package_count":len(packages),
              "dependency_locks":{"cargo":True,"lean":True,"python_ci_constraints":True},
              "wheel_portability":{"canonical_checker":"tools/artifact_manifest.py",
                  "windows_native_isolation_required":True,"linux_native_isolation_required":True,
                  "private_trace_count_required":0,"license_and_notices_required":True},
              "failures":failures}
    (OUT / "release-hardening.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
    return int(bool(failures))


if __name__ == "__main__": raise SystemExit(main())
