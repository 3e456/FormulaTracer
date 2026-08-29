# Assurance, audit bundles, and release reports

The release assurance layer prioritizes false acceptance. It records semantic
mutations, meaning-preserving metamorphic cases, and an adversarial corpus, then
reports true/false acceptance/rejection and unresolved counts. The release gate
requires zero open critical false-acceptance defects.

Corpus registration is not execution evidence. Registered metamorphic and
adversarial cases remain in the `unresolved` metric until a corresponding
runner actually checks them; they never inflate true-acceptance counts.

`ProjectAuditResult.create_bundle(path)` writes a versioned, hashed directory
containing a manifest, source hashes, project graph, implementation and
Mathematical IR, independent theory, transformations, contracts, assumptions,
error/range evidence, Lean records, debug findings, E2E claims, and JSON/LaTeX
certificates. The bundle hash is derived from the immutable member hashes.

`before.diff(after)` compares formula, constants, dependencies, approximation,
error bound, range, proof status, library registry, and artifacts. It reports
semantic categories rather than a text-only diff.

Human certificates support `en-US` and `ja-JP`. Machine IDs, source identifiers,
file names, mathematical symbols, and API names are never translated. JSON
remains locale-neutral. Certificates intentionally show the audit target,
theory/implementation, error/range, result, debug summary, and overall status;
detailed traces stay in JSON and the AuditBundle.
