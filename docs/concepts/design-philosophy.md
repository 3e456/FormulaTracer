# Design philosophy

FormulaTracer values integration and explicit evidence boundaries over a claim
of universal verification. The Rust semantic core owns interpretation; Python,
C, and C++ adapt arguments and results. Lean independently checks only the
proof obligations sent to it.

The default policy is fail-closed. Missing contracts, ambiguous notation,
unknown calls, and open assumptions remain unresolved. Candidate retrieval is
high recall, but adoption is strict: typed unification, authorized rewrites,
domain/type/shape checks, and semantic re-comparison are required.

A declared theory is never used to reconstruct the implementation. Code is
analyzed first; an independently supplied theory enables an additional
comparison afterwards.
