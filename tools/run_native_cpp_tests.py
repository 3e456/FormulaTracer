"""Build and run the stable C ABI and thin C++ wrapper conformance tests.

Some Windows process launchers expose both ``Path`` and ``PATH``.  MSBuild
rejects that environment before it invokes a compiler, so this runner creates
a case-insensitively unique environment for the child toolchain.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "native-api-tests-msvc"
REPORT = ROOT / "output" / "native_migration" / "cross_language_conformance.json"


def normalized_environment() -> dict[str, str]:
    result: dict[str, str] = {}
    spelling: dict[str, str] = {}
    for key, value in os.environ.items():
        folded = key.casefold()
        previous = spelling.get(folded)
        if previous is not None:
            result.pop(previous, None)
        preferred = "Path" if folded == "path" else key
        spelling[folded] = preferred
        result[preferred] = value
    return result


def msvc_environment() -> dict[str, str]:
    """Import the supported MSVC developer environment without a shell build."""
    base = normalized_environment()
    program_files = Path(os.environ.get("ProgramFiles", ""))
    vsdevcmd = program_files / "Microsoft Visual Studio" / "2022" / "Community" / "Common7" / "Tools" / "VsDevCmd.bat"
    if not vsdevcmd.exists():
        return base
    completed = subprocess.run(
        f'cmd.exe /d /c call "{vsdevcmd}" -arch=x64 >nul && set',
        env=base,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return base
    imported = dict(base)
    for line in completed.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            key, value = line.split("=", 1)
            imported[key] = value
    return imported


def run(command: list[str], environment: dict[str, str]) -> dict[str, object]:
    resolved = shutil.which(command[0], path=environment.get("Path") or environment.get("PATH"))
    if resolved:
        command = [resolved, *command[1:]]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def public_step(step: dict[str, object]) -> dict[str, object]:
    """Remove workstation paths while retaining conformance evidence."""
    replacements = (
        (str(ROOT), "<PROJECT_ROOT>"),
        (os.environ.get("ProgramFiles", ""), "<PROGRAM_FILES>"),
        (str(Path.home()), "<USER_HOME>"),
    )

    def sanitize(value: object) -> object:
        if isinstance(value, str):
            for actual, placeholder in replacements:
                if actual:
                    value = value.replace(actual, placeholder).replace(actual.replace("\\", "/"), placeholder)
            return value
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    return {key: sanitize(value) for key, value in step.items()}


def main() -> int:
    environment = msvc_environment()
    BUILD.mkdir(parents=True, exist_ok=True)
    library = ROOT / "target" / "debug" / "formulatracer_c_api.dll.lib"
    c_executable = BUILD / "formulatracer_c_api_test.exe"
    cpp_executable = BUILD / "formulatracer_cpp_api_test.exe"
    steps = [
        run(
            [
                "cl.exe", "/nologo", "/W4", "/std:c17", f"/I{ROOT / 'include'}",
                str(ROOT / "tests" / "native" / "c_api_test.c"), str(library),
                f"/Fo:{BUILD / 'c_api_test.obj'}", f"/Fe:{c_executable}",
            ],
            environment,
        )
    ]
    if steps[-1]["returncode"] == 0:
        steps.append(
            run(
                [
                    "cl.exe", "/nologo", "/W4", "/EHsc", "/std:c++20", f"/I{ROOT / 'include'}",
                    str(ROOT / "tests" / "native" / "cpp_api_test.cpp"), str(library),
                    f"/Fo:{BUILD / 'cpp_api_test.obj'}", f"/Fe:{cpp_executable}",
                ],
                environment,
            )
        )
    runtime_path = str(ROOT / "target" / "debug") + os.pathsep + environment.get("Path", "")
    environment["Path"] = runtime_path
    if steps[-1]["returncode"] == 0:
        steps.append(run([str(c_executable)], environment))
    if steps[-1]["returncode"] == 0:
        steps.append(run([str(cpp_executable)], environment))
    passed = len(steps) == 4 and all(step["returncode"] == 0 for step in steps)
    payload = {
        "schema_version": "1.0",
        "interop_contract": "STABLE_C_ABI_V1",
        "bindings": {
            "c": "DIRECT_C_ABI",
            "cpp": "THIN_RAII_OVER_C_ABI",
            "python": "THIN_ERGONOMIC_OVER_C_ABI",
            "rust": "NATIVE_API_SAME_CORE",
        },
        "semantic_implementation_count": 1,
        "generated_research_code_languages": ["Python", "Rust", "C++"],
        "tooling_limitation": "CMake 3.31 crashes after MSVC detection in this Unicode workspace; direct MSVC conformance is authoritative for this host",
        "passed": passed,
        "steps": [public_step(step) for step in steps],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "returncodes": [step["returncode"] for step in steps]}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
