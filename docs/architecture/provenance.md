# Native semantic provenance

FormulaTracer treats provenance as semantic evidence, not display metadata.
Kernel E in `formulatracer-core` owns origin-set operations, configuration
resolution, schema comparison, field lineage, and canonical provenance-graph
assembly. Python captures language/runtime observations and projects the native
objects; it does not decide lineage or provenance identity.

`OriginSet` is many-to-many. Union deduplicates every recorded origin,
intersection retains only common evidence, and projection selects an explicitly
named physical source. Canonicalization, alpha-renaming, associative ordering,
temporary elimination, and reduction lowering union origins rather than choosing
the first span. Missing stages are absent or null; no synthetic edge is created.

The native graph can retain source, Implementation IR, Mathematical IR,
Algorithm IR, transformation, provider, relation, proof-obligation, Error IR,
verification claim, and output-artifact nodes. Provider retrieval rank is marked
as non-proof evidence. Non-exact relations remain distinct from exact equality.
Environment and Git facts are observations and never proof authority.

Semantic and physical identity are separate. A graph hash includes physical
provenance for artifact integrity, while mathematical comparison continues to
use the established provenance-ignoring canonical policy. Presentation locale
and serialization order do not establish semantic identity.

Field lineage records input/derived/output field edges without reading research
data content. The private research-scale corpus validation remains read-only and records
`corpus_modified = false` and `research_data_content_read = false`.

