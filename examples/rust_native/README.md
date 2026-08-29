# Rust-only consumer

This independent Cargo project uses `formulatracer-core` directly. It does not
invoke Python and exercises the same semantic core used by C ABI v1.

```console
cargo run --manifest-path examples/rust_native/Cargo.toml
```

The current native CLI and this API operate on TeX or versioned semantic
documents. Full Rust-source project parsing remains a separate frontend path and
is not claimed by this example.
