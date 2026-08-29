import CppAudit.Approximation.Convergence

namespace CppAudit.Approximation

noncomputable def forwardDifferenceReal (f : ℝ → ℝ) (x h : ℝ) : ℝ := (f (x + h) - f x) / h
noncomputable def backwardDifferenceReal (f : ℝ → ℝ) (x h : ℝ) : ℝ := (f x - f (x - h)) / h
noncomputable def centralDifferenceReal (f : ℝ → ℝ) (x h : ℝ) : ℝ := (f (x + h) - f (x - h)) / (2 * h)

theorem forward_difference_error_bound {f : ℝ → ℝ} {x h d M : ℝ}
    (hh : 0 < h) (hM : 0 ≤ M)
    (remainder : TaylorRemainderBound f x d h M (1 / 2)) :
    |forwardDifferenceReal f x h - d| ≤ (M / 2) * |h| := by
  have hh0 : h ≠ 0 := ne_of_gt hh
  have heq : forwardDifferenceReal f x h - d =
      (f (x + h) - f x - h * d) / h := by
    field_simp [forwardDifferenceReal, hh0]
    <;> ring
  rw [heq, abs_div, abs_of_pos hh]
  apply (div_le_iff₀ hh).2
  have hrem : |f (x + h) - f x - h * d| ≤ (1 / 2 : ℝ) * M * h ^ 2 := by
    simpa [TaylorRemainderBound, abs_of_pos hh] using remainder
  nlinarith

theorem backward_difference_error_bound {f : ℝ → ℝ} {x h d M : ℝ}
    (hh : 0 < h) (hM : 0 ≤ M)
    (remainder : TaylorRemainderBound f x d (-h) M (1 / 2)) :
    |backwardDifferenceReal f x h - d| ≤ (M / 2) * |h| := by
  have hh0 : h ≠ 0 := ne_of_gt hh
  have heq : backwardDifferenceReal f x h - d =
      -(f (x - h) - f x + h * d) / h := by
    field_simp [backwardDifferenceReal, hh0]
    <;> ring
  rw [heq, abs_div, abs_neg, abs_of_pos hh]
  apply (div_le_iff₀ hh).2
  have hrem0 := remainder
  simp only [TaylorRemainderBound, abs_neg, abs_of_pos hh, neg_sq] at hrem0
  have hrem : |f (x - h) - f x + h * d| ≤ (1 / 2 : ℝ) * M * h ^ 2 := by
    convert hrem0 using 1 <;> ring
  nlinarith

theorem central_difference_error_bound {f : ℝ → ℝ} {x h d d2 M : ℝ}
    (hh : 0 < h) (hM : 0 ≤ M)
    (plus_remainder : ThirdOrderTaylorRemainderBound f x d d2 h M (1 / 6))
    (minus_remainder : ThirdOrderTaylorRemainderBound f x d d2 (-h) M (1 / 6)) :
    |centralDifferenceReal f x h - d| ≤ (M / 6) * |h| ^ 2 := by
  have hh0 : h ≠ 0 := ne_of_gt hh
  let rp := f (x + h) - f x - h * d - h ^ 2 / 2 * d2
  let rm := f (x - h) - f x + h * d - h ^ 2 / 2 * d2
  have heq : centralDifferenceReal f x h - d = (rp - rm) / (2 * h) := by
    field_simp [centralDifferenceReal, rp, rm, hh0]
    <;> ring
  have hrp : |rp| ≤ (1 / 6 : ℝ) * M * |h| ^ 3 := by
    simpa [ThirdOrderTaylorRemainderBound, rp] using plus_remainder
  have hrm : |rm| ≤ (1 / 6 : ℝ) * M * |h| ^ 3 := by
    simpa [ThirdOrderTaylorRemainderBound, rm, abs_neg, sub_eq_add_neg,
      add_comm, add_left_comm, add_assoc] using minus_remainder
  rw [heq, abs_div, abs_of_pos (mul_pos (by norm_num) hh)]
  calc
    |rp - rm| / (2 * h) ≤ (|rp| + |rm|) / (2 * h) := by
      gcongr
      exact abs_sub rp rm
    _ ≤ (((1 / 6 : ℝ) * M * |h| ^ 3) + ((1 / 6 : ℝ) * M * |h| ^ 3)) / (2 * h) := by
      gcongr
    _ = (M / 6) * |h| ^ 2 := by
      rw [abs_of_pos hh]
      field_simp [hh0]
      ring

end CppAudit.Approximation
