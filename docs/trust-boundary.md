# Trust boundary

Inside the checked claim are: the selected registry contracts, input/output
representation functions, stated preconditions, canonical graph semantics, and
generated Lean theorem. Outside it are: the scientific truth of the human spec,
Clang and its AST, C++ library internals, compiler/LLVM, machine code, CPU,
floating-point hardware, the YAML parser, and report rendering.

For the initial slice, valid span lengths, object lifetimes, iterator validity,
initialized reads, adequate output capacity, and non-overlap of inputs/output
are explicit proof obligations or contract assumptions. Unknown effects,
unregistered standard entities, unsupported external calls, and possible UB
must fail closed.

