from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/native_migration/final/final-test-execution.json"


def run(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8",
                               errors="replace", capture_output=True, check=False)
    return {"command": command, "returncode": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr}


def main() -> int:
    cargo_path = Path.home() / ".cargo/bin/cargo.exe"
    lake_path = Path.home() / ".elan/toolchains/leanprover--lean4---v4.19.0/bin/lake.exe"
    cargo = str(cargo_path) if cargo_path.exists() else shutil.which("cargo")
    lake = str(lake_path) if lake_path.exists() else shutil.which("lake")
    if not cargo or not lake:
        raise SystemExit("required Cargo or Lean 4.19 toolchain not found")
    pytest = run([sys.executable, "-m", "pytest", "-q"])
    rust = run([cargo, "test", "--workspace"])
    cpp = run([sys.executable, "tools/run_native_cpp_tests.py"])
    differential = run([sys.executable, "tools/run_native_differential.py"])
    structural = run([sys.executable, "tools/run_structural_isomorphism_assurance.py"])
    wave_scripts = [
        "run_wave1_core_parity.py", "run_wave1_expression_parity.py",
        "run_wave1_numeric_types_parity.py", "run_wave1_math_semantics_parity.py",
        "run_wave2_knowledge_parity.py", "run_wave2_transformations_parity.py",
        "run_wave2_equality_parity.py", "run_wave3_ieee754_parity.py",
        "run_wave3_interval_parity.py", "run_wave3_probability_parity.py",
        "run_wave4_synthesis_parity.py",
    ]
    waves = [run([sys.executable, str(Path("scripts") / script)]) for script in wave_scripts]
    lean = run([lake, "build"])
    lean_sources = "\n".join(path.read_text(encoding="utf-8")
                             for path in (ROOT / "lean").rglob("*.lean"))
    forbidden = {word: len(re.findall(rf"\b{word}\b", lean_sources))
                 for word in ("sorry", "admit", "axiom")}
    pytest_text = str(pytest["stdout"]) + str(pytest["stderr"])
    passed_match = re.search(r"(\d+) passed", pytest_text)
    skipped_match = re.search(r"(\d+) skipped", pytest_text)
    subtests_match = re.search(r"(\d+) subtests passed", pytest_text)
    rust_text = str(rust["stdout"]) + str(rust["stderr"])
    rust_passed = sum(int(value) for value in re.findall(
        r"test result: ok\. (\d+) passed; 0 failed", rust_text))
    payload = {
        "schema_version": "1.0",
        "python": {"passed": int(passed_match.group(1)) if passed_match else None,
                   "skipped": int(skipped_match.group(1)) if skipped_match else 0,
                   "subtests_passed": int(subtests_match.group(1)) if subtests_match else 0,
                   "returncode": pytest["returncode"], "summary": pytest_text[-1000:]},
        "rust": {"passed": rust_passed, "returncode": rust["returncode"],
                 "summary": rust_text[-2000:]},
        "c_cpp": {"returncode": cpp["returncode"], "output": cpp["stdout"]},
        "differential": {"returncode": differential["returncode"],
                         "output": differential["stdout"]},
        "structural_isomorphism": {"returncode": structural["returncode"],
                                   "output": structural["stdout"]},
        "waves": [{"script": script, "returncode": result["returncode"]}
                  for script, result in zip(wave_scripts, waves)],
        "lean": {"returncode": lean["returncode"],
                 "output": str(lean["stdout"]) + str(lean["stderr"]),
                 "forbidden_declarations": forbidden},
    }
    payload["status"] = "PASS" if (
        pytest["returncode"] == rust["returncode"] == cpp["returncode"]
        == differential["returncode"] == structural["returncode"] == lean["returncode"] == 0
        and all(item["returncode"] == 0 for item in waves)
        and all(value == 0 for value in forbidden.values())) else "FAIL"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("status", "python", "rust", "lean")},
                     indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
