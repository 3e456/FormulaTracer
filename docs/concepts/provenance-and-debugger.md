# Provenance and semantic debugger

Provenance links source spans, frontend nodes, Implementation IR, Mathematical
IR, transformations, providers, evidence, and output artifacts. The semantic
debugger uses that graph to report the first justified divergence and a
localization level. It must not claim an exact source span when only a function
or module is known.

Public artifacts must not contain private research paths, source, formulas,
datasets, credentials, or environment snapshots. Keep operational AuditBundles
with their originating private project.
