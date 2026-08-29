import CppAudit.Semantics.Fold

namespace CppAudit.Generated.PythonAudit

/-- SHA-256 of the Python source whose AST produced the implementation IR. -/
def implementationSourceHash : String := "8261f068b6887c456619881bb1eacbf55430116e12270985235e9610f8944933"

/-- Auditable symbol correspondence found by graph isomorphism. -/
def symbolMapping : String := "{\"bound_indices\": {\"i\": \"i\", \"r\": \"r\"}, \"symbols\": {\"dim(samples,1)\": \"I\", \"samples\": \"samples\", \"weighted_score\": \"weighted_score\", \"weights\": \"weights\"}}"

def sumN (n : Nat) (f : Nat → Int) : Int :=
  (List.range n).foldl (fun acc i => acc + f i) 0

def productN (n : Nat) (f : Nat → Int) : Int :=
  (List.range n).foldl (fun acc i => acc * f i) 1

def implementationExpression (I : Nat) (r : Nat) (weights : Nat → Int) (samples : Nat → Nat → Int) : Int :=
  sumN (I) (fun i => (samples (r) (i) * weights (i)))

def theoryExpression (I : Nat) (r : Nat) (weights : Nat → Int) (samples : Nat → Nat → Int) : Int :=
  sumN (I) (fun i => (samples (r) (i) * weights (i)))

/-- The kernel checks the two separately translated expression graphs. -/
theorem extracted_expression_matches_theory (I : Nat) (r : Nat) (weights : Nat → Int) (samples : Nat → Nat → Int) :
    implementationExpression I r weights samples = theoryExpression I r weights samples := by
  simp [implementationExpression, theoryExpression, Int.add_comm, Int.mul_comm]

end CppAudit.Generated.PythonAudit
