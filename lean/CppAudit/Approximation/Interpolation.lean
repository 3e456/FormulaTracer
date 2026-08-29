import CppAudit.Approximation.Convergence

namespace CppAudit.Approximation

theorem nearest_interpolation_error_bound {f : ℝ → ℝ} {x q L radius : ℝ}
    (hL : 0 ≤ L) (hr : |q - x| ≤ radius)
    (lipschitz : |f q - f x| ≤ L * |q - x|) :
    |f q - f x| ≤ L * radius := by
  exact lipschitz.trans (mul_le_mul_of_nonneg_left hr hL)

theorem linear_interpolation_error_bound_from_remainder
    {implementation exact M h : ℝ} (hM : 0 ≤ M) (hh : 0 ≤ h)
    (remainder : |implementation - exact| ≤ M * h ^ 2 / 8) :
    |implementation - exact| ≤ (M / 8) * h ^ 2 := by
  nlinarith

end CppAudit.Approximation
