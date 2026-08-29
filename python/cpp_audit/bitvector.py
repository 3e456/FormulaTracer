"""Integer numeral provenance and width-aware bit-vector semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class Signedness(str, Enum):
    UNSIGNED = "UNSIGNED"
    SIGNED = "SIGNED"
    UNBOUNDED = "UNBOUNDED"
    UNRESOLVED = "UNRESOLVED"


class BitEncoding(str, Enum):
    TWOS_COMPLEMENT = "TWOS_COMPLEMENT"
    UNSIGNED_BINARY = "UNSIGNED_BINARY"
    PYTHON_INFINITE_TWOS_COMPLEMENT = "PYTHON_INFINITE_TWOS_COMPLEMENT"
    UNRESOLVED = "UNRESOLVED"


class OverflowSemantics(str, Enum):
    MODULAR_WRAP = "MODULAR_WRAP"
    CHECKED = "CHECKED"
    SATURATING = "SATURATING"
    UNBOUNDED = "UNBOUNDED"
    LANGUAGE_UNRESOLVED = "LANGUAGE_UNRESOLVED"


class ShiftSemantics(str, Enum):
    LOGICAL_LEFT = "LOGICAL_LEFT"
    LOGICAL_RIGHT = "LOGICAL_RIGHT"
    ARITHMETIC_RIGHT = "ARITHMETIC_RIGHT"
    ROTATE_LEFT = "ROTATE_LEFT"
    ROTATE_RIGHT = "ROTATE_RIGHT"
    LANGUAGE_DEPENDENT = "LANGUAGE_DEPENDENT"


@dataclass(frozen=True)
class NumeralRepresentation:
    value: int
    radix: int = 10
    original_text: str | None = None

    def __post_init__(self) -> None:
        if self.radix not in {2, 8, 10, 16}:
            raise ValueError("UNSUPPORTED_NUMERAL_RADIX")


@dataclass(frozen=True)
class BitRepresentation:
    width: int | None
    signedness: Signedness
    encoding: BitEncoding
    overflow: OverflowSemantics
    language: str
    dtype: str | None = None
    evidence: str = "DECLARED"

    def __post_init__(self) -> None:
        if self.width is not None and self.width <= 0:
            raise ValueError("BIT_WIDTH_MUST_BE_POSITIVE")
        if self.signedness == Signedness.UNBOUNDED:
            if self.width is not None or self.encoding != BitEncoding.PYTHON_INFINITE_TWOS_COMPLEMENT:
                raise ValueError("UNBOUNDED_BIT_REPRESENTATION_INCONSISTENT")
        elif self.signedness == Signedness.UNRESOLVED:
            if self.width is not None or self.encoding != BitEncoding.UNRESOLVED:
                raise ValueError("UNRESOLVED_BIT_REPRESENTATION_INCONSISTENT")
        elif self.width is None:
            raise ValueError("FIXED_BIT_REPRESENTATION_REQUIRES_WIDTH")

    @classmethod
    def python_int(cls) -> "BitRepresentation":
        return cls(None, Signedness.UNBOUNDED, BitEncoding.PYTHON_INFINITE_TWOS_COMPLEMENT,
                   OverflowSemantics.UNBOUNDED, "python", "python.int", "LANGUAGE_SPEC")

    @classmethod
    def unresolved(cls, *, language: str, evidence: str = "TYPE_UNRESOLVED") -> "BitRepresentation":
        return cls(None, Signedness.UNRESOLVED, BitEncoding.UNRESOLVED,
                   OverflowSemantics.LANGUAGE_UNRESOLVED, language, None, evidence)

    @classmethod
    def unsigned(cls, width: int, *, language: str = "mathematical",
                 dtype: str | None = None) -> "BitRepresentation":
        return cls(width, Signedness.UNSIGNED, BitEncoding.UNSIGNED_BINARY,
                   OverflowSemantics.MODULAR_WRAP, language, dtype, "TYPE_CONTRACT")

    @classmethod
    def signed_twos_complement(cls, width: int, *, language: str = "mathematical",
                               dtype: str | None = None,
                               overflow: OverflowSemantics = OverflowSemantics.LANGUAGE_UNRESOLVED) -> "BitRepresentation":
        return cls(width, Signedness.SIGNED, BitEncoding.TWOS_COMPLEMENT, overflow,
                   language, dtype, "TYPE_CONTRACT")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["signedness"] = self.signedness.value
        value["encoding"] = self.encoding.value
        value["overflow"] = self.overflow.value
        return value


def _reference_representation_for_dtype(dtype: str, *, language: str = "unknown") -> BitRepresentation | None:
    normalized = dtype.lower().replace("std::", "").replace("numpy.", "")
    aliases = {"byte": (8, True), "ubyte": (8, False), "char": (8, True),
               "uchar": (8, False), "short": (16, True), "ushort": (16, False),
               "int": (32, True), "uint": (32, False), "long": (64, True), "ulong": (64, False)}
    for prefix in ("uint", "u"):
        if normalized.startswith(prefix) and normalized[len(prefix):].isdigit():
            return BitRepresentation.unsigned(int(normalized[len(prefix):]), language=language, dtype=dtype)
    for prefix in ("int", "i"):
        if normalized.startswith(prefix) and normalized[len(prefix):].isdigit():
            return BitRepresentation.signed_twos_complement(int(normalized[len(prefix):]), language=language, dtype=dtype)
    if normalized in aliases:
        width, signed = aliases[normalized]
        return (BitRepresentation.signed_twos_complement(width, language=language, dtype=dtype)
                if signed else BitRepresentation.unsigned(width, language=language, dtype=dtype))
    if normalized in {"python.int", "pyint"}:
        return BitRepresentation.python_int()
    return None


def representation_for_dtype(dtype: str, *, language: str = "unknown") -> BitRepresentation | None:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        value = context.execute_kernel({"schema_version": "1.0", "kernel": "A",
            "operation": "BITVECTOR", "action": "REPRESENTATION_FOR_DTYPE",
            "dtype": dtype, "language": language})["result"]["value"]
    return representation_from_dict(value) if value is not None else None


def representation_from_dict(value: dict[str, Any]) -> BitRepresentation:
    return BitRepresentation(value.get("width"), Signedness(value["signedness"]),
        BitEncoding(value["encoding"]), OverflowSemantics(value["overflow"]),
        value.get("language", "unknown"), value.get("dtype"), value.get("evidence", "DECLARED"))


def _reference_encode_bits(value: int, representation: BitRepresentation) -> int:
    """Return the non-negative integer encoding of a bit vector."""
    if representation.width is None:
        if representation.signedness == Signedness.UNRESOLVED:
            raise ValueError("BIT_REPRESENTATION_UNRESOLVED")
        raise ValueError("UNBOUNDED_INTEGER_HAS_NO_FINITE_BITVECTOR_ENCODING")
    modulus = 1 << representation.width
    if representation.signedness == Signedness.UNSIGNED and value < 0:
        raise ValueError("NEGATIVE_VALUE_CANNOT_ENCODE_AS_UNSIGNED_WITHOUT_CAST")
    if representation.overflow == OverflowSemantics.CHECKED:
        lower = -(1 << (representation.width - 1)) if representation.signedness == Signedness.SIGNED else 0
        upper = (1 << (representation.width - 1)) - 1 if representation.signedness == Signedness.SIGNED else modulus - 1
        if not lower <= value <= upper:
            raise OverflowError("BIT_ENCODING_OUT_OF_RANGE")
    return value % modulus


def _reference_decode_bits(bits: int, representation: BitRepresentation) -> int:
    if representation.width is None:
        if representation.signedness == Signedness.UNRESOLVED:
            raise ValueError("BIT_REPRESENTATION_UNRESOLVED")
        raise ValueError("UNBOUNDED_INTEGER_HAS_NO_FINITE_BITVECTOR_DECODING")
    modulus = 1 << representation.width
    bits %= modulus
    if representation.signedness == Signedness.SIGNED and bits >= (1 << (representation.width - 1)):
        return bits - modulus
    return bits


def _reference_bit_mask(representation: BitRepresentation) -> int:
    if representation.width is None:
        raise ValueError("UNBOUNDED_INTEGER_HAS_NO_FINITE_MASK")
    return (1 << representation.width) - 1


def _reference_evaluate_bit_operation(op: str, values: Iterable[int], representation: BitRepresentation,
                                      *, shift_semantics: ShiftSemantics | None = None) -> int:
    args = list(values)
    if op in {"BitAnd", "BitOr", "BitXor"} and len(args) != 2:
        raise ValueError("BIT_BINARY_ARITY")
    if op in {"BitNot"} and len(args) != 1:
        raise ValueError("BIT_UNARY_ARITY")
    if op in {"ShiftLeft", "ShiftRight", "RotateLeft", "RotateRight"}:
        if len(args) != 2: raise ValueError("BIT_SHIFT_ARITY")
        if args[1] < 0: raise ValueError("NEGATIVE_SHIFT_COUNT")
    if representation.width is None:
        if representation.signedness == Signedness.UNRESOLVED:
            raise ValueError("BIT_REPRESENTATION_UNRESOLVED")
        if op == "BitAnd": return args[0] & args[1]
        if op == "BitOr": return args[0] | args[1]
        if op == "BitXor": return args[0] ^ args[1]
        if op == "BitNot": return ~args[0]
        if op == "ShiftLeft": return args[0] << args[1]
        if op == "ShiftRight": return args[0] >> args[1]
        raise ValueError("ROTATE_REQUIRES_FIXED_BIT_WIDTH")
    encoded = [_reference_encode_bits(value, representation) for value in args]
    mask = _reference_bit_mask(representation); width = int(representation.width)
    if op in {"ShiftLeft", "ShiftRight"} and args[1] >= width:
        raise ValueError("SHIFT_COUNT_OUT_OF_RANGE")
    if op == "BitAnd": result = encoded[0] & encoded[1]
    elif op == "BitOr": result = encoded[0] | encoded[1]
    elif op == "BitXor": result = encoded[0] ^ encoded[1]
    elif op == "BitNot": result = (~encoded[0]) & mask
    elif op == "ShiftLeft": result = (encoded[0] << encoded[1]) & mask
    elif op == "ShiftRight":
        kind = shift_semantics or (ShiftSemantics.ARITHMETIC_RIGHT if representation.signedness == Signedness.SIGNED
                                   else ShiftSemantics.LOGICAL_RIGHT)
        if kind == ShiftSemantics.ARITHMETIC_RIGHT:
            result = _reference_encode_bits(_reference_decode_bits(encoded[0], representation) >> encoded[1], representation)
        elif kind == ShiftSemantics.LOGICAL_RIGHT: result = encoded[0] >> encoded[1]
        else: raise ValueError("INVALID_RIGHT_SHIFT_SEMANTICS")
    elif op in {"RotateLeft", "RotateRight"}:
        amount = encoded[1] % width
        if op == "RotateLeft": result = ((encoded[0] << amount) | (encoded[0] >> (width - amount))) & mask
        else: result = ((encoded[0] >> amount) | (encoded[0] << (width - amount))) & mask
    else: raise ValueError(f"UNSUPPORTED_BIT_OPERATION:{op}")
    return _reference_decode_bits(result, representation)


def _native_bitvector(action: str, representation: BitRepresentation, **values: Any) -> int:
    from formulatracer.native import NativeContext
    request = {"schema_version": "1.0", "kernel": "A", "operation": "BITVECTOR",
               "action": action, "representation": representation.to_dict(), **values}
    try:
        with NativeContext() as context:
            return int(context.execute_kernel(request)["result"]["value"])
    except RuntimeError as exc:
        message = str(exc)
        if "BIT_ENCODING_OUT_OF_RANGE" in message:
            raise OverflowError("BIT_ENCODING_OUT_OF_RANGE") from exc
        raise ValueError(message) from exc


def encode_bits(value: int, representation: BitRepresentation) -> int:
    return _native_bitvector("ENCODE", representation, value=value)


def decode_bits(bits: int, representation: BitRepresentation) -> int:
    return _native_bitvector("DECODE", representation, value=bits)


def bit_mask(representation: BitRepresentation) -> int:
    return _native_bitvector("MASK", representation)


def evaluate_bit_operation(op: str, values: Iterable[int], representation: BitRepresentation,
                           *, shift_semantics: ShiftSemantics | None = None) -> int:
    return _native_bitvector("EVALUATE", representation, op=op, values=list(values),
        shift_semantics=shift_semantics.value if shift_semantics is not None else None)


def bit_ir(op: str, *args: dict[str, Any], representation: BitRepresentation,
           shift_semantics: ShiftSemantics | None = None,
           source_operator: str | None = None) -> dict[str, Any]:
    domain = ("BitVector" if representation.width is not None else
              "UnresolvedBitDomain" if representation.signedness == Signedness.UNRESOLVED else "UnboundedIntegerBits")
    result = {"op": op, "args": list(args), "bit_representation": representation.to_dict(),
              "semantic_domain": domain}
    if shift_semantics is not None: result["shift_semantics"] = shift_semantics.value
    if source_operator is not None: result["source_operator"] = source_operator
    return result


def bit_field_extract(value: dict[str, Any], *, offset: int, width: int,
                      representation: BitRepresentation) -> dict[str, Any]:
    if offset < 0 or width <= 0 or (representation.width is not None and offset + width > representation.width):
        raise ValueError("BIT_FIELD_OUT_OF_RANGE")
    return {"op": "BitFieldExtract", "value": value, "offset": offset, "width": width,
            "bit_representation": representation.to_dict(), "result_representation":
            BitRepresentation.unsigned(width, language=representation.language).to_dict()}


def bit_field_insert(base: dict[str, Any], field_value: dict[str, Any], *, offset: int, width: int,
                     representation: BitRepresentation) -> dict[str, Any]:
    if offset < 0 or width <= 0 or representation.width is None or offset + width > representation.width:
        raise ValueError("BIT_FIELD_OUT_OF_RANGE")
    return {"op": "BitFieldInsert", "base": base, "field_value": field_value, "offset": offset,
            "width": width, "bit_representation": representation.to_dict()}


def _reference_recognize_bit_field_extract(node: dict[str, Any]) -> dict[str, Any] | None:
    if node.get("op") != "BitAnd" or len(node.get("args", ())) != 2:
        return None
    shifted, mask_node = node["args"]
    if shifted.get("op") != "ShiftRight" or mask_node.get("op") != "Constant":
        return None
    mask = mask_node.get("value")
    if not isinstance(mask, int) or mask <= 0 or (mask & (mask + 1)) != 0:
        return None
    amount = shifted.get("args", [{}, {}])[1]
    if amount.get("op") != "Constant" or not isinstance(amount.get("value"), int):
        return None
    width = mask.bit_length()
    representation = node.get("bit_representation") or shifted.get("bit_representation")
    if not representation:
        return None
    return {"op": "BitFieldExtract", "value": shifted["args"][0], "offset": amount["value"],
            "width": width, "bit_representation": representation,
            "result_representation": BitRepresentation.unsigned(width).to_dict(),
            "recognized_from": "shift-and-mask"}


def recognize_bit_field_extract(node: dict[str, Any]) -> dict[str, Any] | None:
    from formulatracer.native import NativeContext
    with NativeContext() as context:
        return context.execute_kernel({"schema_version": "1.0", "kernel": "A",
            "operation": "BITVECTOR", "action": "RECOGNIZE_FIELD_EXTRACT", "node": node})["result"]["value"]


@dataclass
class BitAssuranceResult:
    width: int
    cases: int
    passed: int
    failed: int
    false_acceptance: int
    operations: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def run_exhaustive_bit_assurance(*, width: int = 8) -> BitAssuranceResult:
    """Exhaustively compare unsigned fixed-width IR semantics with host integers."""
    if not 1 <= width <= 8:
        raise ValueError("EXHAUSTIVE_ASSURANCE_WIDTH_MUST_BE_1_TO_8")
    rep = BitRepresentation.unsigned(width); modulus = 1 << width
    passed = failed = 0; counts: dict[str, int] = {}
    for op, host in (("BitAnd", lambda a, b: a & b), ("BitOr", lambda a, b: a | b),
                     ("BitXor", lambda a, b: a ^ b)):
        for left in range(modulus):
            for right in range(modulus):
                expected = host(left, right) % modulus
                observed = _reference_evaluate_bit_operation(op, (left, right), rep)
                passed += observed == expected; failed += observed != expected
        counts[op] = modulus * modulus
    for value in range(modulus):
        expected = (~value) % modulus
        observed = _reference_evaluate_bit_operation("BitNot", (value,), rep)
        passed += observed == expected; failed += observed != expected
    counts["BitNot"] = modulus
    cases = passed + failed
    return BitAssuranceResult(width, cases, passed, failed, failed, counts)
