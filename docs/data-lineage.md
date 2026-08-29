# Data lineage and schema audit

`DataLineage` connects input artifacts/fields through numeric transformations
to outputs and serialization boundaries. Field mappings retain named dimensions
and source `OriginSet`s when available. A single source span is never invented
for a many-origin normalization.

`DatasetSchema` and `FieldSchema` record dtype, shape, ordered named dimensions,
coordinates, unit, missing-value semantics, and encoding. Schema comparison
reports field add/remove, dtype/shape/dimension/order/unit/missing-value/encoding
changes independently.

Mathematical payload correctness and serialization correctness are separate
claims. A serializer or schema failure is `SERIALIZATION_DIVERGENCE` or a schema
change; it is not reported as a Theory mismatch.
