# Structured Result Model

FormulaTracer 0.1.1 returns a structured `VerificationResult`/`NativeResult`.
`to_tex()`, `to_json()`, `to_dict()`, and `explain()` are projections; none is
the canonical result by itself.

| Field | Meaning | Missing-information behavior |
|---|---|---|
| `status` | Overall exact, certified, empirical, failed, or unresolved state | Never upgraded by numeric similarity |
| `theory` | Independently registered theory, when present | `None` does not invalidate code-first reconstruction |
| `implementation` | Mathematics reconstructed from source/IR | Opaque operations remain explicit |
| `relation` | Exact or non-exact connection between objects | Unknown relation is `UNRESOLVED` |
| `assumptions` | Conditions used by conditional claims | Undischarged assumptions remain visible |
| `proof_obligations` | Evidence still required | Open obligations prevent stronger certification |
| `error`, `range` | Certified, symbolic, empirical, or unresolved bounds | Runtime estimates are not certificates |
| `evidence` | Claim authority and provenance | Evidence classes are not merged |
| `provenance`, `debugger` | Source/IR/rewrite trace and localization | Ambiguous origins do not claim one exact span |
| `reconstruction` | Detailed Formula→Code→Formula outcome | `CORRECTLY_UNRESOLVED` is fail-closed success |

`KERNEL_VERIFIED` is emitted only from accepted Lean evidence. `USER_DECLARED`,
provider references, structural witnesses, and runtime observations retain their
weaker authority.

