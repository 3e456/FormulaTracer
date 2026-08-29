# Dependency and license audit

Audit date: 2026-08-27. Scope: tracked FormulaTracer source plus the active
Windows RC environment. This is an engineering assessment, not legal advice.

## Conclusion first

No tracked third-party source or vendored dependency tree was found. PyYAML and
jsonschema are the only direct Python runtime requirements in `pyproject.toml`;
their observed versions are 6.0.3 and 4.26.0. LLVM/Clang 18 is an optional
native build/link requirement, and Lean/mathlib are proof-build requirements.
Scientific libraries in provider registries are not thereby imported or
distributed.

Windows and Linux native wheels were built, inspected, installed into clean
environments, and executed. Their metadata declares only PyYAML and jsonschema
at Python runtime; neither artifact contains the untracked DOCX or an external
source tree. The wheels include the complete project license.

FormulaTracer is licensed under Apache-2.0. The choice retains the repository's
existing declarations and supplies an explicit patent grant while remaining
compatible with the measured permissive runtime and build dependency set.
`LICENSE`, `pyproject.toml`, Cargo metadata, `CITATION.cff`, the READMEs, and
this audit now agree. This is an engineering compatibility review, not legal
advice.

## Seven usage categories

| Category | Observed items | Imported/linked? | Distributed in tracked source? |
|---|---|---:|---:|
| Runtime dependency | PyYAML, jsonschema; transitive attrs, jsonschema-specifications, referencing, rpds-py | Yes at runtime | No |
| Build dependency | setuptools; optional LLVM/Clang 18; Lean 4.19.0; mathlib 4.19.0 | Build/proof dependent | No |
| Development/test dependency | pytest 9.1.1 | Test only | No |
| Optional provider | NumPy, SciPy, pandas, xarray, Dask, Numba, JAX, PyTorch, CuPy, SymPy, scikit-learn, statsmodels, Eigen, Boost, egg, egglog | No in base runtime | No |
| External validation only | Ephemeral NumPy/SciPy and other recorded corpus checkouts | No retained import/link | No; cleanup count 0 |
| Referenced documentation/paper | DLMF, SciPy docs, LAPACK Users' Guide, egg paper | No | No |
| Copied/vendored source | None found in tracked files | No | No |

The full per-item table is
[`dependency-license-inventory.json`](../output/release_candidate/dependency-license-inventory.json).
`NOT_INSTALLED` and `REFERENCE_ONLY_VERSION_UNPINNED` are deliberately not
replaced with guessed versions.

## Candidate project licenses

| Candidate | Compatibility with observed permissive dependencies | Attribution/redistribution | Patent terms | Research/commercial ergonomics |
|---|---|---|---|---|
| Apache-2.0 | Good for the observed dependency set; current declared choice | Preserve license/notices and mark modified files where applicable | Explicit patent grant and termination | Permissive; somewhat longer compliance text |
| MIT | Good for observed non-vendored dependencies | Preserve copyright and permission notice | No express patent license | Very short and widely understood |
| BSD-3-Clause | Good for observed non-vendored dependencies | Preserve copyright, conditions, disclaimer; no endorsement | No express patent license | Permissive and familiar in scientific computing |

Decision: Apache-2.0. MIT would have been shorter and BSD-3-Clause familiar in
scientific computing, but neither includes Apache-2.0's express patent grant.
No measured dependency requires changing the selected license. Generated
research code is not automatically relicensed by FormulaTracer; generated
artifacts must preserve any provider/template notices that their own provenance
requires.

## Release blockers and re-check triggers

1. Re-run the inventory against each final wheel, sdist, and native binary.
2. If LLVM-linked binaries or vendored/generated third-party code are shipped,
   collect the applicable license/exception texts and notices in the package.
3. Re-audit whenever optional providers become mandatory or source is copied.

Upstream identifiers were checked against project metadata and official project
repositories; downstream distributors remain responsible for the concrete
artifacts they ship.

## Upstream license evidence

- [PyYAML official repository](https://github.com/yaml/pyyaml) — MIT.
- [jsonschema project metadata](https://github.com/python-jsonschema/jsonschema/blob/main/pyproject.toml) — MIT and runtime dependency declarations.
- [LLVM license](https://github.com/llvm/llvm-project/blob/main/llvm/LICENSE.TXT) — Apache-2.0 with LLVM exception.
- [mathlib4 repository](https://github.com/leanprover-community/mathlib4) — Apache-2.0.
- [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html), [MIT](https://opensource.org/license/mit), and [BSD-3-Clause](https://opensource.org/license/BSD-3-clause) canonical candidate terms.
