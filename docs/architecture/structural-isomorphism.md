# Typed structural isomorphism and quotient normalization

FormulaTracer uses a Rust-owned structural comparison aid to place expressions
into correspondence before the ordinary verification pipeline. It is designed
to recognize representation differences without weakening mathematical
soundness.

The pipeline is:

```text
raw Mathematical IR
  -> fact-gated quotient normalization
  -> typed structural correspondence
  -> explicit witness
  -> ordinary canonical/e-graph/relation/Lean verification
```

Structural correspondence is never proof. Its result always has
`proof_authority = false` and `establishes_mathematical_equality = false`.
Similarity or isomorphism only authorizes a later comparison; it cannot produce
`EXACT_EQUALITY`, `KERNEL_VERIFIED`, or certified error evidence.

## Preserved and ignored information

The normalizer may ignore representation provenance such as source spans,
node IDs, temporary IDs, and numeral spelling. Every ignored field is recorded
in the witness and can be stored in an `AuditBundle`.

It does not ignore operators, constants, bounds, axes, index positions, branch
ordering, dtype, shape, named dimensions, units, bit width, signedness, or
overflow representation. A difference in these fields blocks structural
isomorphism or leaves it unresolved.

Free-symbol renaming requires either equal type facts or an explicit symbol
mapping. Bound-variable alpha renaming is scope-sensitive. Commutativity and
associativity are applied only when the caller supplies the corresponding
operator facts; no operator is treated as commutative merely because its name
looks algebraic.

## Witness

The machine-readable witness records symbol, binder, index and node mappings;
operand permutations; association changes; ignored representation metadata;
required facts and assumptions; blocked reasons; provenance; and evidence
level. The witness is presentation-neutral and is returned through the native
kernel, the thin Python facade, and the native `AuditBundle`.

## Current boundary

Native v1 supports typed symbol correspondence, alpha-equivalent binders,
representation-metadata quotienting, and fact-gated associative/commutative
normalization. Temporary inline/uninline correspondence, loop-to-Fold/reduction
lifting, and production provider-reconstruction integration remain incomplete.
The completion gate therefore remains false even though the implemented
negative mutation assurance reports no collapsed semantic mutations.

External reconstruction artifacts now retain the Theory quotient and reserve
the reconstructed quotient/witness fields. Where no reconstructed IR exists,
those fields are null with an explicit reason; the Theory expression is never
substituted as a fake implementation. This permits the next phase to apply the
same native engine without re-harvesting external references.

Run `tools/run_structural_isomorphism_assurance.py` to regenerate the focused
positive/negative report under `output/structural_isomorphism/`.
