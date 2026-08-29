# Languages and toolchains

| Language/tool | FormulaTracer role | Required version | End user needs it? |
|---|---|---|---|
| Python | facade, CLI, Python frontend | >= 3.10 | Python distribution only |
| Rust | single semantic core, native CLI | >= 1.85, edition 2021 | No with wheel/native binary |
| C | stable ABI | ABI v1 | compiler only for C consumer build |
| C++ | Clang frontend and RAII wrapper | audited input C++17/20; build C++20 | only for native C++ use |
| LLVM/Clang | C/C++ source frontend | major 18 | optional frontend/developer |
| Lean/mathlib | independent proof layer | 4.19.0 / 4.19.0 | proof developer only |

Implementation language, audited source language, and generated-code language
are independent. Python, Rust, and C++ generation are supported. C generation
is not currently advertised. C/C++ consumers can use semantic documents without
Python; source-to-audit requires the Clang frontend. Rust-source project parsing
exists in the Python-orchestrated project frontend, while the native CLI is
currently limited to semantic-document operations.
