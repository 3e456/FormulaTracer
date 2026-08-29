# Native core completion validation

Status: **NATIVE CORE COMPLETE**. The authoritative machine-readable decision
is `output/native_migration/final/final-native-certificate.json`, mirrored by
`output/native_core_completion/gates.json`.

FormulaTracer production semantics now have one source of truth: the Rust
`formulatracer-core`. Python remains a language frontend, thin facade,
adapter/presentation layer, and isolated reference/validation oracle. The final
inventory reviewed 442 symbols from six former owner modules and found zero
production semantic owners, zero production semantic symbols, zero reachable
Python semantic decisions, and zero unresolved dynamic dispatch. Inventory
consistency is `PASS`.

Wave 4 moved GenerationDecision, provider compatibility, assumptions,
obligations, relation classification, safe-to-generate decisions, semantic
round-trip comparison, and repair verification into `D/LEGACY_SYNTHESIS`.
Python retains only formatting, source emission, IDs, wrappers, and
orchestration. Focused synthesis assurance passed 15/15 with zero false safe
generation and zero open obligation promoted to safe.

Final regression evidence:

- Python: 571 passed, 1 skipped, 36 subtests passed.
- Rust: 41 core plus 3 C-ABI tests passed; the 196,864-case eight-bit
  exhaustive check is included.
- C and C++: all four compile/run conformance steps passed.
- Python--Rust and TeX differential: 1,056/1,056 each, false acceptance 0.
- Structural Isomorphism: 28 cases, 10 positive correspondences, zero false
  isomorphism and zero semantic mutation collapse.
- Lean 4.19: `lake build` passed; `sorry`, `admit`, and `axiom` are all zero.
- AuditBundle field parity and integrity: `PASS`.

The read-only private research-scale corpus certification completed in 1,850.28 seconds. It preserved
the bucketed baseline cardinality of 20+ projects, 170+ source files,
40k+ LOC, 700+ roots, and 900+ outputs. Detailed runtime counts are retained privately. Production semantic
calls were Rust-native; Python semantic calls and fallback were zero. Critical
false acceptance and false localization were zero, the corpus was not modified,
and research data content was not read.

External OSS assurance rechecked seven pinned revisions from five official
scientific repositories and 317 selected source files. External source retained
is zero and critical false acceptance is zero. External-21 reconstruction is
artifact-complete 21/21, uses 63 Rust-native calls and no Python semantic path,
and now projects every fixed-corpus outcome through the Rust-owned
`ReconstructionResult`. Because the historical artifacts lack generated source,
they remain deliberately fail-closed with explicit reasons. Independent native
reconstruction assurance covers exact, relational, inline/uninline, Loop/Fold,
provider projection, and semantic mutations.

Windows AMD64 and Linux x86_64 wheels were rebuilt, audited to contain exactly
one platform-native library, installed in clean environments, and exercised
through TeX input, generation/re-audit, native loading, and structured result
JSON/TeX. Supported-wheel users do not require Rust or Cargo.

Native completion remains separate from release readiness. The current release
decision is recorded in `output/reconstruction_closure/gates.json`.
