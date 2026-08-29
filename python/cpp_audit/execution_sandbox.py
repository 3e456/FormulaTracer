"""Conservative runtime-evidence sandbox for generated validation code."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable, Mapping


@dataclass(frozen=True)
class SandboxPolicy:
    timeout_seconds: float = 10.0
    network_disabled: bool = True
    external_inputs_read_only: bool = True
    memory_limit_bytes: int | None = None
    max_output_bytes: int = 1_000_000
    allow_unenforced_network_isolation: bool = False


@dataclass(frozen=True)
class SandboxExecutionEvidence:
    status: str
    command: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    temporary_directory: str
    network_control: str
    resource_control: str
    external_inputs: tuple[str, ...]
    evidence_level: str = "RUNTIME_EVIDENCE"
    proof_authority: bool = False

    def to_dict(self) -> dict: return asdict(self)


def run_sandboxed(command: Iterable[str], *, policy: SandboxPolicy | None = None,
                  external_inputs: Iterable[str | Path] = (),
                  environment: Mapping[str, str] | None = None) -> SandboxExecutionEvidence:
    """Run without a shell in an isolated temporary cwd.

    Network denial is an OS-enforced claim only where an external sandbox has
    supplied one.  This reference backend scrubs proxy variables and reports
    that limitation instead of claiming proof-grade isolation.
    """
    selected = policy or SandboxPolicy(); argv = tuple(str(item) for item in command)
    if not argv: raise ValueError("SANDBOX_COMMAND_REQUIRED")
    inputs = tuple(str(Path(item).resolve()) for item in external_inputs)
    for item in inputs:
        if not Path(item).exists(): raise FileNotFoundError(item)
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}}
    env.update({str(key): str(value) for key, value in (environment or {}).items()})
    if selected.network_disabled:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            env.pop(key, None)
        env["FORMULATRACER_NETWORK_POLICY"] = "DISABLED_BY_DEFAULT"
        if not selected.allow_unenforced_network_isolation:
            return SandboxExecutionEvidence("RUNTIME_EVIDENCE_BLOCKED_BY_SANDBOX_POLICY", argv, None,
                "", "Network isolation is unavailable on the reference backend.", False, "",
                "NETWORK_DENIAL_NOT_OS_ENFORCEABLE;EXECUTION_BLOCKED",
                "NOT_EXECUTED", inputs)
    with tempfile.TemporaryDirectory(prefix="formulatracer-sandbox-") as directory:
        try:
            completed = subprocess.run(argv, cwd=directory, env=env, capture_output=True, text=True,
                                       timeout=selected.timeout_seconds, shell=False, check=False)
            stdout, stderr = completed.stdout[:selected.max_output_bytes], completed.stderr[:selected.max_output_bytes]
            status = "RUNTIME_EVIDENCE_SUCCEEDED" if completed.returncode == 0 else "RUNTIME_EVIDENCE_FAILED"
            return SandboxExecutionEvidence(status, argv, completed.returncode, stdout, stderr, False, directory,
                "ENVIRONMENT_SCRUB_ONLY_NOT_OS_ENFORCED" if selected.network_disabled else "NETWORK_ALLOWED",
                "TIMEOUT_ENFORCED;MEMORY_LIMIT_NOT_ENFORCED" if selected.memory_limit_bytes else "TIMEOUT_ENFORCED",
                inputs)
        except subprocess.TimeoutExpired as exc:
            return SandboxExecutionEvidence("RUNTIME_EVIDENCE_TIMED_OUT", argv, None,
                (exc.stdout or "")[:selected.max_output_bytes] if isinstance(exc.stdout, str) else "",
                (exc.stderr or "")[:selected.max_output_bytes] if isinstance(exc.stderr, str) else "",
                True, directory, "ENVIRONMENT_SCRUB_ONLY_NOT_OS_ENFORCED", "TIMEOUT_ENFORCED", inputs)
