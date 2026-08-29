namespace CppAudit.SemanticRegistry

/-- Closed family tags used by reviewed reference-contract classes. -/
inductive SemanticFamily where
  | reduction | aggregation | alignment | distribution | optimization
  | interpolation | graph | spatial | parallel | elementwise | selection
  | ordering | shapeTransform | linearAlgebra | statisticalInference | signalTransform
  deriving DecidableEq, Repr

/-- A registry class points to one family and a mathematical projection.
    Library execution and representation details live outside this object. -/
structure SemanticEquivalenceClass (Input Output : Type) where
  family : SemanticFamily
  mathematicalProjection : Input → Output

def normalize (semanticClass : SemanticEquivalenceClass α β) (input : α) : β :=
  semanticClass.mathematicalProjection input

theorem class_normalization_is_projection
    (semanticClass : SemanticEquivalenceClass α β) (input : α) :
    normalize semanticClass input = semanticClass.mathematicalProjection input := by
  rfl

def reductionAdd : SemanticEquivalenceClass (List Int) Int :=
  { family := .reduction, mathematicalProjection := fun xs => xs.foldl (· + ·) 0 }

def aggregationAdd : SemanticEquivalenceClass (List Int) Int :=
  { family := .aggregation, mathematicalProjection := reductionAdd.mathematicalProjection }

theorem reduction_and_aggregation_add_normalize (xs : List Int) :
    normalize reductionAdd xs = normalize aggregationAdd xs := by
  rfl

def relationClass (family : SemanticFamily) (relation : α → β → Prop) :
    SemanticEquivalenceClass (α × β) Prop :=
  { family := family, mathematicalProjection := fun pair => relation pair.1 pair.2 }

theorem alignment_relation_normalizes (relation : α → β → Prop) (left : α) (right : β) :
    normalize (relationClass .alignment relation) (left, right) = relation left right := by
  rfl

theorem optimization_relation_normalizes (relation : α → β → Prop) (left : α) (right : β) :
    normalize (relationClass .optimization relation) (left, right) = relation left right := by
  rfl

theorem graph_relation_normalizes (relation : α → β → Prop) (left : α) (right : β) :
    normalize (relationClass .graph relation) (left, right) = relation left right := by
  rfl

theorem spatial_relation_normalizes (relation : α → β → Prop) (left : α) (right : β) :
    normalize (relationClass .spatial relation) (left, right) = relation left right := by
  rfl

def distributionClass (sampleRelation : Params → Sample → Prop) :
    SemanticEquivalenceClass (Params × Sample) Prop :=
  relationClass .distribution sampleRelation

theorem distribution_relation_preserves_parameters
    (sampleRelation : Params → Sample → Prop) (params : Params) (sample : Sample) :
    normalize (distributionClass sampleRelation) (params, sample) = sampleRelation params sample := by
  rfl

def transformClass (family : SemanticFamily) (transform : α → β) :
    SemanticEquivalenceClass α β :=
  { family := family, mathematicalProjection := transform }

theorem elementwise_transform_normalizes (transform : α → β) (input : α) :
    normalize (transformClass .elementwise transform) input = transform input := by
  rfl

theorem selection_normalizes (select : α → β) (input : α) :
    normalize (transformClass .selection select) input = select input := by
  rfl

theorem ordering_normalizes (order : α → β) (input : α) :
    normalize (transformClass .ordering order) input = order input := by
  rfl

theorem shape_transform_normalizes (reshape : α → β) (input : α) :
    normalize (transformClass .shapeTransform reshape) input = reshape input := by
  rfl

theorem linear_algebra_relation_normalizes
    (relation : α → β → Prop) (left : α) (right : β) :
    normalize (relationClass .linearAlgebra relation) (left, right) = relation left right := by
  rfl

theorem interpolation_relation_normalizes
    (relation : α → β → Prop) (samples : α) (result : β) :
    normalize (relationClass .interpolation relation) (samples, result) = relation samples result := by
  rfl

theorem statistical_inference_relation_normalizes
    (relation : α → β → Prop) (sample : α) (result : β) :
    normalize (relationClass .statisticalInference relation) (sample, result) = relation sample result := by
  rfl

theorem signal_transform_normalizes (transform : α → β) (signal : α) :
    normalize (transformClass .signalTransform transform) signal = transform signal := by
  rfl

inductive ExecutionOverlay where
  | eager | lazyChunked | schedulerDependent
  deriving DecidableEq, Repr

structure ExecutableClass (Input Output : Type) extends SemanticEquivalenceClass Input Output where
  execution : ExecutionOverlay

def parallelize (semanticClass : SemanticEquivalenceClass α β) : ExecutableClass α β :=
  { semanticClass with execution := .lazyChunked }

theorem parallel_mathematical_projection_is_preserved
    (semanticClass : SemanticEquivalenceClass α β) (input : α) :
    normalize (parallelize semanticClass).toSemanticEquivalenceClass input = normalize semanticClass input := by
  rfl

theorem parallel_execution_overlay_is_explicit (semanticClass : SemanticEquivalenceClass α β) :
    (parallelize semanticClass).execution = .lazyChunked := by
  rfl

end CppAudit.SemanticRegistry
