import numpy as np

from native_ext import scale


def calculate(signal):
    approximate = np.gradient(signal)
    return scale(approximate, 2.0)
