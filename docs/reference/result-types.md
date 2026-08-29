# Reading result types and status

[日本語](result-types.ja.md) | [API purpose and selection](api-purpose-guide.md) | [Detailed class and function usage](api-usage-guide.md)

A FormulaTracer result does not collapse everything into one `PASS/FAIL`. It keeps separate what was reconstructed, which relation holds, what supports the conclusion, and what remains unresolved.

## Fields to read first

| Field | Purpose |
|---|---|
| `status` | Overall semantic outcome of the audit, comparison, or reconstruction. |
| `theory` | Structured mathematics on the theory side of a comparison. |
| `implementation` | Structured mathematics obtained from source or Implementation IR. |
| `relation` | Exact, approximation, discretization, or another relation between theory and implementation. |
| `assumptions` | Conditions on which the conclusion depends. |
| `proof_obligations` | Conditions that still need to be discharged. |
| `diagnostics` | Reasons for a partial, unresolved, or divergent result. |
| `error` | A numerical error claim; no bound is invented when evidence is absent. |
| `range` | Value-range or enclosure claims whose evidence must be inspected separately. |
| `evidence` | The kind and strength of support for the conclusion. |
| `provenance` | Origin of source, provider contracts, user declarations, and evidence. |
| `debugger` | Information for tracing a semantic result back to source. |
| `reconstruction` | Reconstruction details, relation chains, and unresolved reasons. |

Prefer the reference for the concrete result type when a field is not present on every result object.

## Do not treat `status` alone as verification

`status` matters, but it does not identify the evidence class. Even when semantic equality holds, inspect separately whether the result has:

- implementation-derived evidence;
- official or reference-backed evidence;
- only a user declaration;
- Lean kernel evidence; or
- only a runtime observation.

Read `status` and `evidence` together.

## Project-level and output-level results

`ProjectAuditResult.status` is distinct from the status of each output.

```text
ProjectAuditResult
├─ output A: FULLY_VERIFIED
├─ output B: FULLY_VERIFIED
└─ output C: UNRESOLVED

→ the project may be PROJECT_UNRESOLVED because of output C
```

Do not infer that every output has the project-level status.

## `relation`

`relation` describes a mathematical relationship, not superficial similarity. Representative families include:

- exact equality;
- approximation;
- discretization;
- truncation;
- sampling; and
- algorithmic realization.

FormulaTracer does not merge a non-exact relation into Exact E-Graph equality.

## `evidence`

Evidence classes conceptually distinguish:

- reconstruction from implementation;
- official or reference-backed evidence;
- provider-contract evidence;
- runtime observations;
- user declarations;
- structural correspondence;
- Lean kernel-verified evidence; and
- unresolved or insufficient evidence.

**`USER_DECLARED` is not `LEAN_KERNEL_VERIFIED`.** Runtime agreement alone is not mathematical equality over all inputs.

## `assumptions` and `proof_obligations`

Conditional conclusions retain their conditions, such as:

- a denominator being nonzero;
- domain requirements;
- regularity required by a theorem; or
- provider-realization preconditions.

An unresolved obligation is not promoted to unconditional verification.

## `error` and `range`

Interpret an error or range claim together with its evidence. When FormulaTracer has no certificate, fail-closed behavior means that an empirical value or estimate is not returned as a certified bound.

## `diagnostics` and `debugger`

For a partial or unresolved result:

- `diagnostics` says what is missing;
- `debugger` helps locate where the missing information or divergence arose.

They distinguish reasons such as an unknown callback, unsupported backend, dynamic dispatch, or insufficient type/effect information.

## `CORRECTLY_UNRESOLVED`

This status is used primarily by `ReconstructionResult` and does not necessarily mean FormulaTracer malfunctioned. Project and output audits use corresponding fail-closed statuses such as `PROJECT_UNRESOLVED` and `UNRESOLVED`.

```text
insufficient information
  ↓
guess EXACT                 ×
CORRECTLY_UNRESOLVED        ✓
```

It means the available source, provider contracts, user declarations, and runtime evidence do not soundly justify a stronger conclusion.

## Rendering is not the canonical result

TeX, JSON, Markdown, Unicode, and human explanations are renderings or serializations of structured results. A readable rendering is not itself proof; inspect the canonical structured result and its `evidence`.

## See also

- [API purpose and selection](api-purpose-guide.md)
- [Detailed class and function usage](api-usage-guide.md)
- [Complete public function inventory](public-functions.md)
- [User-defined semantics](../concepts/user-defined-semantics.md)
