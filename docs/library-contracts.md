# Library Contract Registry

The Library Contract Registry lowers public scientific-library API semantics to
the shared Mathematical Expression IR. It does not inspect library internals
when a matching reference contract exists.

## Resolution order

1. Reference Simple Mapping
2. Reference Detailed Contract
3. Registered Contract
4. explicitly imported local Python source
5. native source analysis, when a resolver can identify authoritative source
6. `OpaqueNumericCall`

Version mismatch is fail-closed: a known callable with no matching version is
not sent through an older adapter. If no version is supplied, the contract
records `VERSION_UNKNOWN`; callers requiring certainty must provide
`library_versions` or `--library-version PACKAGE=VERSION`.

Formal YAML contracts live in `registry/libraries/`. Every binding has an
official reference URL, version selector, verification date, reference status,
semantic family, and equivalence scope. Defined families are `Reduction`,
`ElementwiseFunction`, `ElementwisePredicate`, `ShapeTransform`,
`RepresentationMapping`, `NumericCast`, `IndexSelection`, `AxisMapping`,
`TensorContraction`, `ConditionalSelection`, `Statistics`, `Interpolation`,
`LinearAlgebraRelation`, `GraphAlgorithm`, `SpatialGeometry`, `RandomSample`,
`Distribution`, `AlgorithmInvocation`, `ParallelExecution`, `TableMapping`,
`Grouping`, `Aggregation`, and `Alignment`.

The bulk registry covers NumPy, builtins, xarray, pandas, SciPy, Dask,
GeoPandas, Shapely, pyproj, rasterio, netCDF4, and igraph. Table operations are
not forced into scalar equations: selection, grouping, aggregation, alignment,
and representation changes remain explicit nodes. GIS contracts retain CRS,
ellipsoid, transform, topology, and rasterization parameters where specified by
the public reference.

## Mathematical and execution semantics

NumPy, xarray, and Dask sum bindings all lower to `Reduce(Add, input)`. xarray
adds dimension-name and label-alignment constraints. Dask adds a separate
Execution IR operation such as `ChunkedReduction`; scheduler implementation is
outside the mathematical proof claim. A floating-point Dask reduction records
both `MATHEMATICAL_EQUIVALENCE` and `FLOATING_REDUCTION_ORDER_DIFFERS`.

Execution IR supports `ParallelMap`, `ParallelTask`, `ChunkedArray`,
`ChunkedReduction`, `Rechunk`, `Coarsen`, `Scatter`, `Gather`, `Materialize`, and
`ExecutionBarrier`. `dask.delayed(f)(...)` and `Client.submit(f, ...)` recurse
into an explicitly available local Python function `f`; scheduler internals do
not enter Expression IR.

Random bindings lower to `RandomSample(Distribution(...), shape)`. The
equivalence scope preserves distribution, parameters, population rules, and
shape as applicable, while ignoring the PRNG engine and sample sequence.
Consequently the IR states `DISTRIBUTION_EQUIVALENT` separately from
`SEQUENCE_IDENTICAL_NOT_CLAIMED`.

## Inventory candidates

```console
cpp-audit library-contract-candidates \
  --inventory numeric_library_inventory.json \
  --library-registry registry/libraries \
  --output registry/library_candidates.yaml \
  --coverage-output registry/library_contract_coverage.json \
  --type-evidence registry/inventory_type_evidence.yaml
```

Candidates have status `NEEDS_REVIEW` and no reference verification status.
They are never loaded by `LibraryContractRegistry`, so they cannot affect an
audit until a reviewer adds an official reference and moves a binding into
`registry/libraries/`.

Flattened inventory chains are decomposed through evidence-backed return and
receiver types. `ValueTypeInfo` records container, dimensions, labels, dtype
class, eager/lazy state, and backend when those facts are available. Evidence
is one of `REFERENCE_DETERMINED`, `INPUT_TYPE_DETERMINED`,
`STATICALLY_CONSTRAINED`, `ANNOTATION_DETERMINED`, `AMBIGUOUS`, or `UNKNOWN`.
A chain is supported only if every operation resolves atomically; ambiguous or
unknown receivers fail closed.

Conditional contracts preserve public polymorphism. For example,
`xarray.concat` returns the input xarray type, `pandas.concat` depends on input
objects and axis, and `pandas.to_numeric` returns a Series for Series input but
otherwise an ndarray. `registry/inventory_type_evidence.yaml` contains static
facts extracted from the recorded research call sites and selects these cases;
it is not itself a semantic API contract.

Dask-backed xarray values retain two independent facts: mathematical methods
resolve as xarray operations with named dimensions and label alignment, while
the backend remains lazy `dask.array.Array`. Inventory namespace attribution
does not create fictitious Dask `isel` or `sel` APIs. CSR `data`, `indices`, and
`indptr`, plus pandas/xarray `values`, are property contracts with explicit
return types. Metadata, visualization, string, and output-I/O chains remain
`NON_NUMERIC`.

## Lean boundary

`CppAudit.LibraryMapping` proves representative mappings for cross-library sum,
pandas aggregation, Shapely/GeoPandas spatial predicates, and SciPy shortest
path relations. It does not prove library kernels, xarray internals, Dask
scheduling, native code, dtype behavior, floating-point associativity, or PRNG
algorithms.

`ValueTypeInfo` and receiver propagation are Python-side resolution metadata;
they are deliberately excluded from Lean. Lean continues to check only the
Reference Contract → Semantic Mapping → Mathematical IR boundary.
# Official-reference public API harvest

The verified YAML registry remains the only source of contracts accepted by the
auditor.  `python/cpp_audit/reference_harvester.py` builds a version-pinned
inventory from official Sphinx inventories or official API indexes and emits
review candidates.  It never inserts those candidates into
`LibraryContractRegistry.bindings`.

Resolution is fail-closed and ordered as follows:

1. `REGISTERED_CONTRACT` — reviewed registry entry, accepted by the auditor;
2. `REFERENCE_DETAILED_CONTRACT` — official-reference candidate requiring review;
3. `REFERENCE_SIMPLE_MAPPING` — lower-priority inferred family candidate.

The generated provenance records the requested and documented versions, raw
response SHA-256, parsed-inventory SHA-256, ETag/Last-Modified when supplied,
retrieval time, and parser version.  The comprehensive inventory schema is
`schemas/public-api-inventory.schema.json`; it is intentionally distinct from
the verified library-contract schema.

Generate the inventories with:

```powershell
.\.venv\Scripts\python.exe -m cpp_audit.reference_harvester `
  --specs registry\public_api_reference_specs.json `
  --output registry\generated\public_api `
  --cache <PROJECT_ROOT>/ScientificAuditCache/official-reference
```

Use `--offline` only with an already captured official-reference cache.  A
missing or version-incompatible reference fails the run rather than becoming a
supported contract.

## Reviewed semantic registry

The harvester's final stage builds three separate layers: an API binding, a
`SemanticEquivalenceClass`, and its `SemanticFamily`. The 21 detailed-review
templates are structural reference contracts generated by package and object
kind. They preserve documented parameters and provenance, but deliberately do
not claim member-specific mathematical equivalence. Existing-family proposals
are promoted only through a reviewed operation-level class template or an
existing verified binding; the remainder is classified fail-closed.

Second-stage evidence is fail-closed. Deprecation is `CURRENT` only when the
official page explicitly says so; otherwise it is `DEPRECATED` when an official
directive or reviewed override exists, or `UNKNOWN`. Signatures are resolved in
the order official reference, stub, runtime inspection, documented call
pattern, then `SIGNATURE_UNKNOWN`. Version evidence is recorded as verified,
partially verified, or unverified and is never inferred from a stable URL.

The generated artifacts under `registry/generated/public_api` include the 21
class templates, semantic class registry, API bindings, alias graph, formal
contract alignment, review summary, and updated per-library coverage. The
review overrides in `registry/public_api_reference_review_overrides.yaml` cite
the exact official pages used for explicit deprecation and signatures.

### Existing-family class formalization

Existing-family candidates are refined by semantic subtype and documented
operation identity before promotion. For example, `sum` implementations share
`Reduction(Add)`, SciPy `minimize` uses an optimization-result relation, stats
tests use a statistical-inference relation, and spatial predicates are kept
separate from coordinate transforms. Each generated class contract carries a
LaTeX-ready relation, argument/receiver/return rules, package-version bindings,
official reference URLs and raw-reference hashes.

Unknown signatures do not block a class whose named semantic parameters are
already fixed by its reviewed reference contract. A class that requires a
signature fails closed when that signature is unknown. Public names that are
inherited exception helpers, metadata, configuration, or other non-mathematical
surfaces are `NOT_APPLICABLE`; insufficiently specified numeric mappings are
placed in `source_inspection_candidates.json` without inspecting source or
changing official-reference precedence.

The private research-scale corpus inventory is used only as immutable environment-version evidence.
Documentation-version verification remains separate, so stable Dask and
Rasterio references continue to report `VERSION_UNVERIFIED` even when the
installed private research-scale corpus package version matches the requested version.
