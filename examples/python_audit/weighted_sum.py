import numpy as np
import cpp_audit as audit


@audit.theory(
    output="weighted_score",
    expression="weighted_score[r] = sum(i=0..I-1, samples[r,i] * weights[i])",
)
def calculate_weighted_score(samples, weights):
    product = samples * weights
    weighted_score = np.sum(product, axis=1)
    return weighted_score
