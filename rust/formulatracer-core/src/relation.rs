use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RelationKind {
    ExactEquality,
    ExactUnderAssumptions,
    ApproximationOf,
    DiscretizationOf,
    TruncatedTo,
    SampledAs,
    AlgorithmicallyRealizedBy,
}

impl RelationKind {
    pub fn is_exact(self) -> bool {
        matches!(self, Self::ExactEquality | Self::ExactUnderAssumptions)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelationEdge {
    pub source_hash: String,
    pub target_hash: String,
    pub kind: RelationKind,
    #[serde(default)]
    pub assumptions: Vec<String>,
    pub error_evidence: Option<Value>,
    pub source_provenance: Option<Value>,
    pub transformation_provenance: Option<Value>,
}

#[derive(Debug, Default, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelationGraph {
    pub schema_version: String,
    #[serde(default)]
    pub edges: Vec<RelationEdge>,
}

impl RelationGraph {
    pub fn v1() -> Self {
        Self {
            schema_version: "1.0".into(),
            edges: vec![],
        }
    }
    pub fn add(&mut self, edge: RelationEdge) {
        self.edges.push(edge);
    }
}
