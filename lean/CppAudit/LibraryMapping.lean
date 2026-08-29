namespace CppAudit.LibraryMapping

/-- The mathematical object selected by the public-reference `sum` contracts. -/
def finiteSum (values : List Int) : Int := values.foldl (· + ·) 0

/-- Reference semantics adapters intentionally hide library implementation details. -/
def numpySumReference (values : List Int) : Int := finiteSum values
def xarraySumReference (values : List Int) : Int := finiteSum values
def daskSumReference (values : List Int) : Int := finiteSum values
def simpleReductionAdd (values : List Int) : Int := finiteSum values

theorem numpy_sum_simple_mapping (values : List Int) :
    numpySumReference values = simpleReductionAdd values := by rfl

theorem xarray_sum_simple_mapping (values : List Int) :
    xarraySumReference values = simpleReductionAdd values := by rfl

theorem dask_sum_simple_mapping (values : List Int) :
    daskSumReference values = simpleReductionAdd values := by rfl

theorem cross_library_sum_mapping (values : List Int) :
    numpySumReference values = xarraySumReference values ∧
    xarraySumReference values = daskSumReference values := by
  constructor <;> rfl

/-- Execution metadata is deliberately separate from mathematical meaning. -/
inductive ExecutionSemantics where
  | eager
  | lazyChunked
  | ioBoundary
  | unspecified
  deriving DecidableEq, Repr

structure ReferenceOperation where
  mathematics : List Int → Int
  execution : ExecutionSemantics

def numpySumOperation : ReferenceOperation :=
  { mathematics := numpySumReference, execution := .eager }

def xarraySumOperation : ReferenceOperation :=
  { mathematics := xarraySumReference, execution := .eager }

def daskSumOperation : ReferenceOperation :=
  { mathematics := daskSumReference, execution := .lazyChunked }

theorem cross_library_sum_mathematics_normalizes (values : List Int) :
    numpySumOperation.mathematics values = xarraySumOperation.mathematics values ∧
    xarraySumOperation.mathematics values = daskSumOperation.mathematics values := by
  constructor <;> rfl

theorem dask_execution_overlay_is_not_erased :
    daskSumOperation.execution = .lazyChunked ∧
    numpySumOperation.execution = .eager := by
  exact ⟨rfl, rfl⟩

def pandasSumReference (values : List Int) : Int := finiteSum values
def simpleTableAggregation (values : List Int) : Int := finiteSum values

theorem pandas_sum_aggregation_mapping (values : List Int) :
    pandasSumReference values = simpleTableAggregation values := by rfl

def shapelyContainsReference {α : Type} (contains : α → α → Prop) (left right : α) : Prop := contains left right
def geopandasContainsReference {α : Type} (contains : α → α → Prop) (left right : α) : Prop := contains left right
def simpleSpatialPredicate {α : Type} (contains : α → α → Prop) (left right : α) : Prop := contains left right

theorem cross_library_spatial_predicate_mapping {α : Type} (contains : α → α → Prop) (left right : α) :
    shapelyContainsReference contains left right = simpleSpatialPredicate contains left right ∧
    geopandasContainsReference contains left right = simpleSpatialPredicate contains left right := by
  constructor <;> rfl

def scipyShortestPathReference {Vertex Distance : Type} (relation : Vertex → Vertex → Distance → Prop) := relation
def simpleShortestPathRelation {Vertex Distance : Type} (relation : Vertex → Vertex → Distance → Prop) := relation

theorem scipy_shortest_path_mapping {Vertex Distance : Type} (relation : Vertex → Vertex → Distance → Prop) :
    scipyShortestPathReference relation = simpleShortestPathRelation relation := by rfl

end CppAudit.LibraryMapping
