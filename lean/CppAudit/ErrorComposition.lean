import CppAudit.Error.Residual
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Tactic

open scoped BigOperators

namespace CppAudit.ErrorComposition

theorem add_error_bound {δx δy Bx By : ℝ}
    (hx : |δx| ≤ Bx) (hy : |δy| ≤ By) : |δx + δy| ≤ Bx + By := by
  calc
    |δx + δy| ≤ |δx| + |δy| := abs_add δx δy
    _ ≤ Bx + By := add_le_add hx hy

theorem sub_error_bound {δx δy Bx By : ℝ}
    (hx : |δx| ≤ Bx) (hy : |δy| ≤ By) : |δx - δy| ≤ Bx + By := by
  simpa [sub_eq_add_neg] using add_error_bound hx (show |-δy| ≤ By by simpa using hy)

theorem scale_error_bound (a δx Bx : ℝ) (hx : |δx| ≤ Bx) :
    |a * δx| ≤ |a| * Bx := by
  rw [abs_mul]
  exact mul_le_mul_of_nonneg_left hx (abs_nonneg a)

theorem mul_error_bound {x y δx δy X Y Bx By : ℝ}
    (hx : |x| ≤ X) (hy : |y| ≤ Y) (hδx : |δx| ≤ Bx) (hδy : |δy| ≤ By)
    (hX : 0 ≤ X) (hY : 0 ≤ Y) (hBy : 0 ≤ By) :
    |(x + δx) * (y + δy) - x * y| ≤ Y * Bx + X * By + Bx * By := by
  calc
    |(x + δx) * (y + δy) - x * y| = |y * δx + x * δy + δx * δy| := by ring_nf
    _ ≤ |y * δx| + |x * δy| + |δx * δy| := by
      exact le_trans (abs_add _ _) (add_le_add_right (abs_add _ _) _)
    _ = |y| * |δx| + |x| * |δy| + |δx| * |δy| := by simp [abs_mul]
    _ ≤ Y * Bx + X * By + Bx * By := by
      have h1 : |y| * |δx| ≤ Y * Bx := mul_le_mul hy hδx (abs_nonneg δx) hY
      have h2 : |x| * |δy| ≤ X * By := mul_le_mul hx hδy (abs_nonneg δy) hX
      have h3a : |δx| * |δy| ≤ |δx| * By := mul_le_mul_of_nonneg_left hδy (abs_nonneg δx)
      have h3b : |δx| * By ≤ Bx * By := mul_le_mul_of_nonneg_right hδx hBy
      have h3 : |δx| * |δy| ≤ Bx * By := h3a.trans h3b
      linarith

theorem sum_error_bound {ι : Type} [Fintype ι] (δ : ι → ℝ) (B : ι → ℝ)
    (h : ∀ i, |δ i| ≤ B i) : |∑ i, δ i| ≤ ∑ i, B i := by
  calc
    |∑ i, δ i| ≤ ∑ i, |δ i| := Finset.abs_sum_le_sum_abs _ _
    _ ≤ ∑ i, B i := Finset.sum_le_sum fun i _ => h i

theorem mean_error_bound {δsum B : ℝ} {n : ℕ}
    (h : |δsum| ≤ B) (hn : 0 < n) :
    |δsum / (n : ℝ)| ≤ B / (n : ℝ) := by
  have hnR : (0 : ℝ) < (n : ℝ) := by exact_mod_cast hn
  rw [abs_div, abs_of_pos hnR]
  exact (div_le_div_iff_of_pos_right hnR).2 h

theorem linear_map_error_bound (a δx Bx : ℝ) (hx : |δx| ≤ Bx) :
    |a * δx| ≤ |a| * Bx := scale_error_bound a δx Bx hx

theorem linf_sum_bound {ι : Type} (δx δy : ι → ℝ) (Bx By : ℝ)
    (hx : ∀ i, |δx i| ≤ Bx) (hy : ∀ i, |δy i| ≤ By) :
    ∀ i, |δx i + δy i| ≤ Bx + By := by
  intro i
  exact add_error_bound (hx i) (hy i)

theorem linf_to_l1_bound {ι : Type} [Fintype ι] (δ : ι → ℝ) (B : ℝ)
    (h : ∀ i, |δ i| ≤ B) : ∑ i, |δ i| ≤ Fintype.card ι * B := by
  calc
    ∑ i, |δ i| ≤ ∑ _i : ι, B := Finset.sum_le_sum fun i _ => h i
    _ = Fintype.card ι * B := by simp

theorem safe_exact_cancellation (e : ℝ) : e + (-e) = 0 := by
  simp

end CppAudit.ErrorComposition
