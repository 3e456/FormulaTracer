import CppAudit.Approximation.ErrorBound
import Mathlib.Topology.MetricSpace.Pseudo.Lemmas

open Filter Topology

namespace CppAudit.Approximation

theorem polynomial_error_bound_implies_convergence {error : ℝ → ℝ}
    (bound : PolynomialErrorBound error) : Tendsto error (𝓝 0) (𝓝 0) := by
  rw [tendsto_zero_iff_abs_tendsto_zero]
  apply squeeze_zero (fun h => abs_nonneg (error h)) bound.bound
  have habs : Tendsto (fun h : ℝ => |h|) (𝓝 0) (𝓝 0) := by
    simpa using (continuous_abs.tendsto' 0 0 abs_zero)
  have hp : Tendsto (fun h : ℝ => |h| ^ bound.order) (𝓝 0) (𝓝 0) := by
    simpa [zero_pow (Nat.ne_of_gt bound.order_positive)] using habs.pow bound.order
  simpa using tendsto_const_nhds.mul hp

end CppAudit.Approximation
