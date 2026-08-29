from pathlib import Path

import pytest

from tools.build_native_wheel import (compatible_wheel, native_archive_status,
                                      native_archive_uses_purelib,
                                      platform_native_library)


def test_native_library_selection_is_platform_specific():
    assert platform_native_library("win32") == "formulatracer_c_api.dll"
    assert platform_native_library("linux") == "libformulatracer_c_api.so"
    with pytest.raises(RuntimeError, match="unsupported wheel platform"):
        platform_native_library("darwin")


def test_wheel_selection_never_crosses_platforms():
    windows = Path("formulatracer-0.1.0-py3-none-win_amd64.whl")
    linux = Path("formulatracer-0.1.0-py3-none-linux_x86_64.whl")
    assert compatible_wheel(windows, "win32")
    assert not compatible_wheel(linux, "win32")
    assert compatible_wheel(linux, "linux")
    assert not compatible_wheel(windows, "linux")


def test_archive_rejects_mixed_platform_native_libraries():
    windows = "formulatracer/formulatracer_c_api.dll"
    linux = "formulatracer/libformulatracer_c_api.so"
    assert native_archive_status([windows], "win32") == ([windows], True)
    assert native_archive_status([linux], "linux") == ([linux], True)
    assert native_archive_status([windows, linux], "linux")[1] is False
    assert native_archive_status([windows], "linux")[1] is False


def test_archive_rejects_native_library_in_purelib_scheme():
    invalid = "formulatracer-0.1.0.data/purelib/formulatracer/libformulatracer_c_api.so"
    valid = "formulatracer/libformulatracer_c_api.so"
    assert native_archive_uses_purelib([invalid])
    assert not native_archive_uses_purelib([valid])
