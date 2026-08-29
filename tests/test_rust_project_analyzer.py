from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from formulatracer import (FormulaTracer, RustDependencyResolver,
                           RustLibraryContractRegistry, VariableTarget)


ROOT = Path(__file__).resolve().parents[1]


class RustProjectAnalyzerTests(unittest.TestCase):
    def rust_project(self, source: str, manifest_extra: str = ""):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "src").mkdir()
        (root / "Cargo.toml").write_text(
            "[package]\nname='fixture'\nversion='0.1.0'\nedition='2021'\n" + manifest_extra,
            encoding="utf-8")
        (root / "src/main.rs").write_text(source, encoding="utf-8")
        return temporary, root

    def test_e2e_a_cargo_modules_iterator_and_derived_constant(self) -> None:
        result = FormulaTracer(ROOT / "examples/rust_project_audit/Cargo.toml").analyze()
        self.assertEqual({m.language for m in result.modules}, {"rust"})
        self.assertEqual(len(result.modules), 4)
        sequential = next(o for o in result.outputs if o.name == "result")
        self.assertEqual(sequential.formula["op"], "FiniteSum")
        self.assertFalse(any("UNUSED" in dependency for dependency in sequential.dependencies))
        self.assertTrue(any(edge.kind == "CARGO_DEPENDENCY" for edge in result.project_graph.edges))
        workspace = result.project_graph.metadata["cargo_workspace"]
        self.assertEqual(workspace["packages"][0]["name"], "research-audit")

    def test_e2e_b_iterator_and_d_rayon_semantics_are_separate(self) -> None:
        result = FormulaTracer(ROOT / "examples/rust_project_audit/Cargo.toml").analyze()
        parallel = next(o for o in result.outputs if o.name == "parallel_weighted_sum")
        self.assertEqual(parallel.formula["op"], "FiniteSum")
        self.assertEqual(parallel.formula["execution_policy"], "PARALLEL_REORDERABLE")
        self.assertEqual(parallel.formula["reduction_order"], "unspecified_parallel")
        component = next(c for c in parallel.error_components if c["source"] == "PARALLEL_ORDER_ERROR")
        self.assertEqual(component["proof_status"], "UNRESOLVED")
        self.assertEqual(component["bound"]["status"], "BOUND_NOT_EVALUATED")

    def test_e2e_e_f_pyo3_source_is_inlined_with_boundary_error(self) -> None:
        result = FormulaTracer(ROOT / "examples/cross_language_audit/analysis.py").analyze()
        self.assertEqual(result.outputs[0].formula["op"], "Multiply")
        self.assertTrue(any(edge.kind == "CROSS_LANGUAGE_CALL" for edge in result.project_graph.edges))
        boundary = result.project_graph.metadata["language_boundaries"][0]
        self.assertEqual(boundary["resolution_status"], "RUST_SOURCE_RESOLVED")
        self.assertEqual(boundary["representation_mapping"], "REPRESENTATION_MAPPING_UNRESOLVED")
        sources = {component["source"] for component in result.outputs[0].error_components}
        self.assertIn("CAST_ERROR", sources)
        self.assertIn("DISCRETIZATION_ERROR", sources)

    def test_variable_target_uses_final_mutation(self) -> None:
        tmp, root = self.rust_project(
            "fn compute(x: f64) -> f64 { let mut y = x * 2.0; y += 3.0; y }\n")
        self.addCleanup(tmp.cleanup)
        output = FormulaTracer(root / "src/main.rs").analyze(
            [VariableTarget("y", module="fixture", function="compute")]).outputs[0]
        self.assertEqual(output.formula["op"], "Add")

    def test_unknown_macro_unsafe_and_external_crate_fail_closed(self) -> None:
        tmp, root = self.rust_project(
            "use mystery::thing;\npub fn compute(x: f64) -> f64 { unsafe { mystery!(x) } }\n",
            "\n[dependencies]\nmystery='1'\n")
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "Cargo.toml").analyze()
        codes = {item["code"] for item in result.diagnostics}
        self.assertIn("UNSAFE_PROOF_OBLIGATION", codes)
        self.assertTrue(codes & {"MACRO_EXPANSION_UNRESOLVED", "PROC_MACRO_SEMANTICS_UNRESOLVED"})
        self.assertIn("mystery", result.project_graph.external_modules)
        self.assertFalse(any("site-packages" in module.path for module in result.modules))

    def test_missing_module_and_ambiguous_variable_report_diagnostics(self) -> None:
        tmp, root = self.rust_project(
            "mod absent;\nfn a(){ let x=1; }\nfn b(){ let x=2; }\n")
        self.addCleanup(tmp.cleanup)
        result = FormulaTracer(root / "Cargo.toml").analyze()
        self.assertIn("RUST_MODULE_UNRESOLVED", {item["code"] for item in result.diagnostics})
        with self.assertRaisesRegex(Exception, "OUTPUT_VARIABLE_AMBIGUOUS"):
            FormulaTracer(root / "Cargo.toml").analyze(["x"])

    def test_workspace_local_path_dependency_is_source_resolved(self) -> None:
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "Cargo.toml").write_text("[workspace]\nmembers=['app','core']\nresolver='2'\n", encoding="utf-8")
        for name in ("app", "core"): (root / name / "src").mkdir(parents=True)
        (root / "app/Cargo.toml").write_text(
            "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\ncore={path='../core'}\n", encoding="utf-8")
        (root / "app/src/main.rs").write_text("fn main(){ let result=core::scale(2.0); }\n", encoding="utf-8")
        (root / "core/Cargo.toml").write_text("[package]\nname='core'\nversion='0.1.0'\n", encoding="utf-8")
        (root / "core/src/lib.rs").write_text("pub fn scale(x:f64)->f64{x*2.0}\n", encoding="utf-8")
        resolver = RustDependencyResolver()
        graph = resolver.resolve(root / "Cargo.toml")
        workspace = resolver.workspace
        self.assertEqual({p.name for p in workspace.packages}, {"app", "core"})
        self.assertIn("LOCAL_PATH_CRATE", graph.metadata["dependency_kinds"])
        self.assertEqual({m.name for m in graph.modules}, {"app", "core"})

    def test_contract_identity_and_new_schemas(self) -> None:
        registry = RustLibraryContractRegistry()
        self.assertIsNotNone(registry.resolve("std", "Iterator::sum"))
        self.assertIsNone(registry.resolve("other", "Iterator::sum"))
        schema_root = ROOT / "schemas"
        contract_schema = json.loads((schema_root / "rust-library-contract.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(contract_schema).validate(
            registry.resolve("ndarray", "ArrayBase::sum").to_dict())
        result = FormulaTracer(ROOT / "examples/rust_project_audit/Cargo.toml").analyze()
        workspace_schema = json.loads((schema_root / "cargo-workspace.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(workspace_schema).validate(
            result.project_graph.metadata["cargo_workspace"])
        cross = FormulaTracer(ROOT / "examples/cross_language_audit/analysis.py").analyze()
        boundary_schema = json.loads((schema_root / "language-boundary.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(boundary_schema).validate(
            cross.project_graph.metadata["language_boundaries"][0])

    def test_python_rust_equivalence_and_recursive_cycle(self) -> None:
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "python").mkdir(); (root / "rust/src").mkdir(parents=True)
        (root / "python/main.py").write_text("def scale(x):\n return x * 2.0\n", encoding="utf-8")
        (root / "rust/Cargo.toml").write_text("[package]\nname='same'\nversion='0.1.0'\n", encoding="utf-8")
        (root / "rust/src/lib.rs").write_text(
            "pub fn scale(x:f64)->f64{x*2.0}\npub fn first(x:f64)->f64{second(x)}\npub fn second(x:f64)->f64{first(x)}\n",
            encoding="utf-8")
        py = FormulaTracer(root / "python/main.py").analyze().outputs[0].formula
        rust = FormulaTracer(root / "rust/src/lib.rs").analyze().outputs
        rust_scale = next(item.formula for item in rust if item.name == "scale")
        self.assertEqual(py["op"], rust_scale["op"])
        self.assertEqual(py["args"][1], rust_scale["args"][1])
        rust_result = FormulaTracer(root / "rust/src/lib.rs").analyze()
        self.assertTrue(rust_result.project_graph.cycles)

    def test_binary_only_maturin_extension_is_not_source_resolved(self) -> None:
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "pyproject.toml").write_text(
            "[project]\nname='binary-fixture'\nversion='0.1'\n[tool.maturin]\nmodule-name='binary_ext'\n",
            encoding="utf-8")
        (root / "main.py").write_text("import binary_ext\ndef compute(x): return binary_ext.scale(x)\n", encoding="utf-8")
        result = FormulaTracer(root / "main.py").analyze()
        extension = result.project_graph.metadata["native_extensions"][0]
        self.assertEqual(extension["resolution_status"], "BINARY_ONLY")
        self.assertFalse(any(edge.kind == "CROSS_LANGUAGE_CALL" for edge in result.project_graph.edges))
        self.assertEqual(result.outputs[0].formula["op"], "OpaqueNumericCall")


if __name__ == "__main__":
    unittest.main()
