import Std.Internal.Rat

namespace CppAudit.Semantics.FloatingPoint

/-- An abstract rounding function; no concrete IEEE implementation is trusted here. -/
structure RoundingContract where
  round : Std.Internal.Rat → Std.Internal.Rat
  errorBound : Std.Internal.Rat → Std.Internal.Rat
  nonnegativeBound : ∀ value, 0 ≤ errorBound value
  bounded : ∀ value, -(errorBound value) ≤ round value - value ∧
                         round value - value ≤ errorBound value

def evaluatedAdd (contract : RoundingContract) (left right : Std.Internal.Rat) : Std.Internal.Rat :=
  contract.round (left + right)

def evaluatedMul (contract : RoundingContract) (left right : Std.Internal.Rat) : Std.Internal.Rat :=
  contract.round (left * right)

theorem evaluated_add_within_contract (contract : RoundingContract) (left right : Std.Internal.Rat) :
    -(contract.errorBound (left + right)) ≤ evaluatedAdd contract left right - (left + right) ∧
      evaluatedAdd contract left right - (left + right) ≤ contract.errorBound (left + right) := by
  exact contract.bounded (left + right)

theorem exact_rounding_recovers_mathematics
    (contract : RoundingContract) (exact : ∀ value, contract.round value = value)
    (left right : Std.Internal.Rat) : evaluatedAdd contract left right = left + right := by
  exact exact (left + right)

end CppAudit.Semantics.FloatingPoint
