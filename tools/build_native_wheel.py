"""Build a platform wheel containing the stable-C-ABI native core."""

from __future__ import annotations

import json
import hashlib
import os
import platform
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "python" / "formulatracer"
DIST = ROOT / "dist" / "native"
REPORT = ROOT / "output" / "native_migration" / f"{sys.platform}-wheel.json"
NATIVE_LIBRARY_NAMES = {"formulatracer_c_api.dll", "libformulatracer_c_api.so"}


def public_text(value: str) -> str:
    """Remove workstation/container paths from versioned public evidence."""
    replacements = ((str(ROOT), "<PROJECT_ROOT>"), (str(Path.home()), "<USER_HOME>"),
                    (str(Path(sys.prefix)), "<PYTHON_ENV>"),
                    ("/work", "<PROJECT_ROOT>"))
    for actual, replacement in replacements:
        for spelling in (actual, actual.replace("\\", "/")):
            value = re.sub(re.escape(spelling), replacement, value, flags=re.IGNORECASE)
    return value


def platform_native_library(platform_name: str) -> str:
    if platform_name == "win32":
        return "formulatracer_c_api.dll"
    if platform_name.startswith("linux"):
        return "libformulatracer_c_api.so"
    raise RuntimeError(f"unsupported wheel platform: {platform_name}")


def compatible_wheel(path: Path, platform_name: str) -> bool:
    name = path.name.lower()
    return ("-win_amd64.whl" in name if platform_name == "win32"
            else "-linux_x86_64.whl" in name)


def remove_stale_packaging_libraries() -> None:
    """Remove only transient native copies, including setuptools' stale build cache."""
    directories = [PACKAGE]
    directories.extend(path / "formulatracer" for path in (ROOT / "build").glob("lib*"))
    for directory in directories:
        for name in NATIVE_LIBRARY_NAMES:
            (directory / name).unlink(missing_ok=True)


def native_archive_status(names: list[str], platform_name: str) -> tuple[list[str], bool]:
    native = sorted(name for name in names if Path(name).name in NATIVE_LIBRARY_NAMES)
    expected = platform_native_library(platform_name)
    return native, len(native) == 1 and Path(native[0]).name == expected


def native_archive_uses_purelib(names: list[str]) -> bool:
    """Reject native payloads installed through a wheel's purelib scheme."""
    return any(
        ".data/purelib/" in name and Path(name).name in NATIVE_LIBRARY_NAMES
        for name in names
    )


def main() -> int:
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo.exe")
    build = subprocess.run([cargo, "build", "--workspace", "--release"], cwd=ROOT, check=False)
    if build.returncode:
        return build.returncode
    native_name = platform_native_library(sys.platform)
    source = ROOT / "target" / "release" / native_name
    if not source.exists():
        source = None
    if source is None:
        raise SystemExit("native library output not found")
    remove_stale_packaging_libraries()
    embedded = PACKAGE / source.name
    DIST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, embedded)
    try:
        command = [sys.executable, "-m", "pip", "wheel", ".", "--no-cache-dir",
                   "--no-deps", "-w", str(DIST)]
        if os.environ.get("FORMULATRACER_NO_BUILD_ISOLATION") == "1":
            command.insert(5, "--no-build-isolation")
        wheel = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        embedded.unlink(missing_ok=True)
    artifacts = sorted((path for path in DIST.glob("*.whl") if compatible_wheel(path, sys.platform)),
                       key=lambda path: path.stat().st_mtime)
    artifact = artifacts[-1] if artifacts else None
    license_files: list[str] = []
    notice_files: list[str] = []
    contains_complete_license = False
    contains_docx = False
    native_library_entries: list[str] = []
    platform_native_only = False
    native_library_in_purelib = False
    if artifact:
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
            license_files = [name for name in names if name.endswith("LICENSE")]
            notice_files = [name for name in names if name.endswith("THIRD_PARTY_NOTICES.md")]
            contains_docx = any(name.lower().endswith(".docx") for name in names)
            contains_complete_license = bool(license_files) and b"TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in archive.read(license_files[0])
            native_library_entries, platform_native_only = native_archive_status(names, sys.platform)
            native_library_in_purelib = native_archive_uses_purelib(names)
    payload = {
        "schema_version": "1.0",
        "platform": sys.platform,
        "architecture": platform.machine() or os.environ.get("PROCESSOR_ARCHITECTURE", "unknown"),
        "native_library": source.name,
        "wheel": str(artifact.relative_to(ROOT)) if artifact else None,
        "wheel_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact else None,
        "wheel_size_bytes": artifact.stat().st_size if artifact else None,
        "license_files": license_files,
        "third_party_notice_files": notice_files,
        "complete_project_license_included": contains_complete_license,
        "docx_included": contains_docx,
        "native_library_entries": native_library_entries,
        "platform_native_only": platform_native_only,
        "native_library_in_purelib": native_library_in_purelib,
        "build_passed": wheel.returncode == 0 and bool(artifact) and contains_complete_license and bool(notice_files)
        and not contains_docx and platform_native_only and not native_library_in_purelib,
        "normal_user_requires_rust": False,
        "stdout": public_text(wheel.stdout),
        "stderr": public_text(wheel.stderr),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("platform", "wheel", "build_passed")}, indent=2))
    return 0 if payload["build_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
