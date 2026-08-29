namespace CppAudit

def foldLeft (op : α → β → α) (initial : α) : List β → α
  | [] => initial
  | head :: tail => foldLeft op (op initial head) tail

def weightedSum (quantity factor : List Int) : Int :=
  foldLeft (fun acc pair => acc + pair.1 * pair.2) 0 (quantity.zip factor)

theorem weightedSum_nil_left (factor : List Int) :
    weightedSum [] factor = 0 := by rfl

end CppAudit
