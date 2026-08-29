import CppAudit.Core.Effect

namespace CppAudit

inductive ValueKind where
  | input | constant | temporary | output | iterator | range | container
  | callable | coordinate | dimension
  deriving DecidableEq, Repr

inductive OperationKind where
  | add | subtract | multiply | divide | compare | load | store | index
  | map | fold | reduce | transform | transformReduce | innerProduct | scan
  | conditional | call | allocate | throw | io | clockRead | randomRead
  | atomicOperation | synchronization
  deriving DecidableEq, Repr

structure ValueNode where
  id : String
  kind : ValueKind
  deriving Repr

structure OperationNode where
  id : String
  kind : OperationKind
  effect : Effect
  deriving Repr

structure Edge where
  source : String
  target : String
  argumentIndex : Nat
  argumentRole : String
  deriving Repr

structure Graph where
  values : List ValueNode
  operations : List OperationNode
  edges : List Edge
  deriving Repr

def Graph.effectsKnown (graph : Graph) : Prop :=
  ∀ node ∈ graph.operations, node.effect ≠ .unknown

def Graph.wellFormed (graph : Graph) : Prop :=
  graph.values ≠ [] ∧ graph.operations ≠ [] ∧ graph.effectsKnown

end CppAudit
