# Security policy

FormulaTracer analyzes untrusted source but does not make the host process a
sandbox. Run Clang frontends and generated builds in an isolated environment.

Report suspected vulnerabilities through GitHub's **Private vulnerability
reporting** feature on the FormulaTracer repository. Do not open a public issue
for a vulnerability and do not attach private research source, datasets,
credentials, or audit output. Ordinary bugs belong in GitHub Issues; usage
questions belong in GitHub Discussions.

Please include a minimal independently authored reproducer, affected version,
platform, impact, and any suggested mitigation. Maintainers will acknowledge a
report when it is reviewed; no fixed response-time SLA is currently offered.

## Public/private data boundary

Do not commit user research source, theories, formulas, datasets, provenance,
local audit outputs, environment-specific paths, or credentials to this
repository. Use a gitignored local configuration and keep operational evidence
with the private project. Public bug reproductions must be independently
authored synthetic fixtures or use appropriately licensed public sources.

See [the public/private boundary](docs/security/public-private-boundary.md).
