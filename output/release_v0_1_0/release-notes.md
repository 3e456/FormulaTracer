# FormulaTracer v0.1.0

FormulaTracer v0.1.0 is the first release candidate closed as a public-facing
scientific-code audit system. It reconstructs mathematical expressions from
scientific source code and preserves exact, non-exact, unresolved, and
evidence-qualified results as structured objects.

## Highlights

- Rust native semantic core shared by Python, Rust, the stable C ABI v1, and a
  thin C++ RAII wrapper.
- Python, Rust, and C++ scientific-source frontends and project audit support.
- Fail-closed relation and evidence model with an Exact E-Graph separated from
  approximation, discretization, truncation, sampling, and algorithmic
  realization relations.
- Selected scientific provider semantics, user-defined semantic declarations,
  error/range analysis, provenance, data lineage, and semantic debugging.
- Lean 4 integration for kernel-verified evidence boundaries.
- Physics foundation registry separating definitions, conditional theorems,
  proof evidence, and numerical realizations.
- Structured verification results with TeX/JSON projections and safe
  MathematicalFunction evaluation.
- English and Japanese documentation, including detailed class/function
  signatures, arguments, returns, failure behavior, and runnable examples.
- Release validation on Windows x86-64 and Debian 12 x86-64.

## Assurance summary

The semantic code baseline was validated at
`e2b8c98f234f887b6309d2403f283024703a1088`: Windows Python 608 passed; Debian
Python 607 passed with one platform-specific skip; Rust 68 passed; C/C++ 4
passed; Python--Rust and TeX differential suites matched 1056/1056; BitVector
exhaustive assurance passed 196,864 cases; Lean built 2,842 targets with
`sorry/admit/axiom = 0/0/0`; Clippy deny-warnings passed with zero warnings;
false acceptance remained zero. Subsequent release changes are documentation,
focused documentation tooling/tests, and release evidence only.

## Limitations

- Provider contracts cover selected semantics; a registry entry does not mean
  complete support for every API or behavior of the upstream library.
- Dynamic targets, runtime-only information, unknown effects, and unsupported
  notation may remain explicitly unresolved.
- Public NumPy, SciPy, xarray, and Dask validation cases are partial
  reconstruction evidence, not proof of arbitrary-library support.
- Linux release validation is specifically Debian GNU/Linux 12 x86-64; this is
  not a claim about every Linux distribution or architecture.
- Physics definitions and conditional theorems do not prove the empirical truth
  of natural laws.
- `USER_DECLARED`, implementation verification, and Lean kernel verification
  remain distinct evidence classes.

Package-registry publication is intentionally outside this release closeout:
no PyPI or crates.io publication is performed.
