# Numeric execution types and Mathematical Domains

Phase 2 adds a conservative dtype pass beside Mathematical Expression IR. It
does **not** reinterpret a `float32` calculation as the mathematical object
`float32`: the formula remains over `Real`, `Integer`, `Natural`, `Boolean`, or
`Complex`, while `numeric_type_semantics` records how Python or a scientific
library executes it.

Use the standalone pass with caller-supplied values and, when known, explicit
dtype contracts:

```console
cpp-audit python-dtypes calculation.py --function calculate --output result \
  --inputs inputs.json --input-dtypes input-dtypes.json
```

The dtype file maps a parameter to either a dtype name or a structured
contract. Structured contracts can preserve an xarray container and dimensions:

```json
{
  "temperature": {
    "dtype": "float32",
    "container": "xarray.DataArray",
    "shape": [365, 180, 360],
    "dimensions": ["time", "lat", "lon"]
  },
  "weights": "float64"
}
```

`python-certificate` accepts the same `--input-dtypes` option. Values and dtype
contracts are separate inputs: values drive restricted execution; contracts
drive representation analysis. A contract is never inferred from a requested
mathematical result.

## Model

`NumericExecutionType` contains dtype, kind, width, signedness, container,
shape, xarray dimension names, Mathematical Domain, and explicit overflow and
underflow semantics. `NumericCast` records constructor and `astype` casts.
`PromotionRule` records both operands, result, operator, and the selected rule.

Supported concrete dtypes are `bool`, signed and unsigned 8/16/32/64-bit
integers, `float16`, `float32`, `float64`, `complex64`, and `complex128`, plus
Python `int`, `float`, and `complex`. Python integer arithmetic is marked
unbounded. Fixed-width integer arithmetic is marked modular. Binary floating
types record infinity overflow and gradual-subnormal underflow as their base
execution contract; later IEEE-754 phases will model individual operations and
platform modes in greater detail.

The promotion pass covers Python's numeric tower, weak Python scalars beside a
concrete scientific dtype, Boolean promotion, same-signed integer widening,
safe signed/unsigned widening, floating widening, and complex widening. True
division and integer `mean` have explicit result rules. NumPy/xarray/Dask array
construction, `astype`, reductions, elementary functions, selection, shape
transforms, and alignment-preserving xarray operations carry the inferred dtype.

An unsupported call or promotion produces `TYPE_UNRESOLVED` with a source span.
`STRICT` certificates fail closed. `REPORT_ONLY` still emits JSON and LaTeX and
retains the diagnostic. No platform-dependent `long`, user-defined dtype,
datetime/timedelta, object dtype, structured dtype, quantized type, device
autocast, or low-level BLAS accumulator rule is claimed in this phase.

## Lean boundary

`CppAudit.Semantics.NumericDomain` proves only representation-independent
claims: Boolean embedding, mathematical integer operations, exact signed
machine conversion under an explicit range hypothesis, and the fact that dtype
metadata does not rewrite the mathematical value. It intentionally does not
claim that fixed-width or floating execution equals exact arithmetic.
