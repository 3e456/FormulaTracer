import numpy as np

from cpp_audit import theory
from . import KG_PER_TON


@theory(output="weighted_score", expression="weighted_score[r] = sum(i=0..I-1, samples[r,i] * weights[i])")
def calculate_weighted_score(samples, weights):
    scaled = samples / KG_PER_TON
    weighted_score = np.sum(scaled * weights, axis=1)
    return weighted_score
