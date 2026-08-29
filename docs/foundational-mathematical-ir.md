# Foundational Mathematical IR

The foundational primitive catalogue provides stable semantic names for the
frontend, knowledge registry, provider retrieval, renderer, and debugger. It
includes algebraic structures and numeric domains; binders and equations;
logic, predicates, `Select`, `Piecewise`, and `Indicator`; sets, relations, and
maps; integer/bit and complex primitives; linear algebra and vector calculus;
ODE/PDE concepts; probability; asymptotics; physical units; uncertainty;
polynomials and solvers; optimization, graphs, geometry, sparse structures, and
transforms.

This catalogue is a vocabulary, not a claim that every operation is formally
implemented. Operations become verification evidence only through an explicit
frontend lowering, a contract or knowledge entry, satisfied facts, and the
appropriate verifier.

Branch-sensitive domain analysis keeps a predicate as a branch assumption. A
term such as `select(x != 0, 1/x, 0)` therefore does not require `x != 0`
globally. Unit conversion is exact only when source and target dimensions match
and the scale/offset are known exactly; incompatible dimensions are rejected.

Algebraic structure facts use a hierarchy (for example field implies ring), but
incompatible numeric-domain facts are contradictory. This prevents a rule that
requires a field, ordering, commutativity, or a bit-vector algebra from being
used solely because its surface syntax matches.
