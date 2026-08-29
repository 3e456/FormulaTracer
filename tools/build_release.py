"""Canonical non-publishing entrypoint for FormulaTracer release artifacts."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "dist" / "release"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("wheel", "sdist", "all"), default="all")
    args = parser.parse_args()
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)
    artifacts: list[Path] = []
    if args.kind in {"wheel", "all"}:
        run([sys.executable, "tools/build_native_wheel.py"])
        wheel = max((ROOT / "dist/native").glob("*.whl"), key=lambda item: item.stat().st_mtime)
        destination = STAGING / wheel.name
        shutil.copy2(wheel, destination)
        artifacts.append(destination)
    if args.kind in {"sdist", "all"}:
        command = [sys.executable, "-m", "build", "--sdist", "--outdir", str(STAGING)]
        if os.environ.get("FORMULATRACER_NO_BUILD_ISOLATION") == "1":
            command.append("--no-isolation")
        run(command)
        artifacts.extend(STAGING.glob("*.tar.gz"))
    run([sys.executable, "tools/artifact_manifest.py", *map(str, artifacts),
         "--output", str(STAGING / "release-manifest.json")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
