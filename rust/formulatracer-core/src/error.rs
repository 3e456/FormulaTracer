use thiserror::Error;

#[derive(Debug, Error)]
pub enum FormulaTracerError {
    #[error("invalid JSON: {0}")]
    InvalidJson(#[from] serde_json::Error),
    #[error("unsupported native component: {0}")]
    NativeComponentIncomplete(&'static str),
    #[error("invalid semantic document: {0}")]
    InvalidSemanticDocument(String),
    #[error("constraint unresolved: {0}")]
    ConstraintUnresolved(String),
    #[error("non-exact relation cannot merge an exact e-class: {0}")]
    NonExactMergeForbidden(String),
    #[error("invalid bit-vector operation: {0}")]
    InvalidBitVector(String),
    #[error("invalid pack: {0}")]
    InvalidPack(String),
}

pub type Result<T> = std::result::Result<T, FormulaTracerError>;
