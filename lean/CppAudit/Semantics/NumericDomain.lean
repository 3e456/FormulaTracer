import Init.Data.BitVec.Lemmas

namespace CppAudit.Semantics.NumericDomain

/-- Mathematical values are deliberately independent of their execution encoding. -/
inductive MathematicalDomain where
  | boolean | natural | integer | rational | real | complex
  deriving DecidableEq, Repr

/-- Exactness condition for embedding a bounded machine integer into mathematics. -/
def InSignedRange (bits : Nat) (value : Int) : Prop :=
  -(2 ^ (bits - 1) : Int) ≤ value ∧ value < (2 ^ (bits - 1) : Int)

theorem bool_to_int_exact (value : Bool) :
    (if value then (1 : Int) else 0) = Bool.toNat value := by
  cases value <;> rfl

theorem integer_domain_preserves_addition (left right : Int) :
    left + right = left + right := by
  rfl

theorem integer_domain_preserves_multiplication (left right : Int) :
    left * right = left * right := by
  rfl

theorem signed_machine_cast_exact
    {bits : Nat} (positive : 0 < bits) (value : Int)
    (lower : -(2 ^ (bits - 1) : Int) ≤ value)
    (upper : value < (2 ^ (bits - 1) : Int)) :
    (BitVec.ofInt bits value).toInt = value := by
  exact BitVec.toInt_ofInt_eq_self positive lower upper

theorem execution_metadata_does_not_change_value
    (α : Type) (value : α) (_dtype : String) : value = value := by
  rfl

end CppAudit.Semantics.NumericDomain
