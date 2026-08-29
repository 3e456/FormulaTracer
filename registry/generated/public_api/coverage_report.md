# Public API contract harvest coverage

Generated exclusively from the version configuration and official-reference artifacts recorded in provenance.
The research-observed 397/397 baseline is read from the verified registry coverage artifact.
Deprecation markers are not exposed by most Sphinx inventories; unknown status is retained rather than treated as current.

| Library | Public API | Contract target | Existing family | New family | Detailed review | I/O | Metadata | Non-numeric |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| numpy | 2496 | 1798 | 513 | 0 | 1285 | 32 | 604 | 62 |
| pandas | 2112 | 1306 | 322 | 0 | 984 | 31 | 635 | 140 |
| xarray | 1640 | 764 | 331 | 0 | 433 | 293 | 435 | 148 |
| scipy | 4311 | 2629 | 1457 | 0 | 1172 | 24 | 1608 | 50 |
| dask | 1160 | 942 | 200 | 0 | 742 | 30 | 188 | 0 |
| geopandas | 179 | 134 | 134 | 0 | 0 | 10 | 35 | 0 |
| shapely | 702 | 485 | 485 | 0 | 0 | 0 | 217 | 0 |
| pyproj | 427 | 209 | 209 | 0 | 0 | 16 | 202 | 0 |
| rasterio | 709 | 246 | 246 | 0 | 0 | 141 | 322 | 0 |
| netCDF4 | 125 | 3 | 3 | 0 | 0 | 122 | 0 | 0 |
| igraph | 697 | 634 | 104 | 0 | 530 | 18 | 0 | 45 |
| python-builtins | 306 | 200 | 16 | 0 | 184 | 0 | 52 | 54 |

Total public API: **14864**  
Generated contract candidates: **4020**  
Detailed review required: **5330**  
Semantic equivalence families/classes: **240**  
Alias names beyond canonical names: **158**  
Private names excluded: **1296**

## Fail-closed limitations

- Deprecation status unknown from inventory alone: 14864
- Runtime signature unavailable: 14864
- Stable references without an exposed version: 2
- References verified only at compatible major/minor level: 4
- SciPy 1.17.1 uses the official 1.17.0 reference because no patch-specific 1.17.1 reference is published.
- Detailed-review entries are candidates, never silently supported contracts.
## Reviewed registry

- Detailed-review templates: 21 (5330 API bindings)
- Candidate class templates: 1722
- Existing-family candidates: 4020
- Candidate dispositions: {'FORMALIZED': 3877, 'REVIEW_PENDING': 0, 'REFERENCE_INSUFFICIENT': 4, 'NOT_APPLICABLE': 139, 'REJECTED': 0, 'AMBIGUOUS': 0}
- Formal contract objects: 2139
- Formalized public API bindings: 9207
- Semantic equivalence classes: 1837
- Formal-contract inventory alignment: 380/396 (95.96%)
- A class-boundary contract is structural and does not assert member-specific mathematical equivalence.
- REVIEW_PENDING, unknown deprecation, unknown signature, and unverified version states remain fail-closed.

### Per-library reviewed coverage

| Library | Public | Target | Registry contract | Formalized | Pending | Ref insufficient | Semantic class | Deprecated | Unknown signature | Unknown version |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dask | 1160 | 942 | 16 | 941 | 0 | 0 | 942 | 0 | 1160 | 1160 |
| geopandas | 179 | 134 | 10 | 134 | 0 | 0 | 134 | 0 | 179 | 0 |
| igraph | 697 | 634 | 1 | 622 | 0 | 0 | 634 | 0 | 697 | 0 |
| netCDF4 | 125 | 3 | 1 | 3 | 0 | 0 | 3 | 0 | 125 | 0 |
| numpy | 2496 | 1798 | 140 | 1767 | 0 | 0 | 1798 | 2 | 2494 | 0 |
| pandas | 2112 | 1306 | 96 | 1297 | 0 | 0 | 1306 | 0 | 2112 | 0 |
| pyproj | 427 | 209 | 3 | 209 | 0 | 0 | 209 | 0 | 427 | 0 |
| python-builtins | 306 | 200 | 6 | 195 | 0 | 0 | 200 | 0 | 306 | 0 |
| rasterio | 709 | 246 | 2 | 236 | 0 | 0 | 246 | 0 | 709 | 709 |
| scipy | 4311 | 2629 | 13 | 2559 | 0 | 4 | 2629 | 25 | 4309 | 0 |
| shapely | 702 | 485 | 4 | 485 | 0 | 0 | 485 | 0 | 702 | 0 |
| xarray | 1640 | 764 | 71 | 759 | 0 | 0 | 764 | 7 | 1640 | 0 |
