# Error and range

FormulaTracer separates exact equality, certified error bounds, certified
interval overlap, empirical tolerance, and unresolved bounds. Error components
retain their source (input uncertainty, discretization, truncation, rounding,
or provider contract) and required assumptions.

An empirical observation cannot produce `CERTIFIED_WITHIN_ERROR_BOUND`.
Interval arithmetic is an enclosure only when each operation and domain
condition is justified. A divisor interval crossing zero, unsupported power,
or missing dependence information creates an obligation or unresolved result.
