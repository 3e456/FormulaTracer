# Research provenance

`FormulaTracer.analyze()` augments the existing `ProjectDependencyGraph` and
`ProjectAuditResult.provenance` with one `ResearchProvenanceGraph`. Source,
configuration, parameters, environment observations, dependencies, inputs and
fields, Implementation/Mathematical/Algorithm IR, transformations, artifacts,
and verification claims use typed nodes and edges. There is no parallel audit
pipeline.

```python
result = FormulaTracer.from_source("analysis.py").analyze(
    input_artifacts=[InputArtifact.inspect("input.nc", schema=schema)],
    configuration=[ConfigurationParameter("alpha", 0.2, "USER_OVERRIDE")],
)
graph = result.provenance_graph()
summary = result.explain()
```

File content hashing is opt-in and size bounded. Dataset contents are not
embedded in certificates. Modification timestamps are metadata only. Git dirty
state is recorded without failing the audit. Environment and runtime
observations always have `proof_authority=false`.

`DEFAULT_ARGUMENT < CONFIG_FILE < ENVIRONMENT_VARIABLE < CLI_ARGUMENT <
USER_OVERRIDE < DERIVED_PARAMETER` is the deterministic override precedence.
Sensitive values are redacted in the resolution trace.

Declarative `KnowledgePack`, `ProviderPack`, and `DomainPack` manifests can be
loaded with `load_extension_pack(path)`. JSON is always supported and YAML uses
`yaml.safe_load`. Packs are data, never imported Python code. Every entry must
declare evidence, relation kind, domain constraints, and type constraints;
unsafe or incomplete exact entries are rejected before registration.
