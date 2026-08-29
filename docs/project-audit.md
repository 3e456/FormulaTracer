# Project-wide Python audit

`FormulaTracer` is the primary Phase 9.5 API:

```python
from formulatracer import FormulaTracer, ExpressionTarget, VariableTarget

result = FormulaTracer("analysis/main.py").analyze()
```

`ProjectAnalyzer` orchestrates a `LanguageFrontend` and a
`DependencyResolver`. `PythonFrontend` and `PythonDependencyResolver` are the
implemented backend. `RustFrontend` and `CppFrontend` are explicit fail-closed
extension points; compiler paths and arguments are not part of the normal
public API.

## Static project discovery

The resolver starts at the entry file, finds the nearest project marker
(`pyproject.toml`, `setup.cfg`, or `setup.py`) or the top package boundary, and
resolves local modules without consulting runtime `sys.path`. It recognizes
normal, aliased, `from`, relative, package, multi-level, literal dynamic, and
re-export imports. External packages remain external and flow to the Library
Contract Registry. Non-literal dynamic imports, ambiguous imports/re-exports,
and import cycles produce fail-closed diagnostics. Cyclic graphs are retained
without assuming Python initialization order.

`ProjectDependencyGraph` contains language-neutral `ModuleNode` and
`SymbolNode` values plus `ImportEdge`, `ReExportEdge`, `DefinitionEdge`,
`CallEdge`, and `ValueDependencyEdge` records. Local names and canonical names
are both retained.

## Roots, outputs, and slices

Clear public return-producing entry functions, theory-decorated functions,
unreferenced public return functions, and known I/O sinks become roots. Tuple
returns become distinct outputs. Explicit `VariableTarget` values select the
final reaching definition by default and accept module, function, and source
line selectors. `ExpressionTarget` accepts side-effect-free indexing and slice
expressions. Ambiguous variables fail with `OUTPUT_VARIABLE_AMBIGUOUS`.

Backward evaluation is lazy: only definitions reached from the selected output
enter its slice. Imported functions, constants, and derived constants are
followed across modules; unused constants do not leak into the result.

## I/O boundary

Known `numpy.save`/`savez`, pandas CSV/Parquet, xarray NetCDF, and `json.dump`
calls create `OutputSink` / `ArtifactOutput` values. `SerializationBoundary`
separates the mathematical payload from file formatting, so serializers are
never lowered as mathematical operations. Constant-key dataset assignments are
reported as `DatasetOutput` fields. Unknown calls are not guessed to be sinks.

## Shared semantics and status

Dependencies are intersected before roots are classified as shared or
`DISCONNECTED`. Constants, functions, data sources, intermediates, root
dependencies, and unknown dependence remain distinct. Approximation error
causes use their actual defining source span; two calls from one family are not
merged, while one shared approximation result has one semantic cause ID across
its outputs. Phase 9 error analysis is attached independently per output and no
synthetic project-total error is created.

The result exposes roots, outputs, graph, artifacts, relations, proof status,
diagnostics, and hashes. `to_json()` and `to_latex()` render from that object;
the CLI contains no separate analysis pipeline. Schemas are
`project-audit-result.schema.json`, `project-dependency-graph.schema.json`, and
`output-sink.schema.json`.

## Current boundary

The implementation is a static Python MVP, not a general interprocedural CFG
or Python import-execution emulator. Star imports, computed dynamic imports,
runtime monkey-patching, reflection, descriptor dispatch, and data-dependent
dataset field names remain unresolved. Shape facts from opaque calls are
constraints, not guesses. Rust `mod`/`use`/`pub use` and C++ translation-unit
discovery can reuse the graph and result types through the frontend/resolver
interfaces, but their frontends are not implemented in Phase 9.5.
