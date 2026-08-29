"""Fully synthetic weighted-reduction fixture for public assurance."""

import numpy as np
import cpp_audit as audit


@audit.theory(
    output="weighted_score",
    expression="weighted_score[r] = sum(i=0..I-1, samples[r,i] * (weights[i] * scale))",
)
def calculate_weighted_score(samples, weights):
    one = 1
    scale_denominator = 1000
    scale = one / scale_denominator
    scaled_weights = weights * scale
    weighted_score = np.sum(samples * scaled_weights, axis=1)
    return weighted_score
