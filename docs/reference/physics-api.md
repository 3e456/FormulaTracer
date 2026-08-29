# Physics Foundation Reference

The searchable canonical entries are generated in
`output/public_function_reference/physics-reference.json` from
`registry/scientific_foundations/physics-v1.json`.

The pack contains vector-calculus definitions (`gradient`, `jacobian`,
`hessian`, `divergence`, `curl_r3`, `laplacian`), integral/action and
conservation structures, rotations/frames/quaternions, transform relations,
conditional theorems, and numerical/provider realizations.

Every entry keeps separate fields for definition, assumptions, relation,
formalization level, Lean theorem, implementation realization, obligations,
and error evidence. `DEFINED`, `THEOREM_REGISTERED`, `LEAN_KERNEL_VERIFIED`,
and `REALIZATION_AVAILABLE` are not interchangeable. Gauss, Stokes, Noether,
frame, regularity, orientation, and convergence assumptions remain explicit.

Examples include a vector-calculus definition, quaternion/rotation
realization, and Fourier/Laplace restriction. A discretization or provider
algorithm remains a non-exact relation even when the mathematical definition
is registered.

