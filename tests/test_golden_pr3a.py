from __future__ import annotations

from pathlib import Path
import unittest

from tests.golden.pr3a.fixtures.generate import artifacts
from tests.test_dependency_graph import explicit_fold_ir, if_ir, map_ir

ROOT = Path(__file__).resolve().parent / "golden/pr3a/fixtures"


class PR3AGoldenTests(unittest.TestCase):
    def test_golden_corpus_is_current(self) -> None:
        for name, ir in (("map", map_ir()), ("if_then_else", if_ir()), ("fold_left", explicit_fold_ir())):
            with self.subTest(name=name):
                expected = artifacts(name, ir)
                for filename, content in expected.items():
                    self.assertEqual(content, (ROOT / name / filename).read_text(encoding="utf-8"), filename)


if __name__ == "__main__": unittest.main()
