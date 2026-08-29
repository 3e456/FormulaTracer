from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import jsonschema
import yaml

from cpp_audit.core import AuditError
from cpp_audit.library_contracts import (LibraryContractRegistry, SemanticFamily,
                                         analyze_inventory_coverage, generate_inventory_candidates,
                                         version_matches)
from cpp_audit.python_audit import audit_python


ROOT = Path(__file__).resolve().parents[1]


class LibraryContractTests(unittest.TestCase):
    def audit(self, source: str, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.py"
            path.write_text(source, encoding="utf-8")
            return audit_python(path, mode="REPORT_ONLY", verify_lean=False, **kwargs)

    def test_registry_files_validate_and_every_contract_has_provenance(self) -> None:
        schema = json.loads((ROOT / "schemas/library-contract-registry.schema.json").read_text(encoding="utf-8"))
        for path in (ROOT / "registry/libraries").glob("*.yaml"):
            jsonschema.validate(yaml.safe_load(path.read_text(encoding="utf-8")), schema)
        registry = LibraryContractRegistry.default()
        self.assertGreaterEqual(len(registry.registered_callables()), 80)
        for bindings in registry.bindings.values():
            for binding in bindings:
                self.assertTrue(binding.provenance.official_reference.startswith("https://"))
                self.assertTrue(binding.equivalence_scope["preserve"])

    def test_reference_simple_mapping_wins_resolution_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "registry.yaml").write_text('''
package: demo
version: "1.*"
verified_date: "2026-08-26"
reference_status: REFERENCE_REVIEWED
bindings:
  - callable: demo.sum
    family: AlgorithmInvocation
    bind: {algorithm: source_like_contract}
    resolution_kind: REGISTERED_CONTRACT
    reference: https://example.invalid/detailed
  - callable: demo.sum
    family: Reduction
    bind: {reducer: add}
    resolution_kind: REFERENCE_SIMPLE_MAPPING
    reference: https://example.invalid/simple
''', encoding="utf-8")
            binding = LibraryContractRegistry(root).resolve("demo.sum", "1.2")
        self.assertIsNotNone(binding)
        self.assertEqual(SemanticFamily.REDUCTION.value, binding.family)

    def test_formal_contract_without_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.yaml"
            path.write_text('''
package: demo
version: "1.*"
verified_date: "2026-08-26"
bindings:
  - callable: demo.sum
    family: Reduction
    bind: {reducer: add}
''', encoding="utf-8")
            with self.assertRaisesRegex(AuditError, "REFERENCE_REQUIRED"):
                LibraryContractRegistry(path)

    def test_numpy_xarray_and_dask_sum_share_mathematical_ir(self) -> None:
        numpy = self.audit('''import numpy as np
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x): return np.sum(x)
''')
        xarray = self.audit('''import xarray as xr
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x):
    a = xr.DataArray(x, dims=("i",))
    return a.sum()
''')
        dask = self.audit('''import dask.array as da
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x): return da.sum(x)
''')
        nodes = [item.implementation["outputs"][0]["expression"] for item in (numpy, xarray, dask)]
        self.assertEqual(["Reduce"] * 3, [node["op"] for node in nodes])
        self.assertEqual(["Add"] * 3, [node["reduction"] for node in nodes])
        self.assertEqual([SemanticFamily.REDUCTION.value] * 3, [node["semantic_family"] for node in nodes])

    def test_only_dask_sum_carries_chunked_execution_metadata(self) -> None:
        numpy = self.audit('''import numpy as np
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x): return np.sum(x)
''')
        dask = self.audit('''import dask.array as da
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x): return da.sum(x)
''')
        self.assertEqual("NO_EXECUTION_SEMANTICS", numpy.implementation["execution_ir"]["status"])
        operation = dask.implementation["execution_ir"]["operations"][0]
        self.assertEqual("ChunkedReduction", operation["op"])
        self.assertEqual("MATHEMATICAL_EQUIVALENCE", operation["mathematical_relation"])
        self.assertEqual("FLOATING_REDUCTION_ORDER_DIFFERS", operation["floating_point_relation"])
        schema = json.loads((ROOT / "schemas/execution-ir.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(dask.implementation["execution_ir"], schema)

    def test_random_generators_normalize_to_distribution_not_sequence_identity(self) -> None:
        result = self.audit('''import numpy as np
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate():
    first = np.random.default_rng(1)
    second = np.random.default_rng(2)
    return (first.uniform(0, 1, size=3), second.uniform(0, 1, size=3))
''')
        tuple_node = result.implementation["outputs"][0]["expression"]
        samples = tuple_node["args"]
        self.assertEqual(["RandomSample", "RandomSample"], [item["op"] for item in samples])
        self.assertEqual(["uniform", "uniform"], [item["distribution"]["name"] for item in samples])
        self.assertTrue(all(item["equivalence"]["distribution"] == "DISTRIBUTION_EQUIVALENT" for item in samples))
        self.assertTrue(all(item["equivalence"]["sequence"] == "SEQUENCE_IDENTICAL_NOT_CLAIMED" for item in samples))

    def test_dask_delayed_recurses_into_local_python_function(self) -> None:
        result = self.audit('''from dask import delayed
import cpp_audit as audit
def numeric(x):
    temporary = x * 2
    return temporary
@audit.theory(output="y", expression="y = x * 2")
def calculate(x):
    return delayed(numeric)(x)
''')
        self.assertNotIn("OpaqueNumericCall", result.renderings["json"])
        self.assertTrue(any(item["op"] == "ParallelTask" for item in result.implementation["execution_ir"]["operations"]))
        self.assertTrue(any(item["classification"] == "inlined_user_function" for item in result.output_slice["calls"]))

    def test_dask_client_submit_recurses_into_submitted_function(self) -> None:
        result = self.audit('''from dask.distributed import Client
import cpp_audit as audit
def numeric(x): return x + 4
@audit.theory(output="y", expression="y = x + 4")
def calculate(x):
    client = Client()
    return client.submit(numeric, x)
''')
        self.assertNotIn("OpaqueNumericCall", result.renderings["json"])
        self.assertTrue(any(item["op"] == "ParallelTask" for item in result.implementation["execution_ir"]["operations"]))

    def test_unknown_python_function_falls_back_to_source_analysis(self) -> None:
        result = self.audit('''import cpp_audit as audit
def local_numeric(x): return x + 1
@audit.theory(output="y", expression="y = x + 1")
def calculate(x): return local_numeric(x)
''')
        self.assertTrue(result.comparison["match"])
        self.assertNotIn("OpaqueNumericCall", result.renderings["json"])

    def test_imported_local_python_function_falls_back_to_source_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "helpers.py").write_text("def scale(x):\n    return x * 3\n", encoding="utf-8")
            source = root / "research.py"
            source.write_text('''from helpers import scale
import cpp_audit as audit
@audit.theory(output="y", expression="y = x * 3")
def calculate(x): return scale(x)
''', encoding="utf-8")
            result = audit_python(source, mode="REPORT_ONLY", verify_lean=False)
        self.assertTrue(result.comparison["match"])
        self.assertNotIn("OpaqueNumericCall", result.renderings["json"])
        spans = result.implementation["source_correspondence"][0]["source_spans"]
        self.assertTrue(any(str(item["file"]).endswith("helpers.py") for item in spans))

    def test_unresolved_native_call_remains_opaque(self) -> None:
        result = self.audit('''import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x): return native_extension.kernel(x)
''')
        self.assertEqual("OpaqueNumericCall", result.implementation["outputs"][0]["expression"]["op"])

    def test_version_mismatch_never_uses_contract(self) -> None:
        result = self.audit('''import numpy as np
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x): return np.sum(x)
''', library_versions={"numpy": "1.0.0"})
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("OpaqueNumericCall", expression["op"])
        self.assertIn("LIBRARY_CONTRACT_VERSION_MISMATCH", {item["code"] for item in result.diagnostics})

    def test_inventory_candidate_without_reference_is_never_verified(self) -> None:
        inventory = {"apis": [{"package": "vendor", "version": "1.0", "qualified_callable": "vendor.magic",
                                "call_count": 4, "usage_file_count": 2, "numeric": True,
                                "numeric_classification": "NEEDS_CONTRACT"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(inventory), encoding="utf-8")
            payload = generate_inventory_candidates(path)
        candidate = payload["candidates"][0]
        self.assertEqual("NEEDS_REVIEW", candidate["status"])
        self.assertNotIn("reference_status", candidate)
        self.assertNotIn("official_reference", candidate)

    def test_version_selector(self) -> None:
        self.assertTrue(version_matches("2.4.4", ">=2.0,<3.0"))
        self.assertFalse(version_matches("1.26.0", ">=2.0,<3.0"))

    def test_numpy_function_and_ndarray_method_normalize_identically(self) -> None:
        result = self.audit('''import numpy as np
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x):
    a = np.asarray(x)
    return (np.sum(a), a.sum())
''', library_versions={"numpy": "2.4.4"})
        values = result.implementation["outputs"][0]["expression"]["args"]
        self.assertEqual(["Reduce", "Reduce"], [item["op"] for item in values])
        self.assertEqual(["Add", "Add"], [item["reduction"] for item in values])
        self.assertEqual(["numpy.sum", "numpy.ndarray.sum"], [item["api"] for item in values])

    def test_pandas_aggregation_and_chain_are_atomic_contracts(self) -> None:
        result = self.audit('''import pandas as pd
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x):
    frame = pd.DataFrame(x)
    return frame.copy().fillna(0).clip(0, 1).sum()
''', library_versions={"pandas": "3.0.2"})
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("Aggregation", expression["op"])
        names = [item["callable"] for item in result.implementation["library_contracts"]]
        self.assertIn("pandas.DataFrame.copy", names)
        self.assertIn("pandas.DataFrame.fillna", names)
        self.assertIn("pandas.DataFrame.clip", names)
        self.assertIn("pandas.DataFrame.sum", names)
        self.assertNotIn("pandas.DataFrame.copy.fillna.clip.sum", names)

    def test_pandas_grouping_has_separate_group_and_aggregation_nodes(self) -> None:
        result = self.audit('''import pandas as pd
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x):
    frame = pd.DataFrame(x)
    return frame.groupby("region").sum()
''', library_versions={"pandas": "3.0.2"})
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("Aggregation", expression["op"])
        self.assertEqual("Grouping", expression["args"][0]["op"])

    def test_xarray_align_preserves_named_alignment_contract(self) -> None:
        result = self.audit('''import xarray as xr
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(a, b): return xr.align(a, b, join="inner")
''', library_versions={"xarray": "2026.4.0"})
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("Alignment", expression["op"])
        self.assertTrue(any(item.get("dimension_names_preserved") for item in expression["alignment_constraints"]))

    def test_scipy_nearest_neighbor_and_shortest_path_are_relations(self) -> None:
        nearest = self.audit('''from scipy.spatial import cKDTree
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(points, query):
    tree = cKDTree(points)
    return tree.query(query)
''', library_versions={"scipy": "1.17.1"})
        shortest = self.audit('''from scipy.sparse.csgraph import dijkstra
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(graph): return dijkstra(graph, directed=False)
''', library_versions={"scipy": "1.17.1"})
        self.assertEqual("nearest_neighbor_query", nearest.implementation["outputs"][0]["expression"]["binding"]["algorithm"])
        self.assertEqual("shortest_path_relation", shortest.implementation["outputs"][0]["expression"]["binding"]["algorithm"])

    def test_gis_coordinate_transform_retains_crs_arguments(self) -> None:
        result = self.audit('''import geopandas as gpd
import cpp_audit as audit
@audit.theory(output="y", expression="y = x")
def calculate(x):
    frame = gpd.GeoDataFrame(x, crs="EPSG:4326")
    return frame.to_crs("EPSG:3857")
''', library_versions={"geopandas": "1.1.3"})
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("SpatialGeometry", expression["op"])
        self.assertEqual("coordinate_transform", expression["binding"]["relation"])
        self.assertIn("EPSG:3857", json.dumps(expression))

    def test_shapely_spatial_predicate_uses_geometry_family(self) -> None:
        result = self.audit('''from shapely.geometry import Point
from shapely import contains_xy
import cpp_audit as audit
@audit.theory(output="result", expression="result = x")
def calculate(x, y_coord):
    point = Point(x, y_coord)
    return contains_xy(point, x, y_coord)
''', library_versions={"shapely": "2.1.2"})
        expression = result.implementation["outputs"][0]["expression"]
        self.assertEqual("SpatialGeometry", expression["op"])
        self.assertEqual("contains_point_coordinates", expression["binding"]["relation"])

    def test_inventory_chain_decomposition_and_non_numeric_reclassification(self) -> None:
        registry = LibraryContractRegistry.default()
        chain = registry.resolve_chain("pandas.DataFrame.copy.apply.fillna.clip.sum", {"pandas": "3.0.2"})
        self.assertEqual("SUPPORTED", chain["status"])
        self.assertEqual(5, len(chain["operations"]))
        inventory = {"packages": [{"package": "pandas", "version": "3.0.2"}], "apis": [
            {"package": "pandas", "version": "3.0.2", "qualified_callable": "pandas.DataFrame.to_sql",
             "call_count": 1, "usage_file_count": 1, "numeric": True, "numeric_classification": "NEEDS_CONTRACT"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(inventory), encoding="utf-8")
            coverage = analyze_inventory_coverage(path, registry)
        self.assertEqual(1, coverage["counts"]["NON_NUMERIC"])

    def test_reference_determined_return_type_is_loaded(self) -> None:
        binding = LibraryContractRegistry.default().resolve("xarray.DataArray.values", "2026.4.0")
        self.assertIsNotNone(binding)
        self.assertEqual("numpy.ndarray", binding.return_type["kind"])
        self.assertEqual("REFERENCE_DETERMINED", binding.return_type["evidence"])

    def test_input_type_determines_pandas_concat_groupby_chain(self) -> None:
        chain = LibraryContractRegistry.default().resolve_chain(
            "pandas.concat.groupby.sum", {"pandas": "3.0.2"},
            {"input_types": ["pandas.DataFrame"], "evidence": "INPUT_TYPE_DETERMINED"},
        )
        self.assertEqual("SUPPORTED", chain["status"])
        self.assertEqual(["pandas.concat", "pandas.DataFrame.groupby",
                          "pandas.api.typing.DataFrameGroupBy.sum"],
                         [item["callable"] for item in chain["operations"]])

    def test_receiver_propagates_through_pandas_numeric_chain(self) -> None:
        chain = LibraryContractRegistry.default().resolve_chain(
            "pandas.to_numeric.fillna.clip", {"pandas": "3.0.2"},
            {"input_types": ["pandas.Series"], "evidence": "INPUT_TYPE_DETERMINED"},
        )
        self.assertEqual("SUPPORTED", chain["status"])
        self.assertEqual("pandas.Series", chain["type_info"]["kinds"][0])
        self.assertIn("RECEIVER_PROPAGATION", chain["mechanisms"])

    def test_xarray_concat_input_type_propagates_to_isel_where(self) -> None:
        chain = LibraryContractRegistry.default().resolve_chain(
            "xarray.concat.isel.where", {"xarray": "2026.4.0"},
            {"input_types": ["xarray.DataArray"], "evidence": "INPUT_TYPE_DETERMINED",
             "labels": True},
        )
        self.assertEqual("SUPPORTED", chain["status"])
        self.assertEqual("xarray.DataArray", chain["type_info"]["kinds"][0])
        self.assertTrue(chain["type_info"]["labels"])

    def test_dask_backed_xarray_is_not_resolved_as_dask_array_api(self) -> None:
        context = {"receiver_type": "xarray.DataArray", "namespace_segments": 2,
                   "evidence": "STATICALLY_CONSTRAINED", "backend": "dask.array.Array",
                   "lazy": True, "mechanisms": ["NAMESPACE_CORRECTION"]}
        chain = LibraryContractRegistry.default().resolve_chain(
            "dask.array.isel.where.max", {"dask": "2026.3.0", "xarray": "2026.4.0"}, context)
        self.assertEqual("SUPPORTED", chain["status"])
        self.assertTrue(all(item["package"] == "xarray" for item in chain["operations"]))
        self.assertEqual("dask.array.Array", chain["type_info"]["backend"])
        self.assertTrue(chain["type_info"]["lazy"])

    def test_csr_property_propagates_to_numpy_cast(self) -> None:
        chain = LibraryContractRegistry.default().resolve_chain(
            "scipy.sparse.csr_matrix.indices.astype",
            {"scipy": "1.17.1", "numpy": "2.4.4"})
        self.assertEqual("SUPPORTED", chain["status"])
        self.assertEqual(["scipy.sparse.csr_matrix.indices", "numpy.ndarray.astype"],
                         [item["callable"] for item in chain["operations"]])
        self.assertIn("PROPERTY_PROPAGATION", chain["mechanisms"])

    def test_ambiguous_receiver_fails_closed_without_input_evidence(self) -> None:
        chain = LibraryContractRegistry.default().resolve_chain(
            "xarray.concat.isel", {"xarray": "2026.4.0"})
        self.assertEqual("NEEDS_CONTRACT", chain["status"])
        self.assertEqual("AMBIGUOUS_RECEIVER_TYPE", chain["reason"])
        self.assertEqual("AMBIGUOUS", chain["type_info"]["evidence"])

    def test_unknown_receiver_and_version_mismatch_fail_closed(self) -> None:
        registry = LibraryContractRegistry.default()
        unknown = registry.resolve_chain("vendor.result.sum")
        mismatch = registry.resolve_chain(
            "xarray.concat.isel", {"xarray": "1.0.0"},
            {"input_types": ["xarray.DataArray"], "evidence": "INPUT_TYPE_DETERMINED"})
        self.assertEqual("UNKNOWN_RECEIVER_TYPE", unknown["reason"])
        self.assertEqual("UNKNOWN", unknown["type_info"]["evidence"])
        self.assertEqual("NEEDS_CONTRACT", mismatch["status"])
        self.assertFalse(mismatch["operations"])

    def test_public_synthetic_inventory_type_fixture_resolves_recorded_chains(self) -> None:
        inventory = {
            "packages": [{"package": "dask", "version": "2026.3.0"}],
            "apis": [{
                "package": "dask",
                "version": "2026.3.0",
                "qualified_callable": "dask.array.isel.max",
                "call_count": 2,
                "usage_file_count": 1,
                "numeric": True,
                "numeric_classification": "AUTO_EXTRACTABLE",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-inventory.json"
            path.write_text(json.dumps(inventory), encoding="utf-8")
            coverage = analyze_inventory_coverage(path)
        self.assertEqual(1, sum(coverage["counts"].values()))
        self.assertEqual(0, coverage["counts"]["NEEDS_CONTRACT"])
        self.assertEqual(1, coverage["resolution_metrics"]["dask_xarray_namespace_corrections"])
        self.assertEqual(1, coverage["resolution_metrics"]["resolved_from_baseline"])
        dask_rows = [row for row in coverage["apis"] if row["package"] == "dask"
                     and row.get("type_context", {}).get("receiver_type") == "xarray.DataArray"]
        self.assertTrue(all(row["type_info"]["backend"] == "dask.array.Array" for row in dask_rows))


if __name__ == "__main__":
    unittest.main()
