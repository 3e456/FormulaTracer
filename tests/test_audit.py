from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from cpp_audit.core import audit, extract_ir, normalize, registry_hash

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "examples/weighted_sum/algorithm.yaml"
LOOP = ROOT / "examples/weighted_sum/weighted_sum_loop.cpp"
INNER = ROOT / "examples/weighted_sum/weighted_sum_inner_product.cpp"
REGISTRY = ROOT / "registry/std"


class AuditTests(unittest.TestCase):
    def test_positive_forms_normalize_identically(self) -> None:
        loop = audit(SPEC, LOOP, registry_root=REGISTRY)
        inner = audit(SPEC, INNER, registry_root=REGISTRY)
        self.assertEqual("PASS", loop.status)
        self.assertEqual("PASS", inner.status)
        self.assertEqual(loop.semantic_graph, inner.semantic_graph)
        self.assertEqual("VERIFIED_WITH_CONTRACT_ASSUMPTIONS", loop.proof_level)

    def test_ir_is_deterministic_and_hashed(self) -> None:
        first = extract_ir(LOOP, registry_root=REGISTRY)
        second = extract_ir(LOOP, registry_root=REGISTRY)
        self.assertEqual(first, second)
        self.assertEqual(64, len(first["source_hash"]))
        self.assertEqual(64, len(registry_hash(REGISTRY)))

    def test_negative_mutations_fail_with_specific_diagnostic(self) -> None:
        original = LOOP.read_text(encoding="utf-8")
        cases = {
            "factor index": ("factor[i]", "factor[r]", "FACTOR_INDEX_MISMATCH"),
            "row-major": ("r * inputs + i", "r + i", "ROW_MAJOR_INDEX_MISMATCH"),
            "short loop": ("i < inputs", "i < inputs - 1", "LOOP_BOUND_MISMATCH"),
            "wrong dimension": ("i < inputs", "i < regions", "REDUCTION_DIMENSION_MISMATCH"),
            "initial value": ("acc = 0.0", "acc = 1.0", "INITIAL_VALUE_MISMATCH"),
            "wrong transform": ("* factor[i]", "+ factor[i]", "TRANSFORM_MISMATCH"),
            "output index": ("result[r]", "result[i]", "OUTPUT_INDEX_MISMATCH"),
            "narrowing": ("double acc", "float acc", "NUMERIC_NARROWING"),
            "external": ("acc +=", "mystery(); acc +=", "UNSUPPORTED_EXTERNAL_FUNCTION"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, (old, new, expected) in cases.items():
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.cpp"
                    path.write_text(original.replace(old, new), encoding="utf-8")
                    result = audit(SPEC, path, registry_root=REGISTRY)
                    self.assertEqual("FAILED", result.status)
                    self.assertIn(expected, {d.code for d in result.diagnostics})

    def test_reduce_is_not_accumulate(self) -> None:
        source = INNER.read_text(encoding="utf-8").replace("std::inner_product", "std::reduce")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reduce.cpp"; path.write_text(source, encoding="utf-8")
            result = audit(SPEC, path, registry_root=REGISTRY)
            self.assertIn("REDUCTION_ORDER_MISMATCH", {d.code for d in result.diagnostics})

    def test_aliasing_is_explicit_contract(self) -> None:
        result = audit(SPEC, LOOP, registry_root=REGISTRY)
        self.assertTrue(any("do not overlap" in item for item in result.assumptions))
        self.assertIn("no_forbidden_alias", result.obligations)

    def test_detects_obvious_call_site_alias(self) -> None:
        source = LOOP.read_text(encoding="utf-8") + "\nvoid caller(std::span<double> buffer, std::span<const double> factor) { weighted_sum(buffer, factor, buffer, 1, 1); }\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alias.cpp"; path.write_text(source, encoding="utf-8")
            result = audit(SPEC, path, registry_root=REGISTRY)
            self.assertIn("FORBIDDEN_ALIAS", {d.code for d in result.diagnostics})

    def test_inner_product_bad_range_and_initial_fail(self) -> None:
        source = INNER.read_text(encoding="utf-8").replace("first + inputs", "first + inputs - 1").replace("0.0);", "1.0);")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad_inner.cpp"; path.write_text(source, encoding="utf-8")
            result = audit(SPEC, path, registry_root=REGISTRY)
            codes = {d.code for d in result.diagnostics}
            self.assertIn("ITERATOR_RANGE_MISMATCH", codes)
            self.assertIn("INITIAL_VALUE_MISMATCH", codes)

    def test_unknown_standard_entity_fails_closed(self) -> None:
        source = LOOP.read_text(encoding="utf-8").replace("acc = 0.0", "acc = std::unknown_api()")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.cpp"; path.write_text(source, encoding="utf-8")
            result = audit(SPEC, path, registry_root=REGISTRY)
            self.assertIn("UNREGISTERED_STANDARD_ENTITY", {d.code for d in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
