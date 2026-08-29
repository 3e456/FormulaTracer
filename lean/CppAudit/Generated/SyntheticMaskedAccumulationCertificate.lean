import CppAudit.Semantics.ControlFlow

namespace CppAudit.Generated.SyntheticMaskedAccumulationCertificate

def sourceHash : String :=
  "059a53368f2578de5a776387ed22430b3f1da09c37dca20ac058893b161537bd"

def sumN (n : Nat) (f : Nat → Int) : Int :=
  (List.range n).foldl (fun acc i => acc + f i) 0

def implementationExpression (n : Nat) (values mask : Nat → Int) : Int :=
  sumN n (fun i => if mask i > 0 then values i else 0)

def theoryExpression (n : Nat) (values mask : Nat → Int) : Int :=
  sumN n (fun i => if mask i > 0 then values i else 0)

theorem extracted_expression_matches_theory (n : Nat)
    (values mask : Nat → Int) :
    implementationExpression n values mask =
      theoryExpression n values mask := by
  rfl

theorem mutation_step_uses_finite_fold (initial head : Int) (tail : List Int) :
    CppAudit.foldLeft (fun acc value => acc + value) initial (head :: tail) =
      CppAudit.foldLeft (fun acc value => acc + value) (initial + head) tail := by
  exact CppAudit.Semantics.ControlFlow.finite_fold_step initial head tail

end CppAudit.Generated.SyntheticMaskedAccumulationCertificate
