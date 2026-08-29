# Python numeric-script audit MVP

The Python frontend statically parses source with `ast`; it never imports or
executes the audited module. Starting at the named output (or the decorated
function's return), it performs a conservative name-level backward slice,
inlines simple assignments and local function calls, and lowers only required
numeric dependencies into the shared Mathematical Expression IR.

## Theory independence

Register a human theory with `@cpp_audit.theory(output=..., expression=...)`.
The expression DSL currently accepts scalar/indexed arithmetic and
`sum(i=0..N-1, body)` / `prod(i=0..N-1, body)`. Decorator text is not passed to
the AST extractor. It is parsed only after implementation extraction, then a
bijective symbol/alpha mapping and expression-graph isomorphism are sought.

## Supported Python syntax

Numeric constants, names, `+ - * / **`, unary signs, comparisons, boolean
conditions, conditional expressions, `if/else`, `for range(...)`, local calls,
subscripts, multidimensional indices, slices, and `return` are supported.
Loops cover direct accumulators and simple indexed maps; general CFG merges,
exceptions, generators, mutation through aliases, and `while` remain outside
this MVP.

## Supported numeric APIs

NumPy: `sum`, `prod`, `mean`, `dot`, `matmul`, `einsum`, `where`, `clip`, `abs`,
`sqrt`, `log`, `exp`, `power`, `reshape`, `transpose`, `diff`, and `gradient`.

xarray: `DataArray`, `sum`, `mean`, `where`, `sel`, `isel`, `transpose`,
`rename`, and `broadcast`. Dimension names, label arguments, coordinates, and
alignment obligations are retained in IR metadata. They are not silently
converted to positional NumPy semantics.

Known library calls are now resolved through the reference-first Library
Contract Registry before source analysis. See `library-contracts.md` for
version selection, semantic families, Dask execution metadata, random-sample
equivalence scopes, and inventory candidate generation.

Unrecognised external calls become `OpaqueNumericCall` nodes. Their arguments
remain auditable, an `opaque_result_shape` constraint is recorded, and the
six-stage resolution trace explains why fallback stopped. A local function—or
an explicitly imported adjacent local `.py` function—is instead entered
recursively; recursion is conservatively opaque.
Shape information is always represented as a constraint (reduction axes,
broadcast rank, contraction compatibility, index extent, xarray alignment),
never as a fabricated concrete extent.

## Lean boundary and modes

Lean receives only the two extracted symbolic expressions. Python types,
dtypes, ndarray implementations, and xarray objects are not encoded. The
certificate contains the source SHA-256, symbol mapping, separate Lean
definitions translated from implementation/theory IR, and a theorem checked by
the Lean kernel. The MVP verifies alpha rename, graph identity, finite Map/sum
normalization, and commutative integer addition/multiplication. It does not prove
floating-point rounding or xarray runtime contracts.

`STRICT` fails on missing/mismatched theory or unavailable/failed Lean
verification. `REPORT_ONLY` always completes an artifact for opaque calls,
mismatches, or missing Lean, using diagnostics and `PASS_WITH_FINDINGS`.

The report offers Unicode equations; the JSON result also embeds LaTeX,
Markdown, Unicode, and JSON renderings, the exact backward slice, constraints,
comparison mapping, and Lean result.
