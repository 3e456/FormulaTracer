# Release checklist

This checklist describes a future release. Nothing in the maintenance workflows publishes artifacts.

1. Start from a clean checkout of the intended commit.
2. Confirm version, changelog, API/schema compatibility classification, and deprecations.
3. Run fast, integration, and manual release-validation workflows.
4. Confirm Python/Rust/C/C++ tests, differential gates, structural assurance, BitVector exhaustive assurance, and Lean checks.
5. Re-audit provider contracts required for the release.
6. Run privacy, secret, local-path, dependency-license, and third-party notice checks.
7. Build Windows/Linux wheels and the sdist through `tools/build_release.py`.
8. Inspect artifact manifests, platform-native isolation, LICENSE, notices, checksums, and unexpected files.
9. Install every wheel in a clean supported environment and run native-only examples.
10. Confirm release blockers are zero and obtain human approval.
11. Create an explicit tag and protected GitHub release only after approval.
12. Publish to PyPI through Trusted Publishing when configured; publish crates only if the crate is designated public.
13. Run post-release clean-install smoke tests and archive manifests/AuditBundles.

Publishing must require an explicit tag, protected environment, and manual approval. Long-lived credentials must not be exposed to pull requests. The workflows committed by this project stop at artifact creation and verification.
