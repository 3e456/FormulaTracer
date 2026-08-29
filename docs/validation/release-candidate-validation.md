# Release-candidate validation

Run date: 2026-08-27. Current result: **RC_NOT_READY**.

## Evidence model

The RC workflow maintains five distinct corpora:

1. deterministic self-generated retrieval/adversarial cases;
2. prior read-only private research-scale corpus real-world validation artifacts;
3. ephemeral external open-source repositories;
4. compact external mathematical/reference fixtures; and
5. a fixed final holdout split.

Development, validation, and holdout case IDs and semantic fingerprints are
fixed in `benchmark-manifest.json`. The holdout is executed only after the
harness is frozen and is never used to select repairs. External implementation
source is not copied into the benchmark; retained checkout count is zero.

## Results

| Measure | Result |
|---|---:|
| External mathematical fixtures | 9 |
| Expected provider cases | 8 |
| Recall@1 | 6/8 (75%) |
| Recall@5 | 8/8 (100%) |
| Recall@10 | 8/8 (100%) |
| Recall@20 | 8/8 (100%) |
| Critical false acceptance | 0 |
| Case-specific production branches | 0 |
| Retained external source | 0 |

Defect ledger at this checkpoint:

```text
Discovered defects:              28
Fixed:                           27
Verified fixed:                  27
Deferred:                         1
Known limitations:                1
Critical false acceptance open:   0
```

Provider retrieval is candidate discovery only. Most reference fixtures remain
`RECONSTRUCTION_UNRESOLVED` because domain, normalization, truncation, or
provider-contract obligations were not independently discharged. That is an
intentional fail-closed outcome, not a validation failure hidden as success.

## Platform matrix

| Platform | RC status |
|---|---|
| Windows | Executed |
| Linux | Not executed: environment unavailable on this host |
| macOS | Out of v1 scope |

## Open RC gates

- Linux validation has not run.
- The project license has not received its final maintainer decision.

The Python wheel was built and inspected after making `wheel` an explicit build
requirement. It contains 61 entries, no DOCX, and one packaged `LICENSE`. The
license payload remains the abbreviated tracked text, so artifact construction
passes while the legal-text gate stays open. See
[`packaging-audit.json`](../../output/release_candidate/packaging-audit.json).

The authoritative result is
The private-corpus release summary is generated locally and is not distributed.
Public sanitization gates are described in
[`repository-sanitization-report.md`](../security/repository-sanitization-report.md).
No `RC_READY` status is emitted while either gate remains open.
