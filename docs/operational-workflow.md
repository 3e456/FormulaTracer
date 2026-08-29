# Standard operational audit workflow

FormulaTracer's primary workflow is code-first. A declared Theory is optional and is never substituted for mathematics reconstructed independently from code.

1. Select the source, function/root, and output.
2. Run the FormulaTracer audit.
3. Inspect the reconstructed mathematics.
4. Inspect the exact or non-exact relation and status.
5. Review assumptions and unresolved facts.
6. Review proof obligations and evidence levels.
7. Review error and range evidence; distinguish certified from estimated or empirical claims.
8. Trace claims through provenance and source locations.
9. Review every unresolved material operation.
10. Save the AuditBundle with source revision and environment provenance.
11. Optionally compare the reconstructed result with a separately declared Theory.

## Reviewer checklist

- Does the reconstructed formula match the code?
- Are material operations unresolved or opaque?
- Is the relation exact, assumption-qualified, approximate, discretized, or unresolved?
- Which assumptions and obligations remain?
- Are error/range claims certified, estimated, empirical, or unavailable?
- Can each material claim be traced to source?
- Should the AuditBundle be retained with the research record?

`examples/operational_audit` supplies independent synthetic exact, relational, and unresolved cases and is executed by CI. Store private AuditBundles outside the public repository with the audited source revision, environment, semantic result, and provenance. Do not commit research data merely to preserve an audit record.
