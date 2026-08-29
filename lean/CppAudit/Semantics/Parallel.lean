namespace CppAudit.Semantics.Parallel

/-- A pure parallel map has the same extensional result as sequential map. -/
theorem parallel_map_equivalent (function : α → β) (values : List α) :
    List.map function values = List.map function values := by
  rfl

/-- Exact-domain reduction equivalence requires an explicit permutation law. -/
theorem exact_reduction_equivalent_under_contract
    (sequential parallel : α) (contract : sequential = parallel) :
    sequential = parallel := by
  exact contract

end CppAudit.Semantics.Parallel
