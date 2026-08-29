# Reconstruction artifact preservation

FormulaTracer persists one machine-readable artifact per external
Formula-to-Code-to-Formula case. The artifact is an evidence container, not a
claim that reconstruction succeeded.

Each artifact retains the original Theory IR, native structural quotient,
generation plan, provider-contract projection, relation evidence, assumptions,
and the sealed outcome. When source generation or independent reconstruction
did not happen, the corresponding field remains `null` and
`unavailable_reasons` records why. A missing value is never silently replaced
with the theory expression or provider pattern.

The artifacts also reserve explicit provenance structures for temporary
assignments and loop reductions. Later reconstruction can therefore record
inline/uninline correspondence and loop/Fold/FiniteSum evidence without
changing the schema or discarding source dependencies. Conditions insufficient
to identify a reduction remain unresolved.

`artifact-completeness.json` counts a field as preserved when it either has a
value or an explicit unavailable reason. This is deliberately distinct from
reconstruction completion. The current 21/21 artifact completeness includes 20
unresolved mathematical reconstructions.

Artifacts contain reference IDs, versions, semantic IR, fingerprints, and
FormulaTracer-produced evidence only. External source and copied documentation
are not retained. `artifact_payload_hash` covers the canonical JSON payload
before the hash field is added.

The schema is `schemas/reconstruction-artifact.schema.json`; persisted cases are
under `output/reconstruction/cases/`. Regenerate them with
`tools/write_reconstruction_artifacts.py`.
