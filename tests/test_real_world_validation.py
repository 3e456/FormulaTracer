from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from cpp_audit.real_world_validation import (_json, analyze_inventory, assurance_obligations, inventory_corpus,
                                             metamorphic_validation, mutation_validation, summarize)
from cpp_audit.semantic_debugger import _semantic_signature


ROOT = Path(__file__).resolve().parents[1]


def synthetic_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"; root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='validation-example'\nversion='0.1'\n", encoding="utf-8")
    (root / "model.py").write_text(
        "import numpy as np\n\ndef calculate(x):\n    y = x * 2 + 1\n    return y\n\n"
        "if __name__ == '__main__':\n    print(calculate(2))\n", encoding="utf-8")
    excluded = root / ".venv" / "Lib" / "site-packages"; excluded.mkdir(parents=True)
    (excluded / "ignored.py").write_text("raise RuntimeError('must not scan')\n", encoding="utf-8")
    return root


def test_inventory_analysis_mutation_and_summary_are_fail_closed(tmp_path: Path):
    root = synthetic_corpus(tmp_path); output = tmp_path / "output"; output.mkdir()
    inventory = inventory_corpus(root)
    assert len(inventory["projects"]) == 1
    assert {Path(item["path"]).name for item in inventory["source_files"]} == {"model.py", "pyproject.toml"}
    analyses = analyze_inventory(inventory)
    mutations = mutation_validation(inventory, analyses, output, max_cases=4)
    metamorphic = metamorphic_validation(inventory, analyses, output, max_cases=2)
    obligations = assurance_obligations(mutations, metamorphic)
    summary = summarize(inventory, analyses, mutations, metamorphic, obligations)
    assert summary["status"] == "PRIVATE_CORPUS_VALIDATION_COMPLETED"
    assert not summary["trust_boundary"]["research_code_assumed_correct"]
    assert len(obligations) == 12
    assert mutations["temporary_corpus_removed"] and metamorphic["temporary_corpus_removed"]
    schema = json.loads((ROOT / "schemas" / "real-world-validation-summary.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(summary)


def test_validation_serializer_handles_ast_evidence():
    import ast
    payload = {"diagnostic": ast.parse("sink.save(value)", mode="eval").body}
    assert json.loads(json.dumps(_json(payload)))["diagnostic"] == "sink.save(value)"


def test_mutation_ground_truth_ignores_provenance_only_changes():
    left = {"op": "Constant", "value": 1, "source_span": {"file": "<PRIVATE_CORPUS>/original.py", "begin_line": 9}}
    right = {"op": "Constant", "value": 1, "source_span": {"file": "<TEMP_ROOT>/temporary.py", "begin_line": 3}}
    assert _semantic_signature(left) == _semantic_signature(right)


def test_analysis_progress_is_reported_without_changing_results(tmp_path: Path):
    inventory = inventory_corpus(synthetic_corpus(tmp_path))
    events: list[dict] = []
    analyses = analyze_inventory(inventory, progress=events.append)
    assert len(analyses) == 1
    assert events == [{"stage": "PROJECT_ANALYSIS", "projects_completed": 1,
                       "projects_total": 1, "project_id": inventory["projects"][0]["project_id"],
                       "entries_completed": 1, "elapsed_seconds": events[0]["elapsed_seconds"]}]
    assert events[0]["elapsed_seconds"] >= 0
