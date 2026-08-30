# 公開Function/APIリファレンス

Version: FormulaTracer 0.1.1 / C ABI v1

このreferenceは実装から生成したcanonical inventoryに対応します。文字列・TeX・JSONは構造化resultの派生表現であり、証拠不足はfail-closed（安全側に未解決）になります。

## `FormulaTracer`

Primary code-first facade for source and project audits.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** source/project inputs; use from_tex only when the requested object is a formula
- **Returns / 返却:** structured project or formula facade
- **Failure / unresolved:** unsupported frontend or unresolved semantics remain explicit; no verification is inferred
- **Effects / cost:** Python facade; semantic decisions are delegated to the Rust core
- **Source:** `python/cpp_audit/project.py:1764`

## `MathematicalFormula`

Human-facing formula facade for explanation, generation planning and verification workflows.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** canonical Mathematical IR and optional metadata
- **Returns / 返却:** structured plans/results and derived TeX
- **Failure / unresolved:** ambiguous or unsupported operations remain unresolved
- **Effects / cost:** semantic decisions are delegated to the native core or versioned provider packs
- **Source:** `python/cpp_audit/generation_planning.py:436`

## `NativeFormula`

Owned native formula parsed from versioned IR or supported TeX.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** NativeContext plus canonical JSON or supported TeX
- **Returns / 返却:** NativeResult from verify/verify_against
- **Failure / unresolved:** ambiguous notation and invalid semantic documents are rejected
- **Effects / cost:** owns a native handle
- **Source:** `python/formulatracer/native.py:189`

## `NativeMathematicalFunction`

Safely evaluates and substitutes the Mathematical IR subset supported by the native core.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** structured inputs/substitutions; no eval strings
- **Returns / 返却:** JSON-compatible value or a new function object
- **Failure / unresolved:** domain, shape, unsupported-operation and missing-input errors fail closed
- **Effects / cost:** owns a native function handle; evaluation is local and deterministic for supported pure IR
- **Source:** `python/formulatracer/native.py:254`

## `NativeResult`

Canonical structured verification result returned through the native boundary.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** owned native result handle
- **Returns / 返却:** status, theory, implementation, relation, assumptions, error/range, evidence and provenance
- **Failure / unresolved:** unavailable projections return None or a fail-closed NativeCallError as documented by the method
- **Effects / cost:** owns a native handle; renderings are derived and never the canonical result
- **Source:** `python/formulatracer/native.py:397`

## `ProjectAnalyzer`

Discovers audit roots and outputs across one source project.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** project root, language/frontend options, output selection
- **Returns / 返却:** project analysis with per-root structured results
- **Failure / unresolved:** unsupported dynamic roots and missing build metadata are reported unresolved
- **Effects / cost:** may read source/build metadata and create an incremental cache when configured
- **Source:** `python/cpp_audit/project.py:1148`

## `ReconstructionResult`

Structured reconstruction outcome preserving exact and non-exact relations.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** constructed by reconstruct rather than directly by typical callers
- **Returns / 返却:** status, mathematical_ir, relation_chain, assumptions, obligations and diagnostics
- **Failure / unresolved:** CORRECTLY_UNRESOLVED is a safe result and FALSE_ACCEPTANCE is an assurance failure
- **Effects / cost:** data object with no external side effects
- **Source:** `python/formulatracer/reconstruction.py:11`

## `compare_ir(theory: 'dict[str, Any]', implementation: 'dict[str, Any]') -> 'NativeResultValue'`

Compares two Mathematical IR documents through native canonicalization.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** theory IR and independently extracted implementation IR
- **Returns / 返却:** NativeResultValue
- **Failure / unresolved:** insufficient typing or non-equivalence is not promoted to exact equality
- **Effects / cost:** pure native query apart from handle allocation
- **Source:** `python/formulatracer/native.py:472`

## `native_available() -> 'bool'`

Reports whether the stable C ABI native library can be loaded.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** none
- **Returns / 返却:** bool
- **Failure / unresolved:** False means native operations cannot run; it is not semantic evidence
- **Effects / cost:** loads/probes the packaged native library
- **Source:** `python/formulatracer/native.py:461`

## `plan_generation(expression: 'dict[str, Any]', *, search: 'str' = 'normal', candidate_budget: 'int | None' = None, budget: 'SearchBudget | None' = None, registry: 'Iterable[ProviderContract] | None' = None, assumptions: 'Iterable[str]' = (), authorized_rewrites: 'Iterable[str] | None' = None, language: 'str | None' = None) -> 'GenerationPlan'`

Builds a ranked provider/code-generation candidate plan without treating similarity as proof.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** Mathematical IR plus search budget and language/provider constraints
- **Returns / 返却:** GenerationPlan
- **Failure / unresolved:** candidates with unmet constraints remain unselectable or unresolved
- **Effects / cost:** provider lookup may be expensive; generation does not verify emitted code
- **Source:** `python/cpp_audit/generation_planning.py:361`

## `reconstruct(request: 'Mapping[str, Any]') -> 'ReconstructionResult'`

Reconstructs Mathematical IR from an independently produced implementation description.

- **Stability / 安定性:** `PUBLIC_STABLE`
- **Parameters / 引数:** a versioned reconstruction request mapping
- **Returns / 返却:** ReconstructionResult
- **Failure / unresolved:** missing effects, aliasing, relation evidence, or source IR produces CORRECTLY_UNRESOLVED
- **Effects / cost:** calls the native reconstruction kernel; it does not execute source code
- **Source:** `python/formulatracer/reconstruction.py:37`

## Usage / 使い方

- [引数・戻り値・実コードを含む使い方](api-usage-guide.ja.md)

## Evidence boundary / 証拠境界

`USER_DECLARED` is redundant evidence and never means `KERNEL_VERIFIED`. Structural correspondence is a matching witness, not a proof. Runtime agreement is runtime evidence only.

## See also

- [Result model](result-types.md)
- [C ABI](c-api.md)
- [Rust API](rust-api.md)
- [User-defined semantics](../concepts/user-defined-semantics.md)
