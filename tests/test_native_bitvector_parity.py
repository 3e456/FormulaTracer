from __future__ import annotations

from cpp_audit.bitvector import (
    BitRepresentation,
    ShiftSemantics,
    _reference_decode_bits,
    _reference_encode_bits,
    _reference_evaluate_bit_operation,
    _reference_recognize_bit_field_extract,
    _reference_representation_for_dtype,
    decode_bits,
    encode_bits,
    evaluate_bit_operation,
    recognize_bit_field_extract,
    representation_for_dtype,
)


def test_native_dtype_representation_matches_reference() -> None:
    for dtype in ("uint8", "int16", "std::uint32", "numpy.int64", "python.int", "unknown"):
        native = representation_for_dtype(dtype, language="python")
        reference = _reference_representation_for_dtype(dtype, language="python")
        assert (native.to_dict() if native else None) == (reference.to_dict() if reference else None)


def test_native_encode_decode_and_operations_match_reference() -> None:
    representations = (
        BitRepresentation.unsigned(8),
        BitRepresentation.signed_twos_complement(8),
        BitRepresentation.python_int(),
    )
    for representation in representations:
        if representation.width is not None:
            values = (0, 1, 42, 127) if "UNSIGNED" in representation.signedness.value else (-128, -2, 0, 127)
            for value in values:
                assert encode_bits(value, representation) == _reference_encode_bits(value, representation)
                encoded = _reference_encode_bits(value, representation)
                assert decode_bits(encoded, representation) == _reference_decode_bits(encoded, representation)
        right_shift_value = 254 if representation.signedness.value == "UNSIGNED" else -2
        for op, args, shift in (
            ("BitAnd", (42, 15), None),
            ("BitOr", (42, 15), None),
            ("BitXor", (42, 15), None),
            ("BitNot", (0,), None),
            ("ShiftLeft", (1, 2), None),
            ("ShiftRight", (right_shift_value, 1), ShiftSemantics.ARITHMETIC_RIGHT),
        ):
            assert evaluate_bit_operation(op, args, representation, shift_semantics=shift) == (
                _reference_evaluate_bit_operation(op, args, representation, shift_semantics=shift)
            )


def test_native_bit_field_recognition_matches_reference() -> None:
    representation = BitRepresentation.unsigned(32).to_dict()
    shifted = {"op": "ShiftRight", "args": [
        {"op": "FreeVariable", "name": "x"}, {"op": "Constant", "value": 8}],
        "bit_representation": representation}
    for mask in (0, 0x0F, 0xFF, 250):
        node = {"op": "BitAnd", "args": [shifted, {"op": "Constant", "value": mask}],
                "bit_representation": representation}
        assert recognize_bit_field_extract(node) == _reference_recognize_bit_field_extract(node)
