# Clang-derived audit pipeline

`cpp-audit-clang` selects exactly one named function from exactly one
translation unit. LibTooling must find a command for that source in the supplied
`compile_commands.json`; fixed or inferred fallback flags are forbidden.

The visitor records declarations, loops, calls, operators, subscripts, casts,
literals, references and source spans. Calls retain the overload-resolved
canonical declaration and signature. Project IDs derive from function, source
offset and token text rather than AST addresses.

The Python normalizer reads Implementation IR JSON only. It never reopens C++
source. Missing provenance/span, unresolved calls or overloads, unknown casts or
effects, unsupported control flow, unresolved alias classes and unclassified
standard entities prevent graph construction.

For Weighted Sum, loop bounds, indices, accumulator, load/transform/reduction,
store index and nesting are checked from IR facts. `std::inner_product` is
resolved through its canonical declaration and versioned registry adapter;
`std::reduce` produces a reduction-order mismatch.

Generated Lean modules retain the source SHA-256 and prove graph well-formedness,
representation preservation and refinement for the supported abstract integer
model. Non-aliasing, valid ranges and live storage remain named assumptions.
