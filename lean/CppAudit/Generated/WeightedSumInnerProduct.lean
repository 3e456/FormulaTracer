import CppAudit.Graph.Graph
import CppAudit.Representation.Isomorphism
import CppAudit.Refinement.WeightedSum

namespace CppAudit.Generated.WeightedSumInnerProduct

/-- Generated from Clang Implementation IR for `weighted_sum_inner_product`. -/
def implementationSourceHash : String := "b0190a003827ab245b9cf6ec852d77c51e1bbf3adfa424d5c753de2318e8a05d"

def generatedImplementation := cppInnerProductWeightedSum

def generatedGraph : Graph :=
  { values := [{ id := "quantity", kind := .input },
                { id := "factor", kind := .input },
                { id := "result", kind := .output }]
    operations := [{ id := "multiply", kind := .multiply, effect := .pure },
                   { id := "fold-input", kind := .transformReduce, effect := .pure }]
    edges := [{ source := "quantity", target := "multiply", argumentIndex := 0, argumentRole := "lhs" },
              { source := "factor", target := "multiply", argumentIndex := 1, argumentRole := "rhs" },
              { source := "multiply", target := "fold-input", argumentIndex := 0, argumentRole := "input" }] }

theorem generated_graph_well_formed : generatedGraph.wellFormed := by
  simp [Graph.wellFormed, Graph.effectsKnown, generatedGraph]

theorem generated_representation_valid (input : HumanInput) :
    (encodeInput input).factor = input.factor := by rfl

theorem generated_implementation_refines (quantity factor : List Int) :
    generatedImplementation quantity factor = humanWeightedSum quantity factor := by rfl

end CppAudit.Generated.WeightedSumInnerProduct
