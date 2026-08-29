# Final Stabilization / Defect Burn-down

The ledger was deduplicated and grouped by root cause after Batches A--E.
Renderer findings shared presentation-only causes; semantic-acceptance findings
shared fail-open comparison or evidence-accounting causes. Reproduction tests
are retained for every release-critical fix.

| Metric | Count |
|---|---:|
| Discovered defects | 54 |
| Fixed | 50 |
| Verified fixed | 50 |
| Deferred | 3 |
| Known limitations / unresolved assurance obligations | 4 |
| Critical false-acceptance defects open | 0 |

## Root-cause clusters

- **Renderer (3):** Japanese-path PDF portability, canonical-symbol display,
  and status-row spacing. All are verified fixed by compilation and visual QA.
- **Semantic acceptance / assurance accounting (2):** global axis/order metadata
  comparison and separation of registered corpus entries from executed evidence.
  Both have regression tests and zero open critical false acceptance.
- **Equality/relation boundary (1):** a quadrature provider could inherit an
  exact status from structural unification. It now remains an `APPROXIMATION_OF`
  relation candidate and is ineligible for exact provider selection.
- **Foundational knowledge safety (3):** numeral presentation metadata broke
  semantic constant comparisons, and a reverse identity rooted at a wildcard
  could expand into non-expression AST fields. Natural numbers were also
  incorrectly classified as a ring despite lacking additive inverses. Canonical
  constant comparison, reducing-only directions, schema validation, and a
  distinct commutative-semiring domain now keep these failures closed.
- **Provenance propagation, comparison, cache integrity, and sandboxing (4):** synthetic AST nodes could lack
  end offsets, and location-only metadata leaked into mathematical equality.
  Span construction is now fail-safe, comparison boundaries explicitly ignore
  provenance, and exact literal origin is recovered from enclosing argument or
  named-constant definition spans. A review also found that the initial cache
  draft authenticated its key but not its result payload; canonical value
  digests now reject tampering. The initial sandbox disclosed unenforced network
  denial but still ran; it now blocks by default unless weaker runtime evidence
  is explicitly authorized. All four findings have fixed regression tests.

- **Native Error ABI and graph defaults (3):** the first native request schema
  collided with the kernel dispatch field, and derived graph defaults could
  erase a conservative bound. Both production defects are verified fixed. The
  retired Python oracle cannot express positive RSS and remains a documented
  validation-only limitation; production RSS is Rust-owned and independently
  tested under explicit independence evidence.
- **Native provenance and debugger (4):** differential validation found missing
  source-symbol, Error IR, division-amplification, shared-output, and
  verification-claim joins plus a Python import cycle. General native joins and
  lazy wrapper imports are verified fixed. Full private research-scale corpus wall time stayed nearly
  flat, but peak memory increased; that non-critical performance finding remains
  explicitly deferred and does not weaken correctness or localization gates.
- **Release-candidate execution gates (3):** public CI no longer requires private
  runtime evidence, Linux full assurance declares its Lean environment, and the
  Lake manifest now builds `CppAudit` instead of accepting an empty default
  target. Fresh Debian and Windows regressions retain these fixes.

Known limitations remain explicit in the versioned ledger; registration never
upgrades them to verification evidence.

The TeX-first mathematical API increment added two generation-round-trip
findings. Redundant Python `int` wrappers were removed and regression-tested.
Default project-level return-target selection for accumulator loops now delegates
that bounded case to function-scoped independent Python frontend re-analysis;
the initializer can no longer be mistaken for the returned fold.

RC packaging added two findings. The missing wheel build requirement is
verified fixed by constructing and inspecting the wheel. The incomplete project
license text remains explicitly deferred until the maintainer selects the final
license; it blocks final release but is not a mathematical false-acceptance risk.
