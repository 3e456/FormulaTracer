from __future__ import annotations

from pathlib import Path

from cpp_audit import analyze_numeric_types, analyze_parallel_semantics


def source(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "parallel.py"; path.write_text(body, encoding="utf-8"); return path


def analyze(path: Path, inputs=None, dtypes=None):
    types = analyze_numeric_types(path, function="f", inputs=inputs or {}, input_dtypes=dtypes or {})
    return analyze_parallel_semantics(path, function="f", numeric_types=types)


def test_sequential_default(tmp_path: Path):
    result = analyze(source(tmp_path, "def f(x):\n    return x+1\n"), {"x": 1})
    assert result.overall_policy == "SEQUENTIAL" and not result.operations


def test_dask_map_is_deterministic_under_purity(tmp_path: Path):
    path = source(tmp_path, "def numeric(x):\n    return x+1\ndef f(x):\n    return dask.map_blocks(numeric, x)\n")
    result = analyze(path, {"x": [1]}, {"x": "float32"})
    operation = result.operations[0]
    assert operation.policy == "PARALLEL_DETERMINISTIC"
    assert operation.claims["PARALLEL_MAP_EQUIVALENT"] == "ESTABLISHED_UNDER_PURITY_CONTRACT"


def test_dask_reduction_is_reorderable(tmp_path: Path):
    path = source(tmp_path, "def f(x):\n    return da.sum(x)\n")
    result = analyze(path, {"x": [1.0]}, {"x": "float64"})
    assert result.operations[0].policy == "PARALLEL_REORDERABLE"
    assert result.operations[0].claims["PARALLEL_REDUCTION_ORDER_DIFFERS"] == "POSSIBLE"


def test_distributed_submit(tmp_path: Path):
    path = source(tmp_path, "def numeric(x):\n    return x*2\ndef f(x):\n    return client.submit(numeric, x)\n")
    result = analyze(path, {"x": 1})
    assert result.overall_policy == "DISTRIBUTED"


def test_gpu_kernel_classification(tmp_path: Path):
    path = source(tmp_path, "def f(x):\n    return jax.numpy.sum(x)\n")
    result = analyze(path, {"x": [1.0]}, {"x": "float32"})
    assert result.overall_policy == "GPU_PARALLEL"


def test_shared_worker_mutation_detects_race_and_dependency(tmp_path: Path):
    path = source(tmp_path, "state=[]\ndef worker(x):\n    state.append(x)\n    return x\ndef f(xs):\n    return pool.map(worker, xs)\n")
    result = analyze(path, {"xs": [1, 2]})
    assert result.status == "PARALLEL_SEMANTICS_UNRESOLVED"
    assert result.operations[0].claims["POTENTIAL_DATA_RACE"] == "DETECTED"
    assert {item["code"] for item in result.diagnostics} == {"POTENTIAL_DATA_RACE", "CROSS_ITERATION_DEPENDENCY"}


def test_numpy_reduction_marks_backend_policy_unknown(tmp_path: Path):
    path = source(tmp_path, "import numpy as np\ndef f(x):\n    return np.sum(x)\n")
    result = analyze(path, {"x": [1.0]}, {"x": "float64"})
    assert result.overall_policy == "UNKNOWN_EXECUTION_POLICY"
    assert result.claims["NUMERICALLY_REPRODUCIBLE_WITHIN_TOLERANCE"] == "REQUIRES_TOLERANCE_CONTRACT"
