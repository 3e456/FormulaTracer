# TeX input and notation resolution

The supported TeX-first MVP covers ordinary arithmetic, fractions, powers,
indexed values, function application, finite/infinite sums, definite integrals,
and limits. The original TeX and source span remain on `MathSurfaceAST`, while
the resolved semantics live in a separate canonical Mathematical IR.

```python
finite = FormulaTracer.from_tex(r"\sum_{i=0}^{N-1} x_i")
infinite = FormulaTracer.from_tex(r"\sum_{n=0}^{\infty} x^n")
integral = FormulaTracer.from_tex(r"\int_{0}^{1} x\,dx")
```

Subscripts and superscripts are contextual. A subscript under an explicit sum
may resolve to a bound index. Repeated implicit indices do not silently enable
Einstein summation:

```python
FormulaTracer.from_tex(r"x_i y_i")  # AMBIGUOUS_IMPLICIT_EINSTEIN_SUMMATION
FormulaTracer.from_tex(r"x_i y_i", assumptions=["einstein"])
```

The second call records an explicit convention; it is not inferred. Symbol
declarations can additionally preserve namespace, scalar/tensor/function role,
shape, named dimensions, and domain. Unsupported application/parenthesis/font
ambiguities are rejected rather than converted to an opaque formula that might
later be verified.

`to_tex()` and `to_dsl()` render from semantic IR. TeX → IR → TeX → IR is tested
for the supported subset; presentation styling is retained on the original
surface node, not treated as mathematical identity.
