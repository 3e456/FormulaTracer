# References

FormulaTracer stores reference provenance and compact semantic fixtures, not
external implementation source, in RC benchmark output. Formula and algorithm
references are separated where needed. Accessed 2026-08-27.

## Mathematical and algorithm references

- NIST DLMF, [§1.2 Elementary Algebra](https://dlmf.nist.gov/1.2): mathematical series reference.
- SciPy, [Discrete Fourier transforms](https://docs.scipy.org/doc/scipy/reference/fft.html): public mathematical/API reference.
- SciPy, [`scipy.fft.fft`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.fft.fft.html): provider convention and algorithm reference.
- SciPy, [Integration](https://docs.scipy.org/doc/scipy/reference/integrate.html): quadrature/provider reference.
- Netlib, [LAPACK Users' Guide](https://www.netlib.org/lapack/lug/): linear-algebra algorithm reference.
- Willsey et al., [*egg: Fast and Extensible Equality Saturation*](https://doi.org/10.1145/3434304), POPL 2021: equality-saturation design reference.

The [machine-readable registry](output/release_candidate/reference-registry.json)
contains access dates and retention flags.

## Policy

A citation establishes provenance, not correctness. FormulaTracer independently
reconstructs compact semantics and replays comparison. Reference similarity
cannot promote a claim.
