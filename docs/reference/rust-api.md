# Rust API and native CLI

`formulatracer-core` is the semantic source of truth and requires Rust 1.85 or
newer (edition 2021). It exposes `Formula`, `SemanticDocument`,
`VerificationResult`, `ReconstructionRequest`, `ReconstructionResult`,
`MathematicalFunction`, `AuditBundle`, relation/evidence structures, and
canonical serialization/rendering.

```rust
use formulatracer_core::Formula;

let a = Formula::from_json(r#"{"op":"Constant","value":42,"radix":16}"#)?;
let b = Formula::from_json(r#"{"op":"Constant","value":42,"radix":10}"#)?;
let result = a.verify_against(&b);
assert_eq!(result.status, "EXACT_EQUALITY");
```

Run the independent example with
`cargo run --manifest-path examples/rust_native/Cargo.toml`. Python is not
required. The future crates.io package is metadata-ready but is not published.

`formulatracer-native` supports `canonicalize FILE`, `tex FILE`, and
`compare THEORY IMPLEMENTATION`. These operate on versioned semantic documents;
the CLI does not currently orchestrate a complete Rust-source project audit.
