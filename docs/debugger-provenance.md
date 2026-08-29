# Debugger provenance and localization

The semantic debugger now carries source/operator/argument/keyword origins into
Implementation IR and Mathematical IR findings. Findings distinguish exact
source spans, source span sets, semantic nodes, basic blocks, functions,
modules, and unresolved localization. Strong source confidence is emitted only
for recorded exact/span-set origins.

Mutation ground truth can be evaluated with `debug.evaluate_localization()`.
Wrong high-confidence locations count as `FALSE_LOCALIZATION`; unresolved is
preferred to guessing. Findings also retain blocking evidence, rewrite traces,
minimal divergent subgraphs, root-cause grouped outputs, and serialization vs
mathematics boundaries.

`debug.create_reproducer()` writes a self-owned semantic fixture to an explicit
temporary/copy directory and verifies that the same divergence remains. It does
not modify or copy the original research project or dataset.

Generated validation execution uses `run_sandboxed()`: a temporary working
directory, no shell, timeout, proxy/environment scrubbing, bounded captured
output, and read-only-by-contract external input paths. The reference Windows
backend cannot enforce process network denial, so the default policy blocks
execution rather than claiming isolation. A caller may explicitly permit
best-effort isolation or network access; either result is `RUNTIME_EVIDENCE`,
never proof. Memory limits are likewise reported as unenforced.
