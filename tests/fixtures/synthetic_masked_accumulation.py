"""Fully synthetic masked-accumulation fixture for public assurance."""

import numpy as np
import cpp_audit as audit


@audit.theory(
    output="accepted_total",
    expression="accepted_total = sum(i=0..N-1, values[i] if mask[i] > 0 else 0)",
)
def accumulate_masked_values(values, mask, n):
    accepted_total = 0
    for i in range(n):
        accepted_total += np.where(mask[i] > 0, values[i], 0)
    return accepted_total
