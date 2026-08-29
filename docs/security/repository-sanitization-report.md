# Repository sanitization report

FormulaTracer's public tree was reviewed for private research traces, local
paths, generated certificates, package metadata, and credentials. The cleanup
removed private-corpus inventories and generated operational artifacts,
replaced research-derived fixtures with independently authored synthetic
families, generalized local provenance, and added a runnable public operational
example.

The scan does not reproduce matched private values. Machine-readable evidence
contains redacted fingerprints and aggregate counts only. Hosted issue, pull
request, discussion, and release metadata require a separate host-side review.

History rewriting was required because private research identifiers and local
paths remained reachable even though the current tree was clean. The public
branches were rewritten in a fresh mirror using confirmed private artifact
paths and path-scoped replacements. Commit email metadata was normalized to
public no-reply identities.

The repository had no issues, pull requests, discussions, releases, workflow
artifacts, forks, tags, or pull-request refs at audit time. Therefore no cached
PR view or immutable hosted artifact remained to request removal for. The
repository was private throughout this work.

The validated branches were updated with exact-hash force-with-lease guards and
read back from the host. Old clones must not push their stale refs. Contributors
should discard old clones and make a fresh clone. The private recovery backup
is intentionally not part of the repository and its location is not published.

History sanitization, hosted metadata, package inspection, and regression
outcomes are recorded in `output/repository_sanitization/final-gates.json`.

Post-rewrite validation rebuilt and scanned the source distribution plus
Windows and Linux x86-64 native wheels. Both wheels loaded the native core in
clean environments. The Python suite, Rust workspace, C/C++ conformance,
synthetic operational example, and explicit Lean target build passed. During
that clean validation, three pre-existing fail-closed defects were corrected:
the interval proof target, missing C++ unavailable-evidence, and CRLF-aware
incremental source hashing.
