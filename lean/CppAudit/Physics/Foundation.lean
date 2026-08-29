import Mathlib.Data.Real.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring

namespace CppAudit.Physics

/- These lemmas certify algebraic obligations used after FormulaTracer has
   separately established differentiability and representation assumptions. -/

theorem curlGradientZero (dxy dyx : ℝ) (mixedPartial : dxy = dyx) :
    dxy - dyx = 0 := by
  linarith

theorem divergenceCurlZero
    (dxy dyx dxz dzx dyz dzy : ℝ)
    (hxy : dxy = dyx) (hxz : dxz = dzx) (hyz : dyz = dzy) :
    (dxy - dyx) + (dxz - dzx) + (dyz - dzy) = 0 := by
  linarith

@[ext] structure ComplexPair where
  re : ℝ
  im : ℝ

@[ext] structure Quaternion where
  re : ℝ
  i : ℝ
  j : ℝ
  k : ℝ

def ComplexPair.mul (z w : ComplexPair) : ComplexPair :=
  ⟨z.re * w.re - z.im * w.im, z.re * w.im + z.im * w.re⟩

def Quaternion.mul (q r : Quaternion) : Quaternion :=
  ⟨q.re * r.re - q.i * r.i - q.j * r.j - q.k * r.k,
   q.re * r.i + q.i * r.re + q.j * r.k - q.k * r.j,
   q.re * r.j - q.i * r.k + q.j * r.re + q.k * r.i,
   q.re * r.k + q.i * r.j - q.j * r.i + q.k * r.re⟩

def embedComplex (z : ComplexPair) : Quaternion := ⟨z.re, z.im, 0, 0⟩

theorem complexQuaternionEmbeddingMul (z w : ComplexPair) :
    embedComplex (ComplexPair.mul z w) =
      Quaternion.mul (embedComplex z) (embedComplex w) := by
  ext <;> simp [embedComplex, ComplexPair.mul, Quaternion.mul]

theorem antipodalUnitQuaternionSameQuadraticAction
    (q0 q1 q2 q3 x : ℝ) :
    ((-q0) * (-q0) + (-q1) * (-q1) + (-q2) * (-q2) + (-q3) * (-q3)) * x =
      (q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3) * x := by
  ring

end CppAudit.Physics
