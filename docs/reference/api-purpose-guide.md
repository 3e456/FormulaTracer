# API Purpose and Selection Guide

[日本語](api-purpose-guide.ja.md) | [Detailed usage guide](api-usage-guide.md) | [Complete generated inventory](public-functions.md)

This page answers a different question from the exhaustive API reference:

> **Which FormulaTracer API should I use, and why does it exist?**

The detailed usage guide explains signatures, arguments, return values, ownership, and runnable examples. This page explains **purpose, when to use an API, when not to use it, and how nearby APIs differ**.

## Start here: choose by task

| What you want to do | Start with | Why |
|---|---|---|
| Audit scientific source code | `FormulaTracer.from_source(...)` → `analyze()` | This is the normal high-level code-first workflow. |
| Find why an audit is partial or unresolved | `FormulaTracer.debug(...)` | Adds source/semantic localization to the normal audit. |
| Reuse a previous project audit safely | `analyze_incremental(...)` | Reuses valid cached analysis without silently trusting stale state. |
| Enter a mathematical formula directly | `FormulaTracer.from_tex(...)` or `from_expression(...)` | Creates a `MathematicalFormula` without pretending it came from source code. |
| Compare two independently obtained mathematical structures | `compare_ir(...)` | Checks semantic correspondence between two Mathematical IR documents. |
| Ask how a mathematical formula could be implemented | `plan_generation(...)` / `MathematicalFormula.plan_generation(...)` | Produces ranked implementation/provider candidates; ranking is not proof. |
| Generate source code from a formula | `MathematicalFormula.generate(...)` | Emits a realization and can independently re-audit the emitted source. |
| Synthesize an implementation from declared theory and constraints | `FormulaTracer.synthesize(...)` | Higher-level generation workflow; generation and verification remain distinct. |
| Tell FormulaTracer the intended theory of your own function | `@theory` / user-defined semantics | Adds user-declared semantics as evidence, not as automatic verification. |
| Evaluate or substitute values into reconstructed mathematics | `NativeMathematicalFunction` | Executes the supported pure Mathematical IR subset without Python `eval()`. |
| Work directly with the native core | `NativeContext`, `NativeFormula`, `NativeResult` | Low-level owned-handle API for native integration and advanced users. |
| Build a custom frontend/integration | `ProjectAnalyzer`, `reconstruct(...)` | Advanced integration APIs; ordinary users normally do not call them directly. |
| Check whether the packaged native library can load | `native_available()` | Environment capability probe only; it is not semantic evidence. |

## A useful mental model

FormulaTracer has three common directions of travel:

```text
source code
   ↓
FormulaTracer.analyze()
   ↓
ProjectAuditResult
   ↓
reconstructed mathematics + relations + evidence + unresolved reasons
```

```text
mathematical formula
   ↓
MathematicalFormula
   ↓
plan_generation() / generate()
   ↓
implementation candidate or generated source
   ↓
independent re-audit
```

```text
independent theory IR + implementation IR
   ↓
compare_ir()
   ↓
semantic comparison result
```

If you are unsure which path applies, start with `FormulaTracer` rather than the native or reconstruction APIs.

---

## `FormulaTracer`

### Purpose

The normal public entry point for auditing scientific source code and for starting high-level formula workflows.

### Use it when

- you have Python, Rust, C, or C++ source that you want FormulaTracer to audit;
- you want project/dependency discovery rather than manually constructing internal IR;
- you want the standard result model, diagnostics, provenance, error/range information, and debugger data.

### Usually do not replace it with

- `ProjectAnalyzer`, unless you are integrating a custom frontend;
- `reconstruct()`, unless you already possess an independently produced implementation description;
- `NativeContext`, unless you need the low-level native API.

### Typical path

```python
tracer = FormulaTracer.from_source("model.py")
result = tracer.analyze()
```

For most users, this is the first API to learn.

---

## `FormulaTracer.analyze()`

### Purpose

Audit source/project outputs and reconstruct the mathematics actually implemented, while preserving evidence, assumptions, relations, numerical claims, provenance, and unresolved conditions.

### Use it when

You want the answer to: **“What mathematics does this code actually implement, and how strongly is that conclusion supported?”**

### What it does not mean

A successful return does not mean the code is formally verified. Read the returned `status`, `relation`, `evidence`, assumptions, proof obligations, error/range information, and diagnostics.

### Main result

Returns `ProjectAuditResult`.

---

## `ProjectAuditResult`

### Purpose

The main project-level audit result. It is the object you inspect after `analyze()`.

### Use it to answer

- Did the project audit complete fully, partially, or unresolved?
- Which requested outputs were reconstructed?
- Which output caused the project-level status?
- What diagnostics, provenance, error/range claims, or debugger information are attached?

### Important distinction

A project-level status summarizes multiple outputs. One output can be fully reconstructed while another remains unresolved. Inspect per-output results rather than interpreting only the top-level status.

### Typical next steps

- `get_output(name)` to inspect a specific output;
- `to_dict()` / `to_json()` for structured export;
- `write_json(path)` for a durable audit artifact;
- `debug()` when you need source localization for a failure or unresolved result.

---

## `FormulaTracer.debug()`

### Purpose

Explain **where** an unresolved, mismatched, or otherwise important audit result originates in source/semantic structure.

### Use it when

`analyze()` tells you *what* happened, but you need to know *where and why*.

### Typical questions

- Which source location introduced the unresolved operation?
- Which reconstructed expression or relation caused the mismatch?
- Where did evidence stop being sufficient?

### Do not use it as

A separate verification engine. It derives localization from the same audit semantics.

---

## `analyze_incremental()`

### Purpose

Reuse a previous `ProjectAuditResult` and compatible cache information when auditing a changed project.

### Use it when

You repeatedly audit a larger project and want to avoid unnecessary recomputation.

### Safety property

Cache reuse is conditional on validity. Stale or incompatible cache state must not silently become semantic evidence.

### For a first audit

Use `analyze()` instead.

---

## `MathematicalFormula`

### Purpose

Represent a mathematical object directly for inspection, explanation, transformation, generation planning, and realization workflows.

### Use it when

Your starting point is mathematics rather than source code.

Examples:

- a TeX expression from a paper or note;
- canonical Mathematical IR;
- a formula you want to render, constrain, transform, or implement.

### Do not confuse it with

A claim that an implementation matches the formula. That correspondence requires independent implementation evidence or comparison.

---

## `FormulaTracer.from_tex()`

### Purpose

Parse human TeX notation into FormulaTracer's structured mathematical representation.

### Use it when

Your starting artifact is a mathematical formula written in TeX.

### Important boundary

Parsing a formula does not prove convergence, domains, inverse laws, or correspondence with any program. Ambiguous notation is not guessed into a verified interpretation.

---

## `FormulaTracer.from_expression()`

### Purpose

Start directly from an already structured Mathematical IR expression.

### Use it when

Another trusted component already produced FormulaTracer-compatible Mathematical IR and TeX parsing would be unnecessary.

---

## `compare_ir()`

### Purpose

Compare two **independently obtained** Mathematical IR documents through FormulaTracer's canonical semantic machinery.

### Use it when

You want to compare, for example:

- declared theory vs mathematics reconstructed from code;
- two independently reconstructed implementations;
- a generated realization vs an independent frontend reconstruction.

### Do not use it when

Both arguments are merely two renderings of the same internal object and you intend that to count as independent verification.

### Important boundary

An exact semantic relation does not automatically mean Lean kernel evidence is present. Inspect `evidence` separately.

---

## `plan_generation()` and `MathematicalFormula.plan_generation()`

### Purpose

Find and rank implementation/provider candidates for a mathematical expression while retaining assumptions, constraints, relation information, and proof obligations.

### Use it when

You know the mathematics and want to ask: **“What existing implementation or provider contract could realize this?”**

### What the returned ranking means

Ranking is a search result, not a proof. A highly ranked candidate can still have unmet conditions or obligations.

### Main result

Returns `GenerationPlan`.

---

## `GenerationPlan`

### Purpose

Collect candidate realizations, search-budget information, selection state, relation information, and decision provenance for one generation request.

### Use it to

- inspect why candidates were found;
- compare candidates;
- see unmet obligations;
- select only a rigorously eligible candidate.

### Usually created by

`plan_generation()` rather than directly by user code.

---

## `CandidateMatch`

### Purpose

Represent one possible provider/implementation match inside a `GenerationPlan`.

### Use it to inspect

- which provider contract matched;
- its verification/eligibility state;
- remaining obligations;
- why it is or is not selectable.

### Important boundary

A candidate match is not the same as an implementation proof.

---

## `MathematicalFormula.generate()`

### Purpose

Generate source code for a selected mathematical realization.

### Use it when

You have a mathematical formula and want an implementation candidate in a supported target language.

### Critical distinction

Generated source starts as generated source, not verified source. Independent frontend re-analysis (`verify=True` or `generated.verify()`) is the step that checks the emitted implementation through the normal audit path.

---

## `GeneratedMathematicalImplementation`

### Purpose

Hold generated source together with its realization status and independent re-audit state.

### Use it to

- inspect emitted code;
- determine whether independent verification has been attempted;
- retain the distinction between generated and independently audited artifacts.

### Usually created by

`MathematicalFormula.generate()` rather than directly.

---

## `FormulaTracer.synthesize()`

### Purpose

Higher-level workflow for producing an implementation from declared theory plus language/constraint information.

### Use it when

You want a more end-to-end synthesis workflow rather than manually calling planning and generation steps.

### Difference from `generate()`

`generate()` operates from an existing `MathematicalFormula` and selected generation context. `synthesize()` is a higher-level facade around theory + constraints + target language.

### Important boundary

Synthesis and verification remain separate even when verification is requested in the same workflow.

---

## `@theory`

### Purpose

Attach a user-declared intended mathematical expression to a function without changing how the function executes.

### Use it when

You want to state: **“This function is intended to implement this mathematical relation.”**

This is useful as redundant evidence, especially for user-defined or domain-specific functions.

### It does not mean

- the implementation has been proven to match the declaration;
- the declaration is reference-backed;
- the declaration is Lean-kernel verified.

FormulaTracer must keep user declaration, implementation-derived semantics, reference evidence, and formal evidence distinguishable.

---

## User-defined semantics

### Purpose

Provide explicit mathematical/effect/domain information for functions FormulaTracer cannot fully infer automatically, such as domain-specific callbacks or unavailable implementations.

### Use it when

- a callback is external or opaque;
- a proprietary/native/hardware function cannot be inspected;
- the function's mathematical meaning is known to the user but unavailable to static analysis.

### Why it remains useful even as automatic coverage improves

It is a redundant semantic input path for future libraries and unavailable implementations.

### Evidence boundary

User-declared semantics are evidence with an explicit provenance class; they are not silently promoted to implementation or kernel verification.

---

## `ProjectAnalyzer`

### Purpose

Lower-level project analysis entry point for frontend/integration work.

### Use it when

You are implementing or embedding a custom source frontend or need direct analyzer control.

### For normal users

Prefer `FormulaTracer`.

---

## `reconstruct()`

### Purpose

Run the reconstruction kernel on an independently produced implementation-description request.

### Use it when

You already have lower-level implementation/algorithm information from a frontend or external analysis pipeline and want FormulaTracer to reconstruct mathematical semantics from it.

### For normal source audits

Do not manually construct a reconstruction request. Use `FormulaTracer.analyze()`.

### Why this API exists

It is an integration boundary between implementation extraction and FormulaTracer's mathematical reconstruction semantics.

---

## `ReconstructionResult`

### Purpose

Represent the outcome of reconstruction while preserving exact and non-exact relations, assumptions, obligations, diagnostics, and unresolved reasons.

### Use it when

You call `reconstruct()` or are building frontend/integration tooling.

### Important boundary

`CORRECTLY_UNRESOLVED` is a valid fail-closed result. It should not be converted into an invented exact relation merely to increase coverage.

---

## `NativeContext`

### Purpose

Own the low-level native FormulaTracer context used to create native formula/result/function handles.

### Use it when

You need direct access to the stable native boundary from Python or are testing/integrating the native layer.

### For normal Python users

Prefer `FormulaTracer` and high-level result objects.

### Ownership

Use a context manager or `close()` for owned native objects.

---

## `NativeFormula`

### Purpose

Own a mathematical formula inside the native core and expose native verification/comparison operations.

### Use it when

You are intentionally working at the native API level.

### Usually obtained from

`NativeContext.formula_from_json(...)` or `formula_from_tex(...)`.

---

## `NativeResult`

### Purpose

Own a native verification result handle and expose structured projections/renderings without making renderings canonical.

### Use it when

You called native verification APIs directly.

### For normal users

Use the high-level structured result returned by the normal FormulaTracer workflow unless native ownership/control is specifically required.

---

## `NativeMathematicalFunction`

### Purpose

Evaluate, substitute, inspect, and serialize the subset of Mathematical IR supported by the native function evaluator.

### Use it when

You already have reconstructed/canonical mathematics and want to:

- evaluate it for named values;
- partially substitute parameters;
- create a callable for a supported backend;
- serialize the function schema.

### It is not

A general Python-expression evaluator. Unsupported operations, missing variables, domain errors, and shape mismatches fail closed.

---

## `native_available()`

### Purpose

Check whether the packaged stable native library can be loaded in the current environment.

### Use it when

Diagnosing installation or native-loading problems.

### It does not mean

`True` is not evidence that a formula, program, provider, or theorem has been verified.

---

## Result/evidence APIs: what to read first

For any structured audit/comparison result, interpret fields in roughly this order:

1. **`status`** — overall semantic outcome.
2. **`relation`** — exact, approximation, discretization, or other semantic relationship.
3. **`evidence`** — what actually supports the conclusion.
4. **`assumptions` / `proof_obligations`** — conditions still required.
5. **`error` / `range`** — numerical claims only when supported by appropriate evidence.
6. **`provenance`** — where inputs, contracts, and conclusions came from.
7. **`diagnostics` / debugger information** — why a result is partial or unresolved and where it originated.

Do not infer a stronger guarantee from a convenient rendering such as TeX, JSON, Markdown, or an explanation string.

## High-level vs advanced API summary

### Most users should learn first

- `FormulaTracer`
- `analyze()`
- `ProjectAuditResult`
- `debug()`
- `MathematicalFormula`
- `compare_ir()`
- `plan_generation()` / `generate()` if generation is needed
- `@theory` / user-defined semantics if custom functions need declared meaning

### Advanced integration APIs

- `ProjectAnalyzer`
- `reconstruct()` / `ReconstructionResult`
- `NativeContext`
- `NativeFormula`
- `NativeResult`
- `NativeMathematicalFunction`

The advanced APIs are public because they are useful for integrations and native workflows, not because every user needs them.

## See also

- [Detailed class and function usage](api-usage-guide.md)
- [Complete generated public function inventory](public-functions.md)
- [Result model](result-types.md)
- [User-defined semantics](../concepts/user-defined-semantics.md)
- [C ABI](c-api.md)
- [Rust API](rust-api.md)
