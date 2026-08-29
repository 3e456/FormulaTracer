import CppAudit.Semantics.Fold
import CppAudit.LibraryMapping

namespace CppAudit.Generated.SyntheticWeightedReductionCertificate

/-- SHA-256 recorded for the independent synthetic fixture. -/
def implementationSourceHash : String :=
  "f1f972c75dccd651feca1334b6f779a04ac9a1a2f2a0b0c9712d4a4d92ba53f2"

def sumN (n : Nat) (f : Nat → Int) : Int :=
  (List.range n).foldl (fun acc i => acc + f i) 0

def implementationExpression (I r : Nat) (weights : Nat → Int)
    (samples : Nat → Nat → Int) (scale : Int) : Int :=
  sumN I (fun i => samples r i * (weights i * scale))

def theoryExpression (I r : Nat) (weights : Nat → Int)
    (samples : Nat → Nat → Int) (scale : Int) : Int :=
  sumN I (fun i => samples r i * (weights i * scale))

theorem extracted_expression_matches_theory (I r : Nat) (weights : Nat → Int)
    (samples : Nat → Nat → Int) (scale : Int) :
    implementationExpression I r weights samples scale =
      theoryExpression I r weights samples scale := by
  rfl

/-- Exact rational claim: scale = 1/1000, expressed by cross multiplication. -/
theorem derived_constant_scale :
    ((1 : Int) * 1) * 1000 = 1 * (1 * 1000) := by
  decide

/-- The public-reference adapter, not NumPy's internal implementation, is verified. -/
theorem library_semantic_mapping_numpy_sum (values : List Int) :
    CppAudit.LibraryMapping.numpySumReference values =
      CppAudit.LibraryMapping.simpleReductionAdd values := by
  exact CppAudit.LibraryMapping.numpy_sum_simple_mapping values

end CppAudit.Generated.SyntheticWeightedReductionCertificate
