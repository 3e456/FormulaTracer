# Mathematical Expression IR foundation

Schema version `0.1` introduces versioned expression, dependency, and
transformation objects:

- `schemas/expression-ir.schema.json` describes finite mathematical outputs,
  numeric representation, provenance, and source correspondence.
- `schemas/transformation-rule.schema.json` describes exact,
  exact-under-assumptions, and approximation rules.
- `schemas/transformation-set.schema.json` separates allowed and forbidden
  rules, hard constraints, required observables, objectives, cost model,
  selection policy, and provenance.
- `schemas/dependency-graph.schema.json` and
  `schemas/output-slice.schema.json` persist the validated Rich IR graph and
  the exact backwards slice used for expression recognition.

The Clang-to-expression projection recognizes affine and two-input Maps,
registered elementary calls, simple branch merges as IfThenElse, explicit and
`std::accumulate` FoldLeft forms, and the weighted-sum explicit-loop and
`std::inner_product` TransformReduce forms. Weighted Sum remains a regression:
both implementations produce the same left-to-right finite sum after exact
normalization. Original flattened index text remains attached to the extracted
indexed term, while canonical comparison removes that non-semantic annotation.

Use `cpp-audit dependency-graph --ir FILE` and
`cpp-audit output-slice --ir FILE` to inspect the two intermediate artifacts.
Every generated mathematical term carries Implementation IR node IDs and
source spans. Conditions and true/false branch values retain separate
correspondence.

Structured YAML is the authoritative human formula format. Restricted LaTeX
and the expression DSL are not implemented in this foundation. Renderers emit
LaTeX, Unicode text, Markdown, and JSON from the same Expression IR.

Transformation application now enforces the explicitly selected set, checks
hard constraints before ranking, applies exact/conditional/approximate rules,
and compares the transformed theory graph with the implementation. Forward and
central first differences remain the initial approximation examples. Their
recognition produces an unevaluated residual, not a convergence, error-bound,
or IEEE-754 proof. See `transformation-application.md`.
