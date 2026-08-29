import CppAudit.Semantics.Fold

namespace CppAudit.Semantics.ControlFlow

/-- A branch is interpreted pointwise; this theorem makes the normalization explicit. -/
theorem branch_normalization {α : Type} (condition : Bool) (yes no : α) :
    (if condition then yes else no) = match condition with | true => yes | false => no := by
  cases condition <;> rfl

/-- Functional meaning of an indexed Python state update. -/
def indexedStateUpdate (state : Nat → α) (index : Nat) (value : α) : Nat → α :=
  fun query => if query = index then value else state query

theorem indexed_state_update_at (state : Nat → α) (index : Nat) (value : α) :
    indexedStateUpdate state index value index = value := by
  simp [indexedStateUpdate]

theorem indexed_state_update_other (state : Nat → α) (index query : Nat) (value : α)
    (different : query ≠ index) :
    indexedStateUpdate state index value query = state query := by
  simp [indexedStateUpdate, different]

/-- One semantics-preserving step of a finite left fold. -/
theorem finite_fold_step (initial head : Int) (tail : List Int) :
    CppAudit.foldLeft (fun acc value => acc + value) initial (head :: tail) =
      CppAudit.foldLeft (fun acc value => acc + value) (initial + head) tail := by
  rfl

end CppAudit.Semantics.ControlFlow
