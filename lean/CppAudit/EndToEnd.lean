import CppAudit.Interval
import Mathlib.Algebra.Order.BigOperators.Group.Finset
import Mathlib.Tactic

open scoped BigOperators

namespace CppAudit.EndToEnd

open CppAudit.Interval

theorem exact_chain_transitive {theory implementation artifact : ℝ}
    (hTI : theory = implementation) (hIA : implementation = artifact) :
    theory = artifact := hTI.trans hIA

def Subinterval (inner outer : Interval) : Prop :=
  outer.lower ≤ inner.lower ∧ inner.upper ≤ outer.upper

theorem enclosure_chain_transitive {x : ℝ} {first second : Interval}
    (hx : Mem x first) (hsub : Subinterval first second) : Mem x second := by
  exact ⟨hsub.1.trans hx.1, hx.2.trans hsub.2⟩

theorem value_error_enclosure_sound {value error L U eL eU : ℝ}
    (hv : Mem value ⟨L, U⟩) (he : Mem error ⟨eL, eU⟩) :
    Mem (value + error) ⟨L + eL, U + eU⟩ :=
  value_plus_error_enclosure hv he

theorem verified_component_bounds_imply_total_bound
    {ι : Type} [Fintype ι] (component : ι → ℝ) (lower upper : ι → ℝ)
    (complete : ∀ i, Mem (component i) ⟨lower i, upper i⟩) :
    Mem (∑ i, component i) ⟨∑ i, lower i, ∑ i, upper i⟩ :=
  interval_sum component lower upper complete

theorem proof_completeness_sound
    {ι : Type} [Fintype ι] (implementation theory : ℝ)
    (component : ι → ℝ) (lower upper : ι → ℝ)
    (residual_decomposition : implementation - theory = ∑ i, component i)
    (complete : ∀ i, Mem (component i) ⟨lower i, upper i⟩) :
    Mem (implementation - theory) ⟨∑ i, lower i, ∑ i, upper i⟩ := by
  rw [residual_decomposition]
  exact verified_component_bounds_imply_total_bound component lower upper complete

end CppAudit.EndToEnd
