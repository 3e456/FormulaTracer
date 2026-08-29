"""Independent synthetic inputs for the public operational example."""

import numpy as np
import cpp_audit as audit


@audit.theory(
    output="weighted_score",
    expression="weighted_score[r] = sum(i=0..N-1, samples[r,i] * weights[i])",
)
def weighted_score(samples, weights):
    products = samples * weights
    weighted_score = np.sum(products, axis=1)
    return weighted_score


def central_difference(function, x, spacing):
    return (function(x + spacing) - function(x - spacing)) / (2 * spacing)


@audit.theory(output="adjusted", expression="adjusted = value")
def opaque_adjustment(value):
    adjusted = external_calibration(value)
    return adjusted
