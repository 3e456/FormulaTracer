import Mathlib.Analysis.Calculus.Taylor
import Mathlib.Analysis.SpecialFunctions.Pow.Real

namespace CppAudit.Approximation

structure PolynomialErrorBound (error : ℝ → ℝ) where
  constant : ℝ
  order : ℕ
  constant_nonnegative : 0 ≤ constant
  order_positive : 0 < order
  bound : ∀ h, |error h| ≤ constant * |h| ^ order

theorem second_derivative_factorial_coefficient : (((Nat.factorial 2 : ℕ) : ℝ)⁻¹) = 1 / 2 := by
  norm_num [Nat.factorial]

theorem third_derivative_factorial_coefficient : (((Nat.factorial 3 : ℕ) : ℝ)⁻¹) = 1 / 6 := by
  norm_num [Nat.factorial]

/- A mechanically usable Taylor remainder assumption.  The provenance layer
   records the ContDiffOn/iteratedDerivWithin hypotheses that discharge it via
   Mathlib's taylor_mean_remainder_bound; it is never inferred from samples. -/
def TaylorRemainderBound (f : ℝ → ℝ) (x d h M coefficient : ℝ) : Prop :=
  |f (x + h) - f x - h * d| ≤ coefficient * M * |h| ^ 2

def ThirdOrderTaylorRemainderBound
    (f : ℝ → ℝ) (x d d2 h M coefficient : ℝ) : Prop :=
  |f (x + h) - f x - h * d - h ^ 2 / 2 * d2| ≤ coefficient * M * |h| ^ 3

end CppAudit.Approximation
