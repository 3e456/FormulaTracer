"""Build the ctypes native core and assign its platform wheel tag."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
from wheel.bdist_wheel import bdist_wheel
from setuptools import setup
from setuptools.command.build_py import build_py


ROOT = Path(__file__).resolve().parent


def native_name() -> str:
    if sys.platform == "win32":
        return "formulatracer_c_api.dll"
    if sys.platform.startswith("linux"):
        return "libformulatracer_c_api.so"
    raise RuntimeError(f"unsupported FormulaTracer native platform: {sys.platform}")


class NativeBuildPy(build_py):
    """Compile from an sdist; prebuilt-wheel assembly may provide the library."""

    def run(self):
        super().run()
        name = native_name()
        prebuilt = ROOT / "python" / "formulatracer" / name
        destination = Path(self.build_lib) / "formulatracer" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if prebuilt.is_file():
            shutil.copy2(prebuilt, destination)
            return
        cargo = shutil.which("cargo")
        if cargo is None:
            candidate = Path.home() / ".cargo" / "bin" / ("cargo.exe" if sys.platform == "win32" else "cargo")
            cargo = str(candidate) if candidate.is_file() else None
        if cargo is None:
            raise RuntimeError(
                "Cargo/Rust 1.85+ is required only when building FormulaTracer from sdist; "
                "install a supported binary wheel for a toolchain-free installation"
            )
        environment = dict(os.environ)
        subprocess.run(
            [cargo, "build", "--release", "-p", "formulatracer-c-api", "--locked"],
            cwd=ROOT, env=environment, check=True,
        )
        built = ROOT / "target" / "release" / name
        if not built.is_file():
            raise RuntimeError(f"native library output not found: {built}")
        shutil.copy2(built, destination)


class PlatformIndependentPythonAbiWheel(bdist_wheel):
    """Native platform wheel whose Python facade does not use the CPython ABI."""

    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _python, _abi, platform = super().get_tag()
        return "py3", "none", platform


setup(cmdclass={"bdist_wheel": PlatformIndependentPythonAbiWheel, "build_py": NativeBuildPy})
