use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum NumericDomain {
    Natural,
    Integer,
    Rational,
    Real,
    Complex,
    ModularInteger,
    FiniteField,
    Boolean,
    #[serde(rename = "BITVECTOR", alias = "BIT_VECTOR")]
    BitVector,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AlgebraicStructure {
    Semigroup,
    Monoid,
    Group,
    CommutativeGroup,
    Semiring,
    CommutativeSemiring,
    Ring,
    CommutativeRing,
    IntegralDomain,
    Field,
    BooleanAlgebra,
    VectorSpace,
    MatrixAlgebra,
    ModularRing,
    FiniteField,
    #[serde(rename = "BITVECTOR_ALGEBRA", alias = "BIT_VECTOR_ALGEBRA")]
    BitVectorAlgebra,
}

impl NumericDomain {
    pub fn supports(self, structure: AlgebraicStructure) -> bool {
        use AlgebraicStructure::*;
        match self {
            Self::Natural => matches!(
                structure,
                Semigroup | Monoid | Semiring | CommutativeSemiring
            ),
            Self::Integer => matches!(
                structure,
                Semigroup
                    | Monoid
                    | Group
                    | CommutativeGroup
                    | Semiring
                    | CommutativeSemiring
                    | Ring
                    | CommutativeRing
            ),
            Self::Rational | Self::Real | Self::Complex => matches!(
                structure,
                Semigroup
                    | Monoid
                    | Group
                    | CommutativeGroup
                    | Semiring
                    | CommutativeSemiring
                    | Ring
                    | CommutativeRing
                    | IntegralDomain
                    | Field
            ),
            Self::ModularInteger => matches!(
                structure,
                Semigroup
                    | Monoid
                    | Group
                    | CommutativeGroup
                    | Semiring
                    | CommutativeSemiring
                    | Ring
                    | CommutativeRing
                    | ModularRing
            ),
            Self::FiniteField => matches!(
                structure,
                Semigroup
                    | Monoid
                    | Group
                    | CommutativeGroup
                    | Semiring
                    | CommutativeSemiring
                    | Ring
                    | CommutativeRing
                    | IntegralDomain
                    | Field
                    | FiniteField
            ),
            Self::Boolean => matches!(structure, BooleanAlgebra),
            Self::BitVector => matches!(structure, BitVectorAlgebra),
            Self::Unknown => false,
        }
    }
}

impl AlgebraicStructure {
    fn parents(self) -> &'static [Self] {
        use AlgebraicStructure::*;
        match self {
            Monoid => &[Semigroup],
            Group => &[Monoid, Semigroup],
            CommutativeGroup => &[Group, Monoid, Semigroup],
            Semiring => &[Monoid, Semigroup],
            CommutativeSemiring => &[Semiring, Monoid, Semigroup],
            Ring => &[Semiring, Group, Monoid, Semigroup],
            CommutativeRing => &[
                Ring,
                CommutativeSemiring,
                CommutativeGroup,
                Group,
                Monoid,
                Semigroup,
            ],
            IntegralDomain => &[
                CommutativeRing,
                Ring,
                CommutativeGroup,
                Group,
                Monoid,
                Semigroup,
            ],
            Field => &[
                IntegralDomain,
                CommutativeRing,
                Ring,
                CommutativeGroup,
                Group,
                Monoid,
                Semigroup,
            ],
            FiniteField => &[Field, IntegralDomain, CommutativeRing, Ring],
            ModularRing => &[CommutativeRing, Ring],
            _ => &[],
        }
    }

    pub fn closure(values: impl IntoIterator<Item = Self>) -> Vec<Self> {
        let mut result: HashSet<Self> = values.into_iter().collect();
        let mut pending = result.iter().copied().collect::<Vec<_>>();
        while let Some(value) = pending.pop() {
            for parent in value.parents() {
                if result.insert(*parent) {
                    pending.push(*parent);
                }
            }
        }
        let mut ordered = result.into_iter().collect::<Vec<_>>();
        ordered.sort_by_key(|value| serde_json::to_string(value).unwrap_or_default());
        ordered
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceSpan {
    pub path: String,
    pub start_line: u32,
    pub start_column: u32,
    pub end_line: Option<u32>,
    pub end_column: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceOrigin {
    pub producer: String,
    pub span: Option<SourceSpan>,
    #[serde(default)]
    pub semantic_path: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticDocument {
    pub schema_version: String,
    pub kind: String,
    pub payload: Value,
    #[serde(default)]
    pub origins: Vec<SourceOrigin>,
}

impl SemanticDocument {
    pub fn from_json(input: &str) -> crate::Result<Self> {
        let value: Value = serde_json::from_str(input)?;
        if let Ok(document) = serde_json::from_value::<Self>(value.clone()) {
            return Ok(document);
        }
        let schema_version = value
            .get("schema_version")
            .and_then(Value::as_str)
            .unwrap_or("unversioned")
            .to_owned();
        Ok(Self {
            schema_version,
            kind: "SCHEMA_DOCUMENT".into(),
            payload: value,
            origins: vec![],
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Shape {
    #[serde(default)]
    pub extents: Vec<Option<u64>>,
    #[serde(default)]
    pub named_dimensions: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FunctionType {
    pub domain: NumericDomain,
    pub codomain: NumericDomain,
    pub input_shape: Option<Shape>,
    pub output_shape: Option<Shape>,
    #[serde(default)]
    pub units: Vec<String>,
}
