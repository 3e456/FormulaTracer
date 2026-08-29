"""Registry of canonical Mathematical IR primitive names and categories."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MathematicalPrimitive:
    name: str
    category: str
    exact_semantic: bool = True
    notes: str = ""


_CATEGORIES = {
    "ALGEBRAIC_STRUCTURES": ("NaturalDomain", "IntegerDomain", "RationalDomain", "RealDomain", "ComplexDomain", "ModularIntegerDomain", "FiniteField", "Semigroup", "Monoid", "Semiring", "CommutativeSemiring", "Group", "CommutativeGroup", "Ring", "CommutativeRing", "IntegralDomain", "Field", "VectorSpace", "MatrixAlgebra", "BooleanAlgebra"),
    "BINDERS": ("ForAll", "Exists", "ExistsUnique", "Lambda", "BoundVariable", "SuchThat", "Given", "SubjectTo"),
    "LOGIC_CONDITIONS": ("Predicate", "Compare", "LogicalAnd", "LogicalOr", "LogicalNot", "LogicalXor", "Implies", "Equivalent", "Select", "Piecewise", "Indicator", "Minimum", "Maximum", "Clamp", "HeavisideStep", "Sign"),
    "SETS_RELATIONS": ("Set", "FiniteSet", "Membership", "SetUnion", "SetIntersection", "SetDifference", "SetComplement", "CartesianProduct", "Relation", "EquivalenceRelation", "Partition", "Image", "Preimage"),
    "MAP_PROPERTIES": ("MapComposition", "MapRestriction", "InverseMap", "LeftInverse", "RightInverse", "Injective", "Surjective", "Bijective", "HasFixedPoint", "Kernel", "ImageSpace"),
    "COMPLEX": ("RealPart", "ImagPart", "Conjugate", "Magnitude", "Argument", "PolarForm", "ComplexExponential", "ComplexBranch"),
    "INTEGER_BITVECTOR": ("Numeral", "Modulo", "Remainder", "Quotient", "DivMod", "BitVector", "EncodeBits", "DecodeBits", "BitAnd", "BitOr", "BitXor", "BitNot", "ShiftLeft", "ShiftRight", "RotateLeft", "RotateRight", "BitFieldExtract", "BitFieldInsert", "PopCount", "LeadingZeros", "TrailingZeros", "BitTest", "Parity", "Divisibility"),
    "LINEAR_ALGEBRA": ("Determinant", "Rank", "NullSpace", "Eigenvalue", "Eigenvector", "SVD", "PseudoInverse", "LinearSolve", "Projection", "Orthogonality", "Basis", "ChangeOfBasis"),
    "VECTOR_CALCULUS": ("Gradient", "Divergence", "Curl", "Jacobian", "Hessian", "DirectionalDerivative"),
    "DIFFERENTIAL_EQUATIONS": ("ODE", "PDE", "InitialCondition", "BoundaryCondition", "DiscretizedOperator", "TimeStepper", "BoundaryScheme"),
    "ASYMPTOTIC": ("BigO", "LittleO", "Theta", "AsymptoticEquivalent", "LeadingTerm"),
    "UNITS_DIMENSIONS": ("PhysicalDimension", "Unit", "UnitConversion", "DimensionConsistency"),
    "UNCERTAINTY": ("ExactValue", "Interval", "MeasurementUncertainty", "SignificantDigits", "Tolerance"),
    "SPECIAL_DISTRIBUTIONS": ("DiracDelta", "KroneckerDelta", "StepFunction", "GeneralizedFunction"),
    "POLYNOMIALS": ("Polynomial", "PolynomialDegree", "Coefficient", "Monomial", "RationalFunction", "Root", "Multiplicity", "PolynomialFactorization", "PolynomialDivision", "RemainderPolynomial", "CharacteristicPolynomial", "MinimalPolynomial"),
    "EQUATIONS_SOLVERS": ("Equation", "Inequality", "Constraint", "Solution", "SolutionSet", "Solve", "RootOf", "ExactSolution", "ApproximateSolution", "RootFindingProblem", "Bisection", "NewtonIteration", "SecantIteration", "FixedPointIteration", "LinearSolver", "OptimizationSolver", "ODESolver"),
    "DYNAMICAL_SYSTEMS": ("Recurrence", "DifferenceEquation", "FixedPoint", "StateTransition", "DiscreteDynamicalSystem", "ContinuousDynamicalSystem"),
    "OPTIMIZATION": ("Minimize", "Maximize", "ArgMin", "ArgMax", "Objective", "FeasibleSet", "LocalOptimum", "GlobalOptimum", "Subgradient", "Lagrangian"),
    "GRAPH_MATHEMATICS": ("Graph", "DirectedGraph", "WeightedGraph", "Vertex", "Edge", "Path", "Walk", "Cycle", "AdjacencyMatrix", "GraphLaplacian", "ShortestPath", "Reachability", "ConnectedComponent", "Flow", "Cut"),
    "GEOMETRY_COORDINATES": ("Point", "Vector", "Line", "Polygon", "Distance", "Angle", "Area", "Volume", "CoordinateSystem", "CoordinateTransform", "EuclideanDistance", "GeodesicDistance"),
    "SPARSE_REPRESENTATION": ("SparseVector", "SparseMatrix", "DenseEquivalent", "SparsityPattern", "CSR", "CSC", "COO"),
    "DISCRETE_TRANSFORMS": ("ZTransform", "InverseZTransform", "DCT", "DST", "WaveletTransform", "HilbertTransform"),
}


def mathematical_primitive_registry() -> tuple[MathematicalPrimitive, ...]:
    return tuple(MathematicalPrimitive(name, category,
        exact_semantic=name not in {"DiscretizedOperator", "TimeStepper", "BoundaryScheme", "BigO", "LittleO", "LeadingTerm"})
        for category, names in _CATEGORIES.items() for name in names)


def primitive_categories() -> dict[str, tuple[str, ...]]:
    return dict(_CATEGORIES)
