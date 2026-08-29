namespace CppAudit.Semantics.NumericalApproximation

/- Phase 6 checks the discrete expression graph itself.  This syntax has no
   Python dtype or integer/real division semantics, and no definition below
   claims convergence or an approximation error bound. -/

inductive DiscreteExpr where
  | atom : String → DiscreteExpr
  | lit : Int → DiscreteExpr
  | add : DiscreteExpr → DiscreteExpr → DiscreteExpr
  | sub : DiscreteExpr → DiscreteExpr → DiscreteExpr
  | mul : DiscreteExpr → DiscreteExpr → DiscreteExpr
  | div : DiscreteExpr → DiscreteExpr → DiscreteExpr
  deriving Repr, DecidableEq

open DiscreteExpr

def forwardDifference (fx fxh h : DiscreteExpr) : DiscreteExpr := div (sub fxh fx) h
def backwardDifference (fxmh fx h : DiscreteExpr) : DiscreteExpr := div (sub fx fxmh) h
def centralDifference (fxmh fxh h : DiscreteExpr) : DiscreteExpr :=
  div (sub fxh fxmh) (mul (lit 2) h)
def secondCentralDifference (fxmh fx fxh h : DiscreteExpr) : DiscreteExpr :=
  div (add (add fxh (mul (lit (-2)) fx)) fxmh) (mul h h)

def leftRectangleSum (left h : DiscreteExpr) : DiscreteExpr := mul h left
def rightRectangleSum (right h : DiscreteExpr) : DiscreteExpr := mul h right
def midpointSum (midpoint h : DiscreteExpr) : DiscreteExpr := mul h midpoint
def trapezoidalSum (left right h : DiscreteExpr) : DiscreteExpr :=
  div (mul h (add left right)) (lit 2)
def simpsonSum (left midpoint right h : DiscreteExpr) : DiscreteExpr :=
  div (mul h (add (add left (mul (lit 4) midpoint)) right)) (lit 6)

def nearestInterpolation (nearest : DiscreteExpr) : DiscreteExpr := nearest
def linearInterpolation (left right t : DiscreteExpr) : DiscreteExpr :=
  add (mul (sub (lit 1) t) left) (mul t right)
def multilinearInterpolation2D (v00 v10 v01 v11 tx ty : DiscreteExpr) : DiscreteExpr :=
  add (add (mul (mul (sub (lit 1) tx) (sub (lit 1) ty)) v00)
           (mul (mul tx (sub (lit 1) ty)) v10))
      (add (mul (mul (sub (lit 1) tx) ty) v01) (mul (mul tx ty) v11))

theorem generated_forward_is_registered (fx fxh h : DiscreteExpr) :
    div (sub fxh fx) h = forwardDifference fx fxh h := by rfl
theorem generated_backward_is_registered (fxmh fx h : DiscreteExpr) :
    div (sub fx fxmh) h = backwardDifference fxmh fx h := by rfl
theorem generated_central_is_registered (fxmh fxh h : DiscreteExpr) :
    div (sub fxh fxmh) (mul (lit 2) h) = centralDifference fxmh fxh h := by rfl
theorem generated_second_central_is_registered (fxmh fx fxh h : DiscreteExpr) :
    div (add (add fxh (mul (lit (-2)) fx)) fxmh) (mul h h) =
      secondCentralDifference fxmh fx fxh h := by rfl

theorem generated_left_rectangle_is_registered (left h : DiscreteExpr) :
    mul h left = leftRectangleSum left h := by rfl
theorem generated_right_rectangle_is_registered (right h : DiscreteExpr) :
    mul h right = rightRectangleSum right h := by rfl
theorem generated_midpoint_is_registered (midpoint h : DiscreteExpr) :
    mul h midpoint = midpointSum midpoint h := by rfl
theorem generated_trapezoidal_is_registered (left right h : DiscreteExpr) :
    div (mul h (add left right)) (lit 2) = trapezoidalSum left right h := by rfl
theorem generated_simpson_is_registered (left midpoint right h : DiscreteExpr) :
    div (mul h (add (add left (mul (lit 4) midpoint)) right)) (lit 6) =
      simpsonSum left midpoint right h := by rfl

theorem generated_nearest_is_registered (nearest : DiscreteExpr) :
    nearest = nearestInterpolation nearest := by rfl
theorem generated_linear_interpolation_is_registered (left right t : DiscreteExpr) :
    add (mul (sub (lit 1) t) left) (mul t right) = linearInterpolation left right t := by rfl
theorem generated_multilinear2D_is_registered (v00 v10 v01 v11 tx ty : DiscreteExpr) :
    add (add (mul (mul (sub (lit 1) tx) (sub (lit 1) ty)) v00)
             (mul (mul tx (sub (lit 1) ty)) v10))
        (add (mul (mul (sub (lit 1) tx) ty) v01) (mul (mul tx ty) v11)) =
      multilinearInterpolation2D v00 v10 v01 v11 tx ty := by rfl

end CppAudit.Semantics.NumericalApproximation
