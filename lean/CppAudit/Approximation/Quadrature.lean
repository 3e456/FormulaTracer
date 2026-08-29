import CppAudit.Approximation.Convergence

open scoped BigOperators

namespace CppAudit.Approximation

theorem composite_trapezoidal_error_bound {n : ℕ} {localError : Fin n → ℝ}
    {h M width : ℝ} (hh : 0 ≤ h) (hM : 0 ≤ M)
    (hwidth : width = n * h)
    (local_bound : ∀ i, |localError i| ≤ M * h ^ 3 / 12) :
    |∑ i, localError i| ≤ width * M * h ^ 2 / 12 := by
  calc
    |∑ i, localError i| ≤ ∑ i, |localError i| := Finset.abs_sum_le_sum_abs _ _
    _ ≤ ∑ _i : Fin n, (M * h ^ 3 / 12) := Finset.sum_le_sum fun i _ => local_bound i
    _ = width * M * h ^ 2 / 12 := by
      simp [hwidth]
      ring

end CppAudit.Approximation
