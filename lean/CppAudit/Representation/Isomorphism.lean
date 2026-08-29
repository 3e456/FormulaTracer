namespace CppAudit

structure HumanInput where
  quantity : List (List Int)
  factor : List Int

structure CppInputRepresentation where
  quantityRowMajor : List Int
  factor : List Int
  regions : Nat
  inputs : Nat

def encodeInput (input : HumanInput) : CppInputRepresentation :=
  { quantityRowMajor := input.quantity.flatten
    factor := input.factor
    regions := input.quantity.length
    inputs := input.factor.length }

def decodeInput (shape : List Nat) (cpp : CppInputRepresentation) : HumanInput :=
  { quantity := shape.map (fun offset => (cpp.quantityRowMajor.drop offset).take cpp.inputs)
    factor := cpp.factor }

theorem encode_preserves_factor (input : HumanInput) :
    (encodeInput input).factor = input.factor := by rfl

end CppAudit
