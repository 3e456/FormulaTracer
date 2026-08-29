"""Thin stable-C-ABI facade for the native FormulaTracer semantic core.

This module owns conversion, lifetime, and error mapping only. Semantic
decisions belong exclusively to ``formulatracer-core``.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

from .runtime_paths import inferred_caller, record_semantic_path


class NativeUnavailableError(RuntimeError):
    pass


class NativeCallError(RuntimeError):
    pass


def _candidate_libraries() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    candidates = []
    if configured := os.environ.get("FORMULATRACER_NATIVE_LIBRARY"):
        candidates.append(Path(configured))
    candidates.extend([
        Path(__file__).with_name("formulatracer_c_api.dll"),
        Path(__file__).with_name("libformulatracer_c_api.so"),
        root / "target" / "debug" / "formulatracer_c_api.dll",
        root / "target" / "debug" / "deps" / "formulatracer_c_api.dll",
        root / "target" / "release" / "formulatracer_c_api.dll",
        root / "target" / "release" / "libformulatracer_c_api.so",
        root / "target" / "debug" / "libformulatracer_c_api.so",
    ])
    return candidates


class NativeLibrary:
    ABI_VERSION = 1

    def __init__(self, path: str | Path | None = None):
        target = Path(path) if path else next((item for item in _candidate_libraries() if item.exists()), None)
        if target is None:
            raise NativeUnavailableError("NATIVE_COMPONENT_INCOMPLETE: FormulaTracer native library not found")
        self.path = target.resolve()
        self._lib = ctypes.CDLL(str(self.path))
        self._configure()
        actual = int(self._lib.ft_abi_version())
        if actual != self.ABI_VERSION:
            raise NativeUnavailableError(f"C_ABI_VERSION_MISMATCH: expected {self.ABI_VERSION}, got {actual}")

    def _configure(self) -> None:
        pointer = ctypes.c_void_p
        self._lib.ft_abi_version.restype = ctypes.c_uint32
        self._lib.ft_context_create.restype = pointer
        self._lib.ft_context_free.argtypes = [pointer]
        self._lib.ft_context_last_error.argtypes = [pointer]
        self._lib.ft_context_last_error.restype = pointer
        self._lib.ft_kernel_execute_json.argtypes = [pointer, ctypes.c_char_p]
        self._lib.ft_kernel_execute_json.restype = pointer
        self._lib.ft_formula_from_json.argtypes = [pointer, ctypes.c_char_p]
        self._lib.ft_formula_from_json.restype = pointer
        self._lib.ft_formula_from_tex.argtypes = [pointer, ctypes.c_char_p]
        self._lib.ft_formula_from_tex.restype = pointer
        self._lib.ft_formula_free.argtypes = [pointer]
        self._lib.ft_verify.argtypes = [pointer, pointer]
        self._lib.ft_verify.restype = pointer
        self._lib.ft_verify_pair.argtypes = [pointer, pointer, pointer]
        self._lib.ft_verify_pair.restype = pointer
        self._lib.ft_result_status.argtypes = [pointer]
        self._lib.ft_result_status.restype = ctypes.c_int
        self._lib.ft_result_theory.argtypes = [pointer]
        self._lib.ft_result_theory.restype = pointer
        self._lib.ft_result_implementation.argtypes = [pointer]
        self._lib.ft_result_implementation.restype = pointer
        self._lib.ft_semantic_object_to_json.argtypes = [pointer]
        self._lib.ft_semantic_object_to_json.restype = pointer
        self._lib.ft_semantic_object_to_tex.argtypes = [pointer]
        self._lib.ft_semantic_object_to_tex.restype = pointer
        self._lib.ft_semantic_object_free.argtypes = [pointer]
        self._lib.ft_function_from_ir_json.argtypes = [pointer, ctypes.c_char_p, ctypes.c_char_p]
        self._lib.ft_function_from_ir_json.restype = pointer
        self._lib.ft_function_from_json.argtypes = [pointer, ctypes.c_char_p]
        self._lib.ft_function_from_json.restype = pointer
        self._lib.ft_function_evaluate_json.argtypes = [pointer, pointer, ctypes.c_char_p]
        self._lib.ft_function_evaluate_json.restype = pointer
        self._lib.ft_function_substitute_json.argtypes = [pointer, pointer, ctypes.c_char_p]
        self._lib.ft_function_substitute_json.restype = pointer
        for name in ("ft_function_to_json", "ft_function_to_tex", "ft_function_inspect_json"):
            function = getattr(self._lib, name); function.argtypes = [pointer]; function.restype = pointer
        self._lib.ft_function_free.argtypes = [pointer]
        for name in ("ft_result_theory_function", "ft_result_implementation_function",
                     "ft_result_error_function", "ft_result_range_lower_function",
                     "ft_result_range_upper_function"):
            function = getattr(self._lib, name); function.argtypes = [pointer]; function.restype = pointer
        for name in ("ft_result_to_json", "ft_result_to_tex", "ft_result_diagnostics_json", "ft_result_assumptions_json",
                     "ft_result_evidence_json", "ft_result_error_json", "ft_result_range_json"):
            function = getattr(self._lib, name); function.argtypes = [pointer]; function.restype = pointer
        self._lib.ft_result_to_audit_bundle_json.argtypes = [pointer, pointer, ctypes.c_char_p,
                                                              ctypes.c_char_p, ctypes.c_char_p]
        self._lib.ft_result_to_audit_bundle_json.restype = pointer
        self._lib.ft_result_free.argtypes = [pointer]
        self._lib.ft_string_free.argtypes = [pointer]

    def take_string(self, pointer: int | None) -> str:
        if not pointer:
            return ""
        try:
            return ctypes.string_at(pointer).decode("utf-8")
        finally:
            self._lib.ft_string_free(pointer)


class NativeContext:
    def __init__(self, library: NativeLibrary | None = None):
        self._handle = None
        self.library = library or NativeLibrary()
        self._handle = self.library._lib.ft_context_create()
        if not self._handle:
            raise NativeCallError("ft_context_create failed")

    def close(self) -> None:
        if self._handle:
            self.library._lib.ft_context_free(self._handle); self._handle = None

    def __enter__(self) -> "NativeContext": return self
    def __exit__(self, *_: object) -> None: self.close()
    def __del__(self) -> None: self.close()

    def error(self) -> str:
        return self.library.take_string(self.library._lib.ft_context_last_error(self._handle))

    def formula_from_json(self, value: dict[str, Any] | str) -> "NativeFormula":
        encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        handle = self.library._lib.ft_formula_from_json(self._handle, encoded.encode("utf-8"))
        if not handle:
            reason = self.error() or "ft_formula_from_json failed"
            record_semantic_path(kernel="B", component="mathematical_ir", operation="FORMULA_FROM_JSON",
                                 semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                                 path="UNRESOLVED", fallback_reason=reason, caller=inferred_caller(2))
            raise NativeCallError(reason)
        record_semantic_path(kernel="B", component="mathematical_ir", operation="FORMULA_FROM_JSON",
                             semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                             path="RUST_NATIVE", caller=inferred_caller(2))
        return NativeFormula(self, handle)

    def formula_from_tex(self, tex: str) -> "NativeFormula":
        handle = self.library._lib.ft_formula_from_tex(self._handle, tex.encode("utf-8"))
        if not handle:
            reason = self.error() or "ft_formula_from_tex failed"
            record_semantic_path(kernel="B", component="tex_parser", operation="FORMULA_FROM_TEX",
                                 semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                                 path="UNRESOLVED", fallback_reason=reason, caller=inferred_caller(2))
            raise NativeCallError(reason)
        record_semantic_path(kernel="B", component="tex_parser", operation="FORMULA_FROM_TEX",
                             semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                             path="RUST_NATIVE", caller=inferred_caller(2))
        return NativeFormula(self, handle)

    def execute_kernel(self, request: dict[str, Any]) -> dict[str, Any]:
        kernel = str(request.get("kernel", "B"))
        operation = str(request.get("operation", "UNKNOWN"))
        caller = inferred_caller(2)
        encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        pointer = self.library._lib.ft_kernel_execute_json(self._handle, encoded)
        if not pointer:
            reason = self.error() or "ft_kernel_execute_json failed"
            normalized_reason = reason.upper()
            path = "UNSUPPORTED" if any(marker in normalized_reason for marker in (
                "NATIVE_COMPONENT_INCOMPLETE", "UNSUPPORTED", "UNSUPPORTED NATIVE COMPONENT"
            )) else "UNRESOLVED"
            record_semantic_path(kernel=kernel, component="semantic_kernel", operation=operation,
                                 semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                                 path=path, fallback_reason=reason, caller=caller)
            raise NativeCallError(reason)
        result = json.loads(self.library.take_string(pointer))
        record_semantic_path(kernel=kernel, component="semantic_kernel", operation=operation,
                             semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                             path="RUST_NATIVE", caller=caller)
        return result


class NativeFormula:
    def __init__(self, context: NativeContext, handle: int): self.context, self._handle = context, handle
    def close(self) -> None:
        if self._handle: self.context.library._lib.ft_formula_free(self._handle); self._handle = None
    def __enter__(self) -> "NativeFormula": return self
    def __exit__(self, *_: object) -> None: self.close()
    def __del__(self) -> None: self.close()
    def verify(self) -> "NativeResult":
        handle = self.context.library._lib.ft_verify(self.context._handle, self._handle)
        if not handle:
            reason = self.context.error() or "ft_verify failed"
            record_semantic_path(kernel="F", component="verification_result", operation="VERIFY",
                                 semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                                 path="UNRESOLVED", fallback_reason=reason, caller=inferred_caller(2))
            raise NativeCallError(reason)
        record_semantic_path(kernel="F", component="verification_result", operation="VERIFY",
                             semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                             path="RUST_NATIVE", caller=inferred_caller(2))
        return NativeResult(self.context, handle)
    def verify_against(self, implementation: "NativeFormula") -> "NativeResult":
        handle = self.context.library._lib.ft_verify_pair(self.context._handle, self._handle, implementation._handle)
        if not handle:
            reason = self.context.error() or "ft_verify_pair failed"
            record_semantic_path(kernel="F", component="verification_result", operation="VERIFY_PAIR",
                                 semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                                 path="UNRESOLVED", fallback_reason=reason, caller=inferred_caller(2))
            raise NativeCallError(reason)
        record_semantic_path(kernel="F", component="verification_result", operation="VERIFY_PAIR",
                             semantic_owner="RUST_CORE", execution_backend="STABLE_C_ABI_V1",
                             path="RUST_NATIVE", caller=inferred_caller(2))
        return NativeResult(self.context, handle)


class NativeRelation(str):
    @property
    def kind(self) -> str: return str(self)


class NativeEvidence(tuple):
    @property
    def kernel_verified(self) -> bool:
        return bool(self) and all(isinstance(item, dict) and item.get("kernel_verified") is True for item in self)


@dataclass(frozen=True)
class NativeSemanticObjectValue:
    ir: dict[str, Any]
    semantic_hash: str | None
    tex: str
    assumptions: tuple[str, ...] = ()
    evidence: NativeEvidence = NativeEvidence()
    provenance: Any = None

    def to_tex(self) -> str: return self.tex
    def to_dict(self) -> dict[str, Any]:
        return {"ir": self.ir, "semantic_hash": self.semantic_hash, "tex": self.tex}
    def as_function(self) -> "NativeMathematicalFunction":
        return NativeMathematicalFunction.from_ir(
            self.ir,
            assumptions=self.assumptions,
            evidence=self.evidence,
            provenance=self.provenance,
        )


class NativeMathematicalFunction:
    """Owned native function handle; all mathematical evaluation stays in Rust."""

    def __init__(self, context: NativeContext, handle: int):
        if not handle:
            raise NativeCallError(context.error() or "native function is null")
        self.context, self._handle = context, handle

    @classmethod
    def from_ir(cls, ir: dict[str, Any], *, assumptions=(), evidence=(), provenance=None):
        context = NativeContext()
        metadata = {"assumptions": list(assumptions), "evidence": list(evidence), "provenance": provenance}
        handle = context.library._lib.ft_function_from_ir_json(
            context._handle,
            json.dumps(ir, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )
        if not handle:
            error = context.error(); context.close()
            raise NativeCallError(error or "ft_function_from_ir_json failed")
        return cls(context, handle)

    @classmethod
    def from_schema(cls, schema: dict[str, Any]):
        context = NativeContext()
        handle = context.library._lib.ft_function_from_json(
            context._handle,
            json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if not handle:
            error = context.error(); context.close()
            raise NativeCallError(error or "ft_function_from_json failed")
        return cls(context, handle)

    def close(self) -> None:
        if self._handle:
            self.context.library._lib.ft_function_free(self._handle); self._handle = None
        self.context.close()

    def __enter__(self): return self
    def __exit__(self, *_: object) -> None: self.close()
    def __del__(self) -> None: self.close()

    def _json_call(self, name: str, values: dict[str, Any] | None = None) -> Any:
        function = getattr(self.context.library._lib, name)
        if values is None:
            pointer = function(self._handle)
        else:
            converted = {key: _portable_value(value) for key, value in values.items()}
            pointer = function(self.context._handle, self._handle,
                               json.dumps(converted, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if not pointer:
            raise NativeCallError(self.context.error() or f"{name} failed")
        return json.loads(self.context.library.take_string(pointer))

    def evaluate(self, **values: Any) -> Any:
        return self._json_call("ft_function_evaluate_json", values)

    def __call__(self, **values: Any) -> Any: return self.evaluate(**values)

    def substitute(self, **values: Any) -> "NativeMathematicalFunction":
        converted = {key: _portable_value(value) for key, value in values.items()}
        handle = self.context.library._lib.ft_function_substitute_json(
            self.context._handle, self._handle,
            json.dumps(converted, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if not handle: raise NativeCallError(self.context.error() or "ft_function_substitute_json failed")
        # A substituted handle shares the same loaded library but owns an independent context.
        schema = json.loads(self.context.library.take_string(self.context.library._lib.ft_function_to_json(handle)))
        self.context.library._lib.ft_function_free(handle)
        return NativeMathematicalFunction.from_schema(schema)

    def to_tex(self) -> str:
        return self.context.library.take_string(self.context.library._lib.ft_function_to_tex(self._handle))

    def to_schema(self) -> dict[str, Any]: return self._json_call("ft_function_to_json")
    def to_dict(self) -> dict[str, Any]: return self.to_schema()
    def inspect(self) -> dict[str, Any]: return self._json_call("ft_function_inspect_json")

    def to_callable(self, backend: str = "python"):
        if backend not in {"python", "numpy"}:
            raise NativeCallError(f"UNSUPPORTED backend: {backend}")
        if backend == "python":
            return lambda **values: self.evaluate(**values)
        try:
            import numpy as np
        except ImportError as exc:
            raise NativeCallError("NumPy backend requested but numpy is not installed") from exc
        return lambda **values: np.asarray(self.evaluate(**values))


def _portable_value(value: Any) -> Any:
    """Binding-only conversion; this deliberately performs no mathematical operation."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (str, int, float, bool, list, tuple, dict)) or value is None:
        return value
    raise NativeCallError(f"unsupported input value type: {type(value).__name__}")


@dataclass(frozen=True)
class NativeFunctionalValue:
    raw: Any
    function_schema: dict[str, Any] | None = None

    def as_function(self) -> NativeMathematicalFunction:
        if self.function_schema is None:
            raise NativeCallError("BOUND_NOT_AVAILABLE: no certified symbolic function")
        return NativeMathematicalFunction.from_schema(self.function_schema)


@dataclass(frozen=True)
class NativeRangeValue:
    raw: Any
    lower: NativeFunctionalValue
    upper: NativeFunctionalValue


@dataclass(frozen=True)
class NativeResultValue:
    status: str
    theory: NativeSemanticObjectValue | None
    implementation: NativeSemanticObjectValue | None
    relation: NativeRelation
    assumptions: tuple[str, ...]
    diagnostics: tuple[str, ...]
    evidence: NativeEvidence
    error: NativeFunctionalValue | None
    range: NativeRangeValue | None
    provenance: Any
    debugger: Any
    reconstruction: Any
    tex: str
    certificate_tex: str
    raw: dict[str, Any]

    def to_tex(self) -> str: return self.certificate_tex
    def to_dict(self) -> dict[str, Any]: return dict(self.raw)
    def to_json(self) -> str: return json.dumps(self.raw, ensure_ascii=False, sort_keys=True)
    def explain(self, language: str = "en") -> str:
        if language.lower().startswith("ja"):
            return f"検証状態: {self.status} / 関係: {self.relation.kind}"
        return f"Verification status: {self.status}; relation: {self.relation.kind}"


class NativeResult:
    def __init__(self, context: NativeContext, handle: int):
        if not handle: raise NativeCallError("native result is null")
        self.context, self._handle = context, handle
    def close(self) -> None:
        if self._handle: self.context.library._lib.ft_result_free(self._handle); self._handle = None
    def __enter__(self) -> "NativeResult": return self
    def __exit__(self, *_: object) -> None: self.close()
    def __del__(self) -> None: self.close()
    def to_json(self) -> dict[str, Any]: return json.loads(self.context.library.take_string(self.context.library._lib.ft_result_to_json(self._handle)))
    def to_tex(self) -> str: return self.context.library.take_string(self.context.library._lib.ft_result_to_tex(self._handle))
    def to_audit_bundle(self, *, source_context=None, environment=None, artifact_lineage=None) -> dict[str, Any]:
        encode = lambda value: json.dumps(value or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        pointer = self.context.library._lib.ft_result_to_audit_bundle_json(
            self.context._handle, self._handle, encode(source_context), encode(environment),
            encode(artifact_lineage))
        if not pointer:
            raise NativeCallError(self.context.error() or "ft_result_to_audit_bundle_json failed")
        return json.loads(self.context.library.take_string(pointer))
    def _semantic_value(self, accessor: str) -> NativeSemanticObjectValue | None:
        library = self.context.library
        handle = getattr(library._lib, accessor)(self._handle)
        if not handle:
            return None
        try:
            raw = json.loads(library.take_string(library._lib.ft_semantic_object_to_json(handle)))
            tex = library.take_string(library._lib.ft_semantic_object_to_tex(handle))
            result = self.to_json()
            return NativeSemanticObjectValue(
                raw["ir"], raw.get("semantic_hash"), tex,
                tuple(result.get("assumptions", [])), NativeEvidence(result.get("evidence", [])),
                result.get("provenance"),
            )
        finally:
            library._lib.ft_semantic_object_free(handle)
    def _function_schema(self, accessor: str) -> dict[str, Any] | None:
        library = self.context.library
        handle = getattr(library._lib, accessor)(self._handle)
        if not handle:
            return None
        try:
            return json.loads(library.take_string(library._lib.ft_function_to_json(handle)))
        finally:
            library._lib.ft_function_free(handle)
    @property
    def value(self) -> NativeResultValue:
        raw = self.to_json()
        error = None if raw.get("error") is None else NativeFunctionalValue(
            raw["error"], self._function_schema("ft_result_error_function"))
        range_value = None if raw.get("range") is None else NativeRangeValue(
            raw["range"],
            NativeFunctionalValue(raw["range"].get("lower") if isinstance(raw["range"], dict) else None,
                                  self._function_schema("ft_result_range_lower_function")),
            NativeFunctionalValue(raw["range"].get("upper") if isinstance(raw["range"], dict) else None,
                                  self._function_schema("ft_result_range_upper_function")),
        )
        return NativeResultValue(raw["status"], self._semantic_value("ft_result_theory"),
                                 self._semantic_value("ft_result_implementation"), NativeRelation(raw["relation"]),
                                 tuple(raw.get("assumptions", [])), tuple(raw.get("diagnostics", [])),
                                 NativeEvidence(raw.get("evidence", [])), error, range_value,
                                 raw.get("provenance"), raw.get("debugger"), raw.get("reconstruction"),
                                 raw.get("tex", ""), self.to_tex(), raw)


def native_available() -> bool:
    try: NativeLibrary(); return True
    except (NativeUnavailableError, OSError): return False


def execute_native_kernel(request: dict[str, Any]) -> dict[str, Any]:
    """Thin binding to the versioned native semantic-kernel request boundary."""
    with NativeContext() as context:
        return context.execute_kernel(request)


def compare_ir(theory: dict[str, Any], implementation: dict[str, Any]) -> NativeResultValue:
    with NativeContext() as context, context.formula_from_json(theory) as expected, context.formula_from_json(implementation) as actual, expected.verify_against(actual) as result:
        return result.value
