"""Generate PR3A golden artifacts exclusively through the Clang 18 frontend."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

import jsonschema

from cpp_audit.dependency import build_dependency_graph, extract_output_slice
from cpp_audit.expression import compare_exact, extract_expression, normalize_exact, render_expression
from cpp_audit.pipeline import run_frontend


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "tests/golden/pr3a/native_clang18"
CASES = {
    "map": "affine_map",
    "if_then_else": "positive_part",
    "fold_left": "sum_values",
    "weighted_sum_loop": "weighted_sum_loop",
    "weighted_sum_inner_product": "weighted_sum_inner_product",
}
ARTIFACT_NAMES = (
    "implementation-ir.json",
    "dependency-graph.json",
    "output-slice.json",
    "expression-ir.json",
    "equation.tex",
    "equation.txt",
    "report.md",
    "semantic-fingerprint.json",
)


class EnvironmentErrorWithCode(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


def _executable(root: Path, name: str) -> Path | None:
    candidates = [root / "bin" / name, root / "bin" / f"{name}.exe"]
    return next((item for item in candidates if item.is_file()), None)


def _version(command: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [str(command), *arguments], capture_output=True, text=True, check=False
    )
    if completed.returncode:
        raise EnvironmentErrorWithCode(
            "LLVM_NOT_FOUND", f"{command} failed: {completed.stderr.strip()}"
        )
    return (completed.stdout or completed.stderr).strip()


def validate_environment(llvm_root: Path, frontend: Path) -> dict[str, str]:
    clang = _executable(llvm_root, "clang")
    clangxx = _executable(llvm_root, "clang++") or _executable(llvm_root, "clang++-18")
    llvm_config = _executable(llvm_root, "llvm-config") or _executable(llvm_root, "llvm-config-18")
    if not clangxx:
        raise EnvironmentErrorWithCode(
            "LLVM_NOT_FOUND", f"clang++ is required below {llvm_root}"
        )
    clang_version = _version(clangxx, "--version").splitlines()[0]
    match = re.search(r"(?:clang version\s+)?(\d+)(?:\.\d+)+", clang_version)
    if not match or int(match.group(1)) != 18:
        raise EnvironmentErrorWithCode("LLVM_VERSION_MISMATCH", clang_version)
    if not llvm_config:
        raise EnvironmentErrorWithCode(
            "LLVM_EXECUTABLES_FOUND_BUT_LIBTOOLING_DEVELOPMENT_PACKAGE_MISSING",
            f"llvm-config is required below {llvm_root}",
        )
    llvm_version = _version(llvm_config, "--version").splitlines()[0]
    if int(llvm_version.split(".", 1)[0]) != 18:
        raise EnvironmentErrorWithCode("LLVM_VERSION_MISMATCH", f"LLVM {llvm_version}")
    required = {
        "LLVM_CMAKE_CONFIG_NOT_FOUND": llvm_root / "lib/cmake/llvm/LLVMConfig.cmake",
        "CLANG_CMAKE_CONFIG_NOT_FOUND": llvm_root / "lib/cmake/clang/ClangConfig.cmake",
    }
    for code, path in required.items():
        if not path.is_file():
            raise EnvironmentErrorWithCode(code, str(path))
    for path in (llvm_root / "include/llvm", llvm_root / "include/clang", llvm_root / "lib"):
        if not path.exists():
            raise EnvironmentErrorWithCode(
                "LLVM_EXECUTABLES_FOUND_BUT_LIBTOOLING_DEVELOPMENT_PACKAGE_MISSING", str(path)
            )
    if not frontend.is_file():
        raise EnvironmentErrorWithCode("CLANG_FRONTEND_BUILD_FAILED", str(frontend))
    return {
        "clang": str(clang or clangxx),
        "clangxx": str(clangxx),
        "clang_version": clang_version,
        "llvm_version": llvm_version,
        "llvm_dir": str(llvm_root / "lib/cmake/llvm"),
        "clang_dir": str(llvm_root / "lib/cmake/clang"),
    }


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _normalize_string(value: str, replacements: list[tuple[str, str]]) -> str:
    normalized = value.replace("\\", "/")
    for raw, marker in replacements:
        candidate = raw.replace("\\", "/").rstrip("/")
        normalized = re.sub(re.escape(candidate), marker, normalized, flags=re.IGNORECASE)
    return normalized


def _normalize(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, replacements) for item in value]
    return _normalize_string(value, replacements) if isinstance(value, str) else value


def _fingerprint(implementation: dict[str, Any], expression: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": implementation["schema_version"],
        "dependency_graph_version": implementation["dependency_graph_version"],
        "function": implementation["function"],
        "nodes": [
            {
                "id": node["id"],
                "kind": node["kind"],
                "effect": node["effect"],
                "semantic_kind": node.get("attributes", {}).get("semantic_kind"),
                "resolved_symbol": node.get("resolved_symbol", ""),
            }
            for node in implementation["nodes"]
        ],
        "edges": [
            {
                "edge_id": edge["edge_id"],
                "kind": edge["kind"],
                "source_node_id": edge["source_node_id"],
                "target_node_id": edge["target_node_id"],
                "argument_role": edge["argument_role"],
            }
            for edge in implementation["dependency_edges"]
        ],
        "analysis": implementation["analysis"],
        "canonical_expression": normalize_exact(expression)["canonical_expression"],
    }


def _compile_database(build: Path, source: Path, compiler: Path) -> None:
    command = {
        "directory": str(build),
        "file": str(source),
        "arguments": [str(compiler), "-std=c++20", "-c", str(source)],
    }
    (build / "compile_commands.json").write_text(_json([command]), encoding="utf-8")


def generate_once(
    output: Path, build_root: Path, llvm_root: Path, frontend: Path, environment: dict[str, str]
) -> dict[str, dict[str, bytes]]:
    schema = json.loads((PROJECT_ROOT / "schemas/implementation-ir.schema.json").read_text(encoding="utf-8"))
    replacements = [
        (str(build_root), "<BUILD_ROOT>"),
        (str(llvm_root), "<LLVM_ROOT>"),
        (str(PROJECT_ROOT), "<PROJECT_ROOT>"),
        (str(frontend.parent), "<FRONTEND_ROOT>"),
    ]
    frontend_hash = _hash_file(frontend)
    result: dict[str, dict[str, bytes]] = {}
    for case, function in CASES.items():
        source = output / case / "source.cpp"
        if not source.is_file():
            raise FileNotFoundError(source)
        build = build_root / case
        build.mkdir(parents=True)
        _compile_database(build, source.resolve(), Path(environment["clangxx"]))
        raw_path = build / "raw-implementation-ir.json"
        implementation = run_frontend(frontend, build, source.resolve(), function, raw_path)
        normalized_command = _normalize_string(
            str(implementation["producer"]["compile_command"]), replacements
        )
        implementation["producer"].update(
            {
                "compile_command": normalized_command,
                "compile_command_hash": sha256(normalized_command.encode()).hexdigest(),
                "llvm_version": environment["llvm_version"],
                "frontend_sha256": frontend_hash,
                "generation_command": (
                    "python scripts/regenerate_pr3a_native_goldens.py "
                    "--llvm-root <LLVM_ROOT> --frontend <FRONTEND_ROOT>/cpp-audit-clang --verify"
                ),
            }
        )
        implementation = _normalize(implementation, replacements)
        jsonschema.validate(implementation, schema)
        graph = build_dependency_graph(implementation)
        output_slice = extract_output_slice(graph)
        expression = extract_expression(implementation, PROJECT_ROOT / "registry/std")
        if graph["status"] != "DEPENDENCY_GRAPH_BUILT":
            raise RuntimeError(f"{case}: {graph['diagnostics']}")
        if output_slice["status"] != "OUTPUT_SLICE_EXTRACTED":
            raise RuntimeError(f"{case}: {output_slice['diagnostics']}")
        if expression["status"] != "EXPRESSION_EXTRACTED":
            raise RuntimeError(f"{case}: {expression['diagnostics']}")
        artifacts = {
            "implementation-ir.json": _json(implementation),
            "dependency-graph.json": _json(graph),
            "output-slice.json": _json(output_slice),
            "expression-ir.json": _json(expression),
            "equation.tex": render_expression(expression, "latex"),
            "equation.txt": render_expression(expression, "unicode"),
            "report.md": render_expression(expression, "markdown"),
            "semantic-fingerprint.json": _json(_fingerprint(implementation, expression)),
        }
        result[case] = {name: content.encode("utf-8") for name, content in artifacts.items()}
    comparison = compare_exact(
        json.loads(result["weighted_sum_loop"]["expression-ir.json"]),
        json.loads(result["weighted_sum_inner_product"]["expression-ir.json"]),
    )
    if not comparison["match"]:
        raise RuntimeError("weighted_sum loop and std::inner_product expressions differ")
    return result


def _compare_runs(left: dict[str, dict[str, bytes]], right: dict[str, dict[str, bytes]]) -> None:
    for case in CASES:
        for name in ARTIFACT_NAMES:
            if left[case][name] != right[case][name]:
                raise EnvironmentErrorWithCode("NATIVE_FRONTEND_NONDETERMINISTIC", f"{case}/{name}")


def _write_or_verify(generated: dict[str, dict[str, bytes]], output: Path, verify: bool) -> int:
    differences: list[str] = []
    for case, artifacts in generated.items():
        directory = output / case
        directory.mkdir(parents=True, exist_ok=True)
        for name, content in artifacts.items():
            destination = directory / name
            if verify:
                if not destination.is_file() or destination.read_bytes() != content:
                    differences.append(f"{case}/{name}")
            else:
                destination.write_bytes(content)
    if differences:
        print("NATIVE_FRONTEND_GOLDEN_MISMATCH", file=sys.stderr)
        for difference in differences:
            print(f"  {difference}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llvm-root", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    llvm_root, frontend, output = args.llvm_root.resolve(), args.frontend.resolve(), args.output.resolve()
    try:
        environment = validate_environment(llvm_root, frontend)
        with tempfile.TemporaryDirectory(prefix="cpp-audit-pr3a-a-") as first, tempfile.TemporaryDirectory(
            prefix="cpp-audit-pr3a-b-"
        ) as second:
            left = generate_once(output, Path(first), llvm_root, frontend, environment)
            right = generate_once(output, Path(second), llvm_root, frontend, environment)
        _compare_runs(left, right)
        status = _write_or_verify(left, output, args.verify)
        if not status:
            print(f"native Clang 18 goldens {'verified' if args.verify else 'written'}: {output}")
        return status
    except EnvironmentErrorWithCode as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, RuntimeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        print(f"CLANG_FRONTEND_BUILD_FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
