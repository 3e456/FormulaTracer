"""Runtime evidence for semantic execution ownership.

This module observes routing only.  It never makes a mathematical decision.
The recorder is process-local, thread-safe, bounded, and intentionally explicit
about unsupported/unresolved calls versus Python fallback.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import inspect
import json
from pathlib import Path
import sys
from threading import Lock
from typing import Any, Iterator, Mapping


PATHS = {"RUST_NATIVE", "PYTHON_REFERENCE", "PYTHON_FALLBACK", "UNSUPPORTED", "UNRESOLVED"}
KERNELS = tuple("ABCDEF")
_MAX_EVENTS = 250_000
_lock = Lock()
_events: list["SemanticPathEvent"] = []
_sequence = 0
_path_counts: Counter[str] = Counter()
_calls_by_kernel: Counter[str] = Counter()
_calls_by_owner: Counter[str] = Counter()
_calls_by_operation: Counter[str] = Counter()
_calls_by_scope: Counter[str] = Counter()
_paths_by_scope: Counter[tuple[str, str]] = Counter()
_fallback_by_kernel: Counter[str] = Counter()
_dropped_event_details = 0
_event_detail_enabled = True
_execution_scope: ContextVar[str] = ContextVar("formulatracer_execution_scope", default="PRODUCTION")
EXECUTION_SCOPES = {"PRODUCTION", "DIFFERENTIAL_VALIDATION", "REFERENCE_ORACLE", "TEST_ONLY"}
NON_SEMANTIC_BOUNDARY_OPERATIONS = {
    "__init__", "to_dict", "to_json", "to_tex", "to_dsl", "to_unicode",
    "to_markdown", "to_schema", "inspect",
}
NON_SEMANTIC_MODULE_OPERATIONS = {
    "mathematical_knowledge": {"default", "entries", "metrics", "get", "register"},
    "transformations": {"load_rewrite_catalog"},
}

PYTHON_REFERENCE_KERNELS: dict[str, str] = {
    **{name: "A" for name in ("bitvector", "logic_semantics",
                               "mathematical_primitives", "numeric_types", "units")},
    **{name: "B" for name in ("expression", "math_semantics", "transformations",
                               "equality_saturation")},
    **{name: "C" for name in ("approximation_families", "approximation_proofs",
                               "parallel_semantics")},
    **{name: "D" for name in ("mathematical_knowledge",)},
    "core": "F",
}


@dataclass(frozen=True)
class SemanticPathEvent:
    sequence: int
    kernel: str
    component: str
    operation: str
    caller: str
    semantic_owner: str
    execution_backend: str
    path: str
    fallback_used: bool
    fallback_reason: str | None
    request_id: str
    result_id: str
    execution_scope: str


def _next_ids() -> tuple[int, str, str]:
    global _sequence
    with _lock:
        _sequence += 1
        sequence = _sequence
    return sequence, f"semantic-request:{sequence}", f"semantic-result:{sequence}"


def inferred_caller(depth: int = 2) -> str:
    frame = inspect.currentframe()
    try:
        for _ in range(depth):
            frame = frame.f_back if frame else None
        if frame is None:
            return "UNKNOWN_CALLER"
        module = frame.f_globals.get("__name__", "<unknown>")
        return f"{module}.{frame.f_code.co_name}:{frame.f_lineno}"
    finally:
        del frame


def record_semantic_path(*, kernel: str, component: str, operation: str,
                         semantic_owner: str, execution_backend: str, path: str,
                         fallback_used: bool = False, fallback_reason: str | None = None,
                         caller: str | None = None) -> SemanticPathEvent:
    if kernel not in KERNELS:
        raise ValueError(f"UNKNOWN_SEMANTIC_KERNEL:{kernel}")
    if path not in PATHS:
        raise ValueError(f"UNKNOWN_SEMANTIC_PATH:{path}")
    if fallback_used != (path == "PYTHON_FALLBACK"):
        raise ValueError("FALLBACK_FLAG_PATH_MISMATCH")
    sequence, request_id, result_id = _next_ids()
    scope = _execution_scope.get()
    event = SemanticPathEvent(
        sequence, kernel, component, operation, caller or inferred_caller(3),
        semantic_owner, execution_backend, path, fallback_used, fallback_reason,
        request_id, result_id, scope,
    )
    global _dropped_event_details
    with _lock:
        _path_counts[path] += 1
        _calls_by_kernel[kernel] += 1
        _calls_by_owner[component] += 1
        _calls_by_operation[f"{component}:{operation}"] += 1
        _calls_by_scope[scope] += 1
        _paths_by_scope[(scope, path)] += 1
        if fallback_used:
            _fallback_by_kernel[kernel] += 1
        if _event_detail_enabled and len(_events) < _MAX_EVENTS:
            _events.append(event)
        else:
            _dropped_event_details += 1
    return event


def reset_semantic_runtime_metrics() -> None:
    global _sequence, _dropped_event_details
    with _lock:
        _events.clear()
        _path_counts.clear()
        _calls_by_kernel.clear()
        _calls_by_owner.clear()
        _calls_by_operation.clear()
        _calls_by_scope.clear()
        _paths_by_scope.clear()
        _fallback_by_kernel.clear()
        _sequence = 0
        _dropped_event_details = 0


def semantic_runtime_events() -> tuple[dict[str, Any], ...]:
    with _lock:
        return tuple(asdict(event) for event in _events)


def semantic_runtime_snapshot(*, include_events: bool = True) -> dict[str, Any]:
    events = semantic_runtime_events()
    with _lock:
        paths = _path_counts.copy()
        fallback_by_kernel = {kernel: _fallback_by_kernel[kernel] for kernel in KERNELS}
        calls_by_kernel = {kernel: _calls_by_kernel[kernel] for kernel in KERNELS}
        calls_by_owner = dict(_calls_by_owner.most_common())
        calls_by_operation = dict(_calls_by_operation.most_common())
        calls_by_scope = dict(_calls_by_scope)
        paths_by_scope = {
            scope: {path: _paths_by_scope[(scope, path)] for path in sorted(PATHS)}
            for scope in sorted(EXECUTION_SCOPES)
        }
        dropped = _dropped_event_details
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "TOTAL_SEMANTIC_CALLS": sum(paths.values()),
        "RUST_NATIVE_SEMANTIC_CALLS": paths["RUST_NATIVE"],
        "PYTHON_REFERENCE_CALLS": paths["PYTHON_REFERENCE"],
        "PYTHON_SEMANTIC_FALLBACK_COUNT": paths["PYTHON_FALLBACK"],
        "UNSUPPORTED_COUNT": paths["UNSUPPORTED"],
        "UNRESOLVED_COUNT": paths["UNRESOLVED"],
        "fallback_by_kernel": fallback_by_kernel,
        "calls_by_kernel": calls_by_kernel,
        "calls_by_owner": calls_by_owner,
        "calls_by_operation": calls_by_operation,
        "calls_by_scope": calls_by_scope,
        "paths_by_scope": paths_by_scope,
        "event_limit": _MAX_EVENTS,
        "recorded_event_details": len(events),
        "dropped_event_details": dropped,
    }
    if include_events:
        payload["events"] = list(events)
    return payload


@contextmanager
def observe_python_semantic_runtime(
    module_kernels: Mapping[str, str] | None = None,
    *, capture_event_details: bool = True, execution_scope: str = "PRODUCTION",
) -> Iterator[None]:
    """Measure execution of retained Python semantic owners without rerouting it."""
    global _event_detail_enabled
    if execution_scope not in EXECUTION_SCOPES:
        raise ValueError(f"UNKNOWN_EXECUTION_SCOPE:{execution_scope}")
    kernels = dict(module_kernels or PYTHON_REFERENCE_KERNELS)
    previous = sys.getprofile()
    previous_detail_setting = _event_detail_enabled
    scope_token = _execution_scope.set(execution_scope)
    _event_detail_enabled = capture_event_details
    active = False

    def profile(frame: Any, event: str, arg: Any) -> None:
        nonlocal active
        if previous is not None:
            previous(frame, event, arg)
        if event != "call" or active:
            return
        module = str(frame.f_globals.get("__name__", ""))
        if not module.startswith("cpp_audit."):
            return
        caller_module = str(frame.f_back.f_globals.get("__name__", "")) if frame.f_back else ""
        # Count ownership-boundary entries, not every private helper, comprehension,
        # recursion step, or property reached inside the same semantic owner.
        if caller_module == module:
            return
        kernel = kernels.get(module.rsplit(".", 1)[-1])
        if kernel is None:
            return
        active = True
        try:
            operation = frame.f_code.co_name
            stem = module.rsplit(".", 1)[-1]
            if (operation in NON_SEMANTIC_BOUNDARY_OPERATIONS
                    or operation in NON_SEMANTIC_MODULE_OPERATIONS.get(stem, set())):
                return
            record_semantic_path(
                kernel=kernel,
                component=module,
                operation=operation,
                caller=(f"{caller_module}.{frame.f_back.f_code.co_name}:"
                        f"{frame.f_back.f_lineno}" if frame.f_back else "UNKNOWN_CALLER"),
                semantic_owner="PYTHON_REFERENCE",
                execution_backend="CPYTHON",
                path="PYTHON_REFERENCE",
            )
        finally:
            active = False

    sys.setprofile(profile)
    try:
        yield
    finally:
        sys.setprofile(previous)
        _event_detail_enabled = previous_detail_setting
        _execution_scope.reset(scope_token)


@contextmanager
def semantic_execution_scope(scope: str) -> Iterator[None]:
    """Classify native/reference calls without changing their semantics."""
    if scope not in EXECUTION_SCOPES:
        raise ValueError(f"UNKNOWN_EXECUTION_SCOPE:{scope}")
    token = _execution_scope.set(scope)
    try:
        yield
    finally:
        _execution_scope.reset(token)


def write_semantic_runtime_snapshot(path: str | Path, *, include_events: bool = True) -> dict[str, Any]:
    payload = semantic_runtime_snapshot(include_events=include_events)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload
