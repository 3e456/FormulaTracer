# Native semantic debugger

The semantic debugger is a fail-closed Kernel E consumer of recorded provenance.
Rust owns divergence taxonomy, localization level, root-cause candidate strength,
and MinimalReproducer semantic selection. Python retains report rendering and
safe temporary-file creation only.

Localization strength is ordered as:

1. `EXACT_SOURCE_SPAN`
2. `SOURCE_SPAN_SET`
3. `CORRECT_SEMANTIC_NODE`
4. `SOURCE_BASIC_BLOCK`
5. `SOURCE_FUNCTION`
6. `SOURCE_MODULE`
7. `UNRESOLVED`

An exact span requires one complete directly recorded operator/argument origin.
Multiple valid origins produce `SOURCE_SPAN_SET`; missing physical evidence can
produce only a semantic node or `UNRESOLVED`. Nearest-line guessing is forbidden.
Consequently false localization is treated as more severe than unresolved output.

Root-cause results distinguish strong candidates, possible contributors, and
cases blocked by unresolved semantics. A semantic difference is not automatically
causal. FFI and serialization boundaries remain explicit blockers. Error findings
link native Error components, propagation causes, proof obligations, division
amplification points, and source origins without changing Error certification.

MinimalReproducer selection retains expected/actual semantic roots, source subset,
required inputs/configuration/assumptions, and the expected failure. If dependency
closure is unknown it returns `MINIMAL_REPRODUCER_UNRESOLVED`; a smaller fragment
is never assumed valid merely because it is small.

Typed structural-isomorphism witnesses may contribute node correspondence but are
not proof. Provider retrieval, runtime samples, and correlated differences likewise
remain evidence rather than kernel-verified causal claims.

