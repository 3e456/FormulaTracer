namespace CppAudit.Semantics.Transformation

def sumN (n : Nat) (body : Nat → Int) : Int :=
  (List.range n).foldl (fun total index => total + body index) 0

theorem alpha_rename_sound (n : Nat) (body : Nat → Int) :
    sumN n body = sumN n (fun renamedIndex => body renamedIndex) := by
  rfl

theorem finite_sum_normalization_sound (n : Nat) (body : Nat → Int) :
    (List.range n).foldl (fun total index => total + body index) 0 = sumN n body := by
  rfl

theorem add_neutral_sound (value : Int) : value + 0 = value := by
  exact Int.add_zero value

theorem multiply_neutral_sound (value : Int) : value * 1 = value := by
  exact Int.mul_one value

theorem add_commutative_sound (left right : Int) : left + right = right + left := by
  exact Int.add_comm left right

theorem multiply_commutative_sound (left right : Int) : left * right = right * left := by
  exact Int.mul_comm left right

end CppAudit.Semantics.Transformation
