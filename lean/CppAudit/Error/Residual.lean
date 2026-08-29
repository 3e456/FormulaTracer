import Mathlib.Data.Real.Basic
import Mathlib.Data.List.Basic

namespace CppAudit.Error

def residual (implementation theory : ℝ) : ℝ := implementation - theory

def absoluteError (implementation theory : ℝ) : ℝ := |residual implementation theory|

def linf : List ℝ → ℝ
  | [] => 0
  | x :: xs => max |x| (linf xs)

theorem exact_equivalence_has_zero_residual {implementation theory : ℝ}
    (h : implementation = theory) : residual implementation theory = 0 := by
  simp [residual, h]

theorem zero_residual_has_zero_absolute_error {implementation theory : ℝ}
    (h : residual implementation theory = 0) : absoluteError implementation theory = 0 := by
  simp [absoluteError, h]

theorem absolute_error_nonnegative (implementation theory : ℝ) :
    0 ≤ absoluteError implementation theory := by
  exact abs_nonneg _

theorem componentwise_zero_implies_linf_zero (xs : List ℝ)
    (h : ∀ x ∈ xs, x = 0) : linf xs = 0 := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      have hx : x = 0 := h x (by simp)
      have hxs : ∀ y ∈ xs, y = 0 := by
        intro y hy
        exact h y (by simp [hy])
      simp [linf, hx, ih hxs]

theorem absolute_error_triangle (x y : ℝ) : |x + y| ≤ |x| + |y| := by
  exact abs_add x y

end CppAudit.Error
