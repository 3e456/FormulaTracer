# Python CFG and mutation semantics

The Python frontend now emits an explicit implementation-level control-flow
graph before mathematical normalization. `python-cfg SOURCE --function NAME
--output VALUE` prints this artifact as JSON.

## CFG IR

Blocks use `Entry`, `Exit`, `BasicBlock`, `Branch`, `LoopHeader`, and
`MergePoint`. Edges distinguish normal flow, true/false branches, loop body and
exit, `LoopBackEdge`, `BreakEdge`, `ContinueEdge`, `ReturnEdge`, and
`ExceptionEdge`. Source spans and original statement text remain attached.

The summary reports branch, loop, mutation, exception-path, and return counts,
plus alias, termination, and unresolved-control-flow status. Only unresolved
semantics intersecting the selected output's conservative name slice are
critical; unrelated exception paths do not lower the certificate status.

## Mutation and aliases

The implementation IR preserves indexed assignment, indexed/name in-place
arithmetic, attribute updates, list append/extend, and dictionary/array indexed
updates. Direct aliases such as `b = a; a = x` are followed to `x`. Values from
calls, attributes, or subscripts are not guessed: mutation through such a value
is `POTENTIAL_ALIAS`. Targets without a stable named base are
`MUTATION_TARGET_UNRESOLVED`.

## Normalization boundary

- Complete `if/else` definitions become `IfThenElse`.
- `for range(...)` accumulator patterns normalize to finite folds.
- comprehensions become `Map`, with conditional clauses represented as
  `Filter` followed by `Map`; generator reductions share fold semantics.
- `enumerate`/`zip`, loops with `break`/`continue`, and general `while` remain
  `LoopInvocation` unless a safe finite normalization is recognized.
- exception-dependent output becomes `ExceptionChoice` and
  `EXCEPTION_PATH_UNRESOLVED` when the raising condition is not statically known.

`REPORT_ONLY` retains these nodes and produces a certificate. `STRICT` rejects
critical unresolved control flow. The analysis intentionally does not claim
complete Python alias analysis, exception-condition inference, iterator
termination, arbitrary object mutation, concurrency, or reflection semantics.
`return`/`break`/`continue` interactions inside `finally` are conservatively
preserved but are not yet normalized into mathematical expressions.
