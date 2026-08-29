# CLI Reference

Preferred command: `formulatracer`. The historical `cpp-audit` spelling remains
a compatibility entry point. Run `--help` for source-derived defaults.

The Python compatibility CLI includes source audit, formula parsing/comparison,
CFG, certificate, dtype/parallel, provider-contract, and project commands. The
Python-free native CLI supports `canonicalize FILE`, `tex FILE`, `kernel FILE`,
and `compare THEORY IMPLEMENTATION`. Exit code 0 means the command completed;
nonzero means invalid input, unsupported operation, or execution failure.

JSON is structured output. A successful command does not imply every semantic
claim is verified; inspect result status and evidence.

