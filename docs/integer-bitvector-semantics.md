# Integer, numeral, and bit-vector semantics

Numeral radix is presentation provenance. `42`, `0b101010`, `0o52`, and `0x2a`
share the canonical integer value while retaining original radix/text for audit
rendering.

Bit operations use an explicit representation:

```text
Integer -> EncodeBits(width, signedness, encoding) -> BitVector[w]
        -> BitAnd/BitOr/BitXor/BitNot/Shift/Rotate
        -> DecodeBits -> Integer
```

Fixed-width values retain width, signedness, two's-complement encoding, and
overflow semantics. Python's unbounded integer-bit semantics are distinct from
C++/Rust fixed-width integers. If the frontend cannot determine a required
representation, it records `UnresolvedBitDomain`; it never guesses a width.

Logical and bitwise operations are separate primitives. Right shift records
logical versus arithmetic semantics, and invalid fixed-width shift counts are
rejected. Shift/mask expressions can be recognized as `BitFieldExtract` only
when the mask is contiguous and the representation constraints are known.

Conditional arithmetic identities such as a low-bit mask versus modulo and a
left shift versus multiplication modulo `2^w` are registered as guarded
knowledge. They merge only after their width/domain facts are discharged.

The assurance suite exhaustively checks unsigned 8-bit AND, OR, XOR, and NOT:
196,864 source/evaluator comparisons with zero false acceptance.
