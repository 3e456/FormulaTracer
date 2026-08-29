from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from formulatracer import (CppDependencyResolver, CppEnvironmentResolver,
                           FormulaTracer, ProjectAuditResult, VariableTarget)


ROOT = Path(__file__).resolve().parents[1]


class CppProjectAnalyzerTests(unittest.TestCase):
    def project(self, files: dict[str, str]) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(); root = Path(temporary.name)
        for name, text in files.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
        return temporary, root

    def test_e2e_a_single_source_uses_common_object_result(self) -> None:
        result = FormulaTracer(ROOT / "examples/weighted_sum/weighted_sum_loop.cpp").analyze()
        self.assertIsInstance(result, ProjectAuditResult)
        self.assertEqual(result.outputs[0].formula["op"], "TransformReduce")
        self.assertEqual(result.outputs[0].formula["reduction_order"], "left_to_right")
        self.assertEqual(result.outputs[0].implementation["language"], "cpp")
        self.assertFalse(result.outputs[0].implementation["numeric_execution"]["floating_point_exact_real_equivalence"])

    def test_e2e_b_cmake_multifile_include_and_constants(self) -> None:
        result = FormulaTracer(ROOT / "examples/cpp_project_audit/CMakeLists.txt").analyze()
        self.assertEqual(result.project_graph.metadata["cpp_compilation_environment"]["discovery_status"],
                         "COMPILATION_ENVIRONMENT_RESOLVED")
        self.assertTrue(any(edge.kind == "INCLUDE" and not edge.provenance["system"]
                            for edge in result.project_graph.edges))
        self.assertTrue(any(module.is_package for module in result.modules))
        output = next(item for item in result.outputs if item.name == "result")
        self.assertEqual(output.formula["op"], "Multiply")
        self.assertTrue(any(value.endswith("::TON_SCALE") for value in output.dependencies))
        self.assertTrue(any(value.endswith("::KG_PER_TON") for value in output.dependencies))
        self.assertFalse(any(value.endswith("::UNUSED") for value in output.dependencies))
        self.assertTrue(result.artifacts)

    def test_e2e_c_variable_target_final_mutation(self) -> None:
        tmp, root = self.project({"model.cpp":
            "double calculate(double x){ double intermediate=x*2.0; intermediate+=3.0; return intermediate*4.0; }\n"})
        self.addCleanup(tmp.cleanup)
        output = FormulaTracer(root / "model.cpp").analyze(
            [VariableTarget("intermediate", function="calculate")]).outputs[0]
        self.assertEqual(output.formula["op"], "Add")
        self.assertEqual(output.formula["mutation"], "final_reaching_definition")

    def test_e2e_d_multiroot_disconnected_and_shared_constant(self) -> None:
        tmp, root = self.project({"model.cpp":
            "double alpha(double x){return x*2.0;}\ndouble beta(double y){return y+1.0;}\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "model.cpp").analyze()
        self.assertEqual(result.shared_dependencies[0]["kind"], "DISCONNECTED")
        tmp2, root2 = self.project({"model.cpp":
            "const double K=2.0;\ndouble alpha(double x){return x*K;}\ndouble beta(double y){return y*K;}\n"})
        self.addCleanup(tmp2.cleanup)
        result2 = FormulaTracer(root2 / "model.cpp").analyze()
        self.assertEqual(result2.shared_dependencies[0]["kind"], "SHARED_CONSTANT")

    def test_e2e_e_reduce_keeps_reorderable_float_error(self) -> None:
        result = FormulaTracer(ROOT / "examples/cpp_project_audit/src/model.cpp").analyze()
        output = next(item for item in result.outputs if item.name == "reordered_total")
        self.assertEqual(output.formula["reduction_order"], "reorderable")
        self.assertEqual(output.implementation["execution_ir"]["overall_policy"], "PARALLEL_REORDERABLE")
        component = next(value for value in output.error_components if value["source"] == "PARALLEL_ORDER_ERROR")
        self.assertEqual(component["proof_status"], "UNRESOLVED")

    @staticmethod
    def reduction_signature(formula: dict) -> tuple[str, str]:
        if formula.get("op") == "TransformReduce": return formula.get("reduction", "Add"), formula["transform"]["op"]
        if formula.get("op") == "Reduce": return formula.get("reduction", "Add"), formula["input"]["op"]
        if formula.get("op") == "FiniteSum": return "Add", formula.get("body", {}).get("op", "")
        for value in formula.get("args", []):
            if isinstance(value, dict):
                found = CppProjectAnalyzerTests.reduction_signature(value)
                if found != ("", ""): return found
        return "", ""

    def test_e2e_f_python_rust_cpp_weighted_reduction_canonical_family(self) -> None:
        tmp, root = self.project({
            "python/main.py": "import numpy as np\ndef weighted(quantity,factor): return np.sum(quantity*factor,axis=1)\n",
            "rust/Cargo.toml": "[package]\nname='same'\nversion='0.1.0'\n[dependencies]\nrayon='1'\n",
            "rust/src/lib.rs": "pub fn weighted(values:&[f64],factor:f64)->f64{values.iter().map(|x|x*factor).sum()}\n",
            "cpp/model.cpp": "void weighted(const double* quantity,const double* factor,double* result,int regions,int inputs){for(int r=0;r<regions;++r){double acc=0.0;for(int i=0;i<inputs;++i){acc+=quantity[r*inputs+i]*factor[i];}result[r]=acc;}}\n",
        }); self.addCleanup(tmp.cleanup)
        signatures = {
            self.reduction_signature(FormulaTracer(root / "python/main.py").analyze().outputs[0].formula),
            self.reduction_signature(FormulaTracer(root / "rust/src/lib.rs").analyze().outputs[0].formula),
            self.reduction_signature(FormulaTracer(root / "cpp/model.cpp").analyze().outputs[0].formula),
        }
        self.assertEqual(signatures, {("Add", "Multiply")})

    def test_missing_environment_and_binary_evidence_never_become_proof(self) -> None:
        tmp, root = self.project({"model.cpp": "double calculate(double x){return x*2.0;}\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "model.cpp").analyze()
        codes = {item["code"] for item in result.diagnostics}
        self.assertIn("CPP_COMPILATION_DATABASE_UNRESOLVED", codes)
        self.assertIn("CPP_FRONTEND_ENVIRONMENT_UNAVAILABLE", codes)
        self.assertEqual(result.status, "PROJECT_UNRESOLVED")
        self.assertFalse(result.provenance["runtime_evidence_is_lean_proof"])
        self.assertEqual(result.outputs[0].implementation["frontend_authority"], "PORTABLE_RECOGNIZER_PARTIAL")

    def test_python_pybind11_boundary_and_error_propagation(self) -> None:
        result = FormulaTracer(ROOT / "examples/cross_language_cpp_audit/analysis.py").analyze()
        self.assertEqual(result.outputs[0].formula["op"], "Multiply")
        self.assertTrue(any(edge.kind == "CROSS_LANGUAGE_CALL" for edge in result.project_graph.edges))
        boundary = result.project_graph.metadata["language_boundaries"][0]
        self.assertEqual(boundary["target_language"], "cpp")
        self.assertEqual(boundary["representation_mapping"], "REPRESENTATION_MAPPING_UNRESOLVED")
        sources = {item["source"] for item in result.outputs[0].error_components}
        self.assertIn("DISCRETIZATION_ERROR", sources)
        self.assertIn("CAST_ERROR", sources)

    def test_unresolved_include_macro_and_ambiguous_variable_fail_closed(self) -> None:
        tmp, root = self.project({"model.cpp":
            "#include \"missing.hpp\"\n#define COMPUTE(x) ((x)+1)\n"
            "double a(){double value=1;return value;}\ndouble b(){double value=2;return value;}\n"})
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "model.cpp").analyze()
        codes = {item["code"] for item in result.diagnostics}
        self.assertIn("CPP_INCLUDE_UNRESOLVED", codes)
        self.assertIn("CPP_MACRO_SEMANTICS_UNRESOLVED", codes)
        with self.assertRaisesRegex(Exception, "OUTPUT_VARIABLE_AMBIGUOUS"):
            FormulaTracer(root / "model.cpp").analyze(["value"])

    def test_same_function_names_in_translation_units_keep_distinct_identity(self) -> None:
        tmp, root = self.project({
            "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject(fixture)\n",
            "compile_commands.json": json.dumps([
                {"directory": str(root) if False else ".", "command": "clang++ -c a.cpp", "file": "a.cpp"},
                {"directory": ".", "command": "clang++ -c b.cpp", "file": "b.cpp"}]),
            "a.cpp": "double calculate(double x){return x+1;}\n",
            "b.cpp": "double calculate(double x){return x+2;}\n",
        }); self.addCleanup(tmp.cleanup)
        graph = CppDependencyResolver().resolve(root / "CMakeLists.txt")
        names = [item.canonical_name for item in graph.symbols if item.name == "calculate"]
        self.assertEqual(len(set(names)), 2)

    def test_compilation_environment_and_runtime_evidence_schemas(self) -> None:
        result = FormulaTracer(ROOT / "examples/cpp_project_audit/CMakeLists.txt").analyze()
        schema_root = ROOT / "schemas"
        schema = json.loads((schema_root / "cpp-compilation-environment.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(result.project_graph.metadata["cpp_compilation_environment"])
        runtime_schema = json.loads((schema_root / "runtime-evidence.schema.json").read_text(encoding="utf-8"))
        native = FormulaTracer(ROOT / "examples/weighted_sum/weighted_sum_loop.cpp").analyze()
        self.assertTrue(native.provenance["runtime_evidence"])
        for evidence in native.provenance["runtime_evidence"]:
            jsonschema.Draft202012Validator(runtime_schema).validate(evidence)
            self.assertFalse(evidence["proof_authority"])


if __name__ == "__main__":
    unittest.main()
