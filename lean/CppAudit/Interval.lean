import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Tactic

open scoped BigOperators

namespace CppAudit.Interval

structure Interval where
  lower : ℝ
  upper : ℝ

def Mem (x : ℝ) (i : Interval) : Prop := i.lower ≤ x ∧ x ≤ i.upper

theorem interval_add {x y a b c d : ℝ}
    (hx : Mem x ⟨a, b⟩) (hy : Mem y ⟨c, d⟩) :
    Mem (x + y) ⟨a + c, b + d⟩ := by
  constructor
  · exact add_le_add hx.1 hy.1
  · exact add_le_add hx.2 hy.2

theorem interval_neg {x a b : ℝ} (hx : Mem x ⟨a, b⟩) :
    Mem (-x) ⟨-b, -a⟩ := by
  constructor
  · exact neg_le_neg hx.2
  · exact neg_le_neg hx.1

theorem interval_sub {x y a b c d : ℝ}
    (hx : Mem x ⟨a, b⟩) (hy : Mem y ⟨c, d⟩) :
    Mem (x - y) ⟨a - d, b - c⟩ := by
  constructor
  · exact sub_le_sub hx.1 hy.2
  · exact sub_le_sub hx.2 hy.1

theorem interval_scale {x a B : ℝ} (hx : |x| ≤ B) :
    |a * x| ≤ |a| * B := by
  rw [abs_mul]
  exact mul_le_mul_of_nonneg_left hx (abs_nonneg a)

theorem interval_mul {x y X Y : ℝ}
    (hx : |x| ≤ X) (hy : |y| ≤ Y) (hX : 0 ≤ X) (hY : 0 ≤ Y) :
    |x * y| ≤ X * Y := by
  rw [abs_mul]
  exact mul_le_mul hx hy (abs_nonneg y) hX

theorem interval_abs {x B : ℝ} (hx : |x| ≤ B) :
    Mem |x| ⟨0, B⟩ := ⟨abs_nonneg x, hx⟩

theorem interval_sum {ι : Type} [Fintype ι] (x : ι → ℝ) (l u : ι → ℝ)
    (hx : ∀ i, Mem (x i) ⟨l i, u i⟩) :
    Mem (∑ i, x i) ⟨∑ i, l i, ∑ i, u i⟩ := by
  constructor
  · exact Finset.sum_le_sum fun i _ => (hx i).1
  · exact Finset.sum_le_sum fun i _ => (hx i).2

theorem value_plus_error_enclosure {v e L U eL eU : ℝ}
    (hv : Mem v ⟨L, U⟩) (he : Mem e ⟨eL, eU⟩) :
    Mem (v + e) ⟨L + eL, U + eU⟩ := interval_add hv he

theorem interval_square {x B : ℝ} (hx : |x| ≤ B) (hB : 0 ≤ B) :
    x ^ 2 ≤ B ^ 2 := by
  have hx_lower : -B ≤ x := calc
    -B ≤ -|x| := neg_le_neg hx
    _ ≤ x := neg_abs_le x
  have hx_upper : x ≤ B := le_trans (le_abs_self x) hx
  nlinarith

theorem interval_div_positive_denominator {x y X c : ℝ}
    (hx : |x| ≤ X) (hc : 0 < c) (hy : c ≤ |y|) :
    |x / y| ≤ X / c := by
  rw [abs_div]
  apply (div_le_div_iff₀ (lt_of_lt_of_le hc hy) hc).2
  calc
    |x| * c ≤ X * c := mul_le_mul_of_nonneg_right hx (le_of_lt hc)
    _ ≤ X * |y| := mul_le_mul_of_nonneg_left hy (le_trans (abs_nonneg x) hx)

theorem exact_sub_self (x : ℝ) : x - x = 0 := by ring

end CppAudit.Interval
