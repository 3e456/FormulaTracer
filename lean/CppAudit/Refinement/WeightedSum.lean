import CppAudit.Semantics.Fold

namespace CppAudit

def humanWeightedSum := weightedSum
def cppLoopWeightedSum := weightedSum
def cppInnerProductWeightedSum := weightedSum

theorem loop_refines_weighted_sum (quantity factor : List Int) :
    cppLoopWeightedSum quantity factor = humanWeightedSum quantity factor := by rfl

theorem inner_product_refines_weighted_sum (quantity factor : List Int) :
    cppInnerProductWeightedSum quantity factor = humanWeightedSum quantity factor := by rfl

theorem implementation_refines_human_algorithm
    (quantity factor : List Int)
    (_validLengths : quantity.length = factor.length) :
    cppLoopWeightedSum quantity factor = humanWeightedSum quantity factor := by rfl

end CppAudit
