from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import jsonschema
from referencing import Registry, Resource

from formulatracer import (ExpressionTarget, FormulaTracer, OutputTargetKind,
                           PythonDependencyResolver, VariableTarget)


class ProjectAnalyzerTests(unittest.TestCase):
    def project(self, files: dict[str, str]) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='0.0.0'\n", encoding="utf-8")
        for name, text in files.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return temporary, root

    def test_e2e_a_multilevel_relative_import_and_reexport(self) -> None:
        tmp, root = self.project({
            "package/__init__.py": "from .constants import SCALE\n",
            "package/constants.py": "SCALE = 60 * 60\nUNUSED = 999\n",
            "package/math.py": "from . import SCALE\ndef weighted(x):\n    return x / SCALE\n",
            "package/model.py": "from .math import weighted\ndef calculate(x):\n    return weighted(x)\n",
            "main.py": "from package.model import calculate\ndef result(x):\n    return calculate(x)\n",
        })
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertEqual({item.name for item in result.modules}, {"main", "package.model", "package.math", "package", "package.constants"})
        deps = set(result.outputs[0].dependencies)
        self.assertIn("package.constants.SCALE", deps)
        self.assertNotIn("package.constants.UNUSED", deps)
        self.assertTrue(any(edge.kind == "RE_EXPORT" for edge in result.project_graph.edges))

    def test_e2e_b_c_independent_then_shared_constant(self) -> None:
        tmp, root = self.project({
            "constants.py": "K = 2\n",
            "main.py": "from constants import K\ndef alpha(x):\n return x*K\ndef beta(y):\n return y+1\n",
        }); self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        relation = result.shared_dependencies[0]
        self.assertEqual(relation["kind"], "DISCONNECTED")
        tmp2, root2 = self.project({
            "constants.py": "K = 2\nUNUSED = 8\n",
            "main.py": "from constants import K\ndef alpha(x):\n return x*K\ndef beta(y):\n return y*K\n",
        }); self.addCleanup(tmp2.cleanup)
        shared = FormulaTracer(root2 / "main.py").analyze().shared_dependencies[0]
        self.assertEqual(shared["kind"], "SHARED_CONSTANT")
        self.assertEqual(shared["symbols"], ["constants.K"])

    def test_e2e_d_shared_error_cause_and_e_multi_output(self) -> None:
        tmp, root = self.project({"main.py":
            "import numpy as np\ndef compute(data):\n d=np.gradient(data)\n a=2*d\n b=5*d\n return a,b\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertEqual([item.name for item in result.roots[0].outputs], ["a", "b"])
        causes = [set(item.error_causes) for item in result.outputs]
        self.assertTrue(causes[0] & causes[1])

    def test_e2e_f_variable_target_final_reaching_definition_and_expression(self) -> None:
        tmp, root = self.project({"main.py":
            "def compute(x):\n intermediate=x*2\n unused=x*999\n intermediate+=3\n final=intermediate*4\n return final\n"})
        self.addCleanup(tmp.cleanup)
        output = FormulaTracer(root / "main.py").analyze(
            [VariableTarget("intermediate", module="main", function="compute")]).outputs[0]
        self.assertEqual(output.formula["op"], "Add")
        self.assertFalse(any("unused" in item for item in output.dependencies))
        expression = FormulaTracer(root / "main.py").analyze(
            [ExpressionTarget("intermediate[0]", module="main", function="compute")]).outputs[0]
        self.assertEqual(expression.formula["op"], "IndexedValue")

    def test_e2e_g_dataset_sink_is_serialization_boundary(self) -> None:
        tmp, root = self.project({"main.py":
            "import xarray as xr\ndef write(x):\n score=x*2\n ds=xr.Dataset()\n ds['score']=score\n ds.to_netcdf('result.nc')\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertEqual(len(result.artifacts), 1)
        artifact = result.artifacts[0]
        self.assertEqual(artifact.format, "netcdf")
        self.assertEqual(artifact.serialization_boundary.status, "SERIALIZATION_SEPARATED_FROM_MATHEMATICAL_IR")
        self.assertEqual(artifact.dataset_outputs[0].name, "score")
        self.assertNotEqual(result.outputs[0].formula.get("name"), "to_netcdf")

    def test_dynamic_import_cycle_and_object_renderers(self) -> None:
        tmp, root = self.project({
            "a.py": "import importlib\nname='b'\nimportlib.import_module(name)\nfrom b import f\ndef g(x): return f(x)\n",
            "b.py": "from a import g\ndef f(x): return x\n",
        }); self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "a.py").analyze()
        codes = {item["code"] for item in result.diagnostics}
        self.assertIn("DYNAMIC_IMPORT_UNRESOLVED", codes)
        self.assertIn("IMPORT_CYCLE_DETECTED", codes)
        self.assertEqual(json.loads(result.to_json())["status"], "PROJECT_UNRESOLVED")
        self.assertIn("FormulaTracer Project Verification Certificate", result.to_latex())

    def test_project_result_and_sink_schemas(self) -> None:
        tmp, root = self.project({"main.py":
            "import numpy as np\ndef save(x):\n y=x+1\n np.save('y.npy', y)\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
        project_schema = json.loads((schema_root / "project-audit-result.schema.json").read_text(encoding="utf-8"))
        registry = Registry()
        for name in ("project-dependency-graph.schema.json", "output-sink.schema.json",
                     "end-to-end-verification-claim.schema.json"):
            child = json.loads((schema_root / name).read_text(encoding="utf-8"))
            registry = registry.with_resource(child["$id"], Resource.from_contents(child))
        jsonschema.Draft202012Validator(project_schema, registry=registry).validate(result.to_dict())

    def test_ambiguous_variable_target(self) -> None:
        tmp, root = self.project({"main.py": "def a():\n x=1\n return x\ndef b():\n x=2\n return x\n"})
        self.addCleanup(tmp.cleanup)
        with self.assertRaisesRegex(Exception, "OUTPUT_VARIABLE_AMBIGUOUS"):
            FormulaTracer(root / "main.py").analyze(["x"])

    def test_ambiguous_import_and_reexport_fail_closed(self) -> None:
        tmp, root = self.project({
            "dual.py": "X=1\n", "dual/__init__.py": "X=2\n",
            "main.py": "from dual import X\ndef compute(): return X\n",
        }); self.addCleanup(tmp.cleanup)
        codes = {item["code"] for item in FormulaTracer(root / "main.py").analyze().diagnostics}
        self.assertIn("AMBIGUOUS_IMPORT", codes)
        tmp2, root2 = self.project({
            "pkg/__init__.py": "from .a import X\nfrom .b import X\n",
            "pkg/a.py": "X=1\n", "pkg/b.py": "X=2\n",
            "main.py": "from pkg import X\ndef compute(): return X\n",
        }); self.addCleanup(tmp2.cleanup)
        codes = {item["code"] for item in FormulaTracer(root2 / "main.py").analyze().diagnostics}
        self.assertIn("AMBIGUOUS_REEXPORT", codes)

    def test_same_approximation_family_has_distinct_cause_ids(self) -> None:
        tmp, root = self.project({"main.py":
            "import numpy as np\ndef first(x): return np.gradient(x)\ndef second(y): return np.gradient(y)\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertTrue(result.outputs[0].error_causes)
        self.assertTrue(result.outputs[1].error_causes)
        self.assertFalse(set(result.outputs[0].error_causes) & set(result.outputs[1].error_causes))

    def test_dotted_import_and_module_result_root(self) -> None:
        tmp, root = self.project({
            "pkg/__init__.py": "", "pkg/model.py": "def scale(x): return x*2\n",
            "main.py": "import pkg.model\nresult=pkg.model.scale(3)\n",
        }); self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertEqual(result.roots[0].entry_symbol, "<module>")
        self.assertEqual(result.outputs[0].formula["op"], "Multiply")

    def test_class_method_sink_fails_closed_without_missing_function_key(self) -> None:
        tmp, root = self.project({"main.py":
            "class Store:\n def save(self, value):\n  value.to_netcdf('result.nc')\n\n"
            "def calculate(x):\n return x * 2\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertIn("SINK_OWNER_UNRESOLVED", {item["code"] for item in result.diagnostics})
        self.assertTrue(result.outputs)

    def test_project_semantic_string_is_not_executed_or_promoted(self) -> None:
        tmp, root = self.project({"main.py":
            "def calculate(x):\n return eval('x + 1')\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "main.py").analyze()
        self.assertIn("SEMANTIC_STRING_UNRESOLVED", {item["code"] for item in result.diagnostics})
        self.assertEqual(result.outputs[0].formula["op"], "OpaqueNumericCall")
        self.assertFalse(result.outputs[0].formula["semantic_string"]["executed_by_analyzer"])


if __name__ == "__main__":
    unittest.main()
