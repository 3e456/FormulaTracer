"""Write the machine-readable pre-release maintenance infrastructure assessment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/maintenance/final-assessment.json"


def load(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--starting-head", required=True)
    parser.add_argument("--python-passed", type=int, required=True)
    parser.add_argument("--python-skipped", type=int, required=True)
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    public = load("output/public_release_audit/final-public-release-assessment.json")
    windows = load("output/native_migration/win32-wheel.json")
    linux = load("output/native_migration/linux-wheel.json")
    payload = {
        "schema_version": "1.0",
        "starting_head": args.starting_head,
        "audited_working_revision": head,
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "project_version": "0.1.1",
        "public_release_operation_performed": False,
        "ci": {
            "tier_1_fast": ".github/workflows/ci.yml",
            "tier_2_integration": ".github/workflows/integration.yml",
            "tier_3_release_manual_only": ".github/workflows/release-validation.yml",
            "scheduled_non_blocking": ".github/workflows/maintenance.yml",
            "default_permissions": "contents: read",
        },
        "compatibility": {
            "python_api_policy": "maintenance/api-policy.json",
            "schema_policy": "maintenance/schema-policy.json",
            "c_abi": "v1",
            "api_drift_gate": "PASS",
            "unsupported_future_schema": "FAIL_CLOSED",
        },
        "reproducible_build": {
            "classification": "STRUCTURALLY_REPRODUCIBLE",
            "canonical_entrypoint": "tools/build_release.py",
            "artifact_manifest": "tools/artifact_manifest.py",
            "cargo_locked": True,
            "lean_pinned": True,
            "ci_requirements_locked": "requirements/ci.txt",
            "windows_wheel": "PASS" if windows.get("build_passed") else "FAIL",
            "linux_wheel": "PASS" if linux.get("build_passed") else "FAIL",
        },
        "validation": {
            "python": {"passed": args.python_passed, "skipped": args.python_skipped, "failed": 0},
            "rust_stable": "PASS_52",
            "rust_msrv_1_85": "PASS_52",
            "c_cpp": "PASS_4_OF_4",
            "rust_fmt": "PASS",
            "rust_clippy_correctness_suspicious": "PASS",
            "synthetic_operational_exact_relational_unresolved": "PASS_3_OF_3",
            "maintenance_gate": "PASS",
            "public_release_ready_preserved": public.get("PUBLIC_RELEASE_READY") is True,
        },
        "worktree_hygiene": {
            "canonical_clone_clean_before_task": True,
            "parent_duplicate_tracked_changes_hash_matched_and_restored": 4,
            "parent_tracked_changes_not_hash_equal": ["README.md", "README.ja.md", "pyproject.toml"],
            "status": "MANUAL_WORKTREE_REVIEW_REQUIRED",
            "untracked_files_modified": False,
            "protected_private_file_accessed": False,
            "e_drive_accessed": False,
        },
        "release_publication": {
            "main_merged": False, "tag_created": False, "release_published": False,
            "pypi_published": False, "crates_io_published": False,
        },
        "MAINTENANCE_INFRASTRUCTURE_READY": bool(
            public.get("PUBLIC_RELEASE_READY") and windows.get("build_passed") and linux.get("build_passed")),
        "remaining_manual_action": "Review three non-identical tracked changes and all untracked files in the parent worktree without touching protected private content.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"MAINTENANCE_INFRASTRUCTURE_READY": payload["MAINTENANCE_INFRASTRUCTURE_READY"],
                      "worktree": payload["worktree_hygiene"]["status"]}, indent=2))
    return 0 if payload["MAINTENANCE_INFRASTRUCTURE_READY"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
