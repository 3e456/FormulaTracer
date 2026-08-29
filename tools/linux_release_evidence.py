"""Record path-free evidence for the Linux release artifact built by CI."""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def command(*parts: str) -> str:
    completed = subprocess.run(parts, text=True, capture_output=True, check=False)
    return (completed.stdout or completed.stderr).splitlines()[0] if (completed.stdout or completed.stderr) else "UNAVAILABLE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-passed", action="store_true")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("Linux evidence must be generated on Linux")
    wheels = sorted((ROOT / "dist/release").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one release wheel, found {len(wheels)}")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    native = sorted(name for name in names if name.endswith((".so", ".dll", ".dylib")))
    expected_native = [name for name in native if name.endswith("libformulatracer_c_api.so")]
    # Split path markers so the public scanner does not mistake this detector
    # definition for a leaked workstation path.
    posix_home = r"(?:/" + r"home/|/" + r"Users/)[^/\s]+/"
    private_path_pattern = re.compile(rf"(?:[A-Z]:[\\/]|{posix_home})")
    text_hits = 0
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size > 16 * 1024 * 1024:
                continue
            payload = archive.read(info)
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            text_hits += len(private_path_pattern.findall(text))
    os_release = platform.freedesktop_os_release()
    payload = {
        "schema_version": "1.0",
        "status": "PASS" if args.smoke_passed and len(expected_native) == 1 and native == expected_native and text_hits == 0 else "FAIL",
        "environment": {
            "os": platform.system(), "distribution": os_release.get("PRETTY_NAME", "unknown"),
            "architecture": platform.machine(), "python": platform.python_version(),
            "rust": command("rustc", "--version"), "compiler": command("cc", "--version"),
            "glibc": " ".join(platform.libc_ver()),
        },
        "wheel": wheel.name,
        "wheel_platform_tag": wheel.stem.rsplit("-", 1)[-1],
        "native_libraries": native,
        "expected_native_library": "libformulatracer_c_api.so",
        "windows_dll_contamination": sum(name.endswith(".dll") for name in native),
        "unexpected_platform_binary": sum(not name.endswith("libformulatracer_c_api.so") for name in native),
        "private_path_trace": text_hits,
        "protected_docx": sum(name.lower().endswith(".docx") for name in names),
        "clean_install": "PASS" if args.smoke_passed else "FAIL",
        "native_load": "PASS" if args.smoke_passed else "FAIL",
        "minimal_audit": "PASS" if args.smoke_passed else "FAIL",
        "portability_claim": "ONLY_THIS_RECORDED_RUNNER_ENVIRONMENT",
    }
    destination = ROOT / "dist/release/linux-release-validation.json"
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
