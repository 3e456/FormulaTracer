# Proof levels

`SEMANTICALLY_VERIFIED` requires a checked Lean refinement with no unresolved
result-affecting entity. `VERIFIED_WITH_CONTRACT_ASSUMPTIONS` additionally lists
external representation, memory, or library contracts. Structural and
type/shape levels make weaker claims. Numerical validation reports only runtime
evidence. `UNRESOLVED`, `UNSUPPORTED`, and `FAILED` are never successes.

The weighted-sum slice is currently verified only at the abstract rational/real
structure level with memory contracts. No equivalence between AbstractReal and
IEEE-754 is assumed.

