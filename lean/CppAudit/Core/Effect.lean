namespace CppAudit

inductive Effect where
  | pure | readMemory | writeMemory | allocate | deallocate | throw
  | io | fileSystem | clock | random | thread | atomic | synchronize
  | environment | unknown
  deriving DecidableEq, Repr

def Effect.permittedForScientificAudit : Effect → Bool
  | .pure | .readMemory | .writeMemory => true
  | _ => false

theorem unknown_not_permitted :
    Effect.unknown.permittedForScientificAudit = false := by rfl

end CppAudit
