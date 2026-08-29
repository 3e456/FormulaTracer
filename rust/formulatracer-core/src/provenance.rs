use crate::{canonical_json, CanonicalPolicy, Result, SourceSpan};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProvenanceNode {
    pub node_id: String,
    pub kind: String,
    pub digest: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProvenanceEdge {
    pub source: String,
    pub target: String,
    pub kind: String,
}

#[derive(Debug, Default, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProvenanceGraph {
    pub schema_version: String,
    pub nodes: Vec<ProvenanceNode>,
    pub edges: Vec<ProvenanceEdge>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CacheKey {
    pub source_hash: String,
    pub formulatracer_version: String,
    pub ir_version: String,
    pub contract_version: String,
    pub knowledge_version: String,
    pub provider_version: String,
    pub schema_version: String,
}

impl CacheKey {
    pub fn digest(&self) -> Result<String> {
        let bytes = serde_json::to_vec(self)?;
        Ok(format!("{:x}", Sha256::digest(bytes)))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IntegrityEnvelope {
    pub key_digest: String,
    pub payload_digest: String,
    pub payload: Value,
}

impl IntegrityEnvelope {
    pub fn create(key: &CacheKey, payload: Value) -> Result<Self> {
        Ok(Self {
            key_digest: key.digest()?,
            payload_digest: semantic_payload_digest(&payload)?,
            payload,
        })
    }
    pub fn verify(&self, key: &CacheKey) -> Result<bool> {
        Ok(self.key_digest == key.digest()?
            && self.payload_digest == semantic_payload_digest(&self.payload)?)
    }
}

fn semantic_payload_digest(value: &Value) -> Result<String> {
    let bytes = canonical_json(
        value,
        CanonicalPolicy {
            ignore_source_provenance: false,
            ..Default::default()
        },
    )?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LocalizationLevel {
    ExactSourceSpan,
    SourceSpanSet,
    CorrectSemanticNode,
    SourceBasicBlock,
    SourceFunction,
    SourceModule,
    Unresolved,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DebugLocalization {
    pub level: LocalizationLevel,
    pub spans: Vec<SourceSpan>,
    pub semantic_path: Vec<String>,
    pub evidence: Vec<String>,
}

pub fn localize(origins: &[crate::SourceOrigin], semantic_path: Vec<String>) -> DebugLocalization {
    let spans: Vec<_> = origins
        .iter()
        .filter_map(|origin| origin.span.clone())
        .collect();
    let level = match spans.len() {
        1 => LocalizationLevel::ExactSourceSpan,
        n if n > 1 => LocalizationLevel::SourceSpanSet,
        _ if !semantic_path.is_empty() => LocalizationLevel::CorrectSemanticNode,
        _ => LocalizationLevel::Unresolved,
    };
    DebugLocalization {
        level,
        spans,
        semantic_path,
        evidence: origins
            .iter()
            .map(|origin| origin.producer.clone())
            .collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn tampered_cache_payload_is_rejected() {
        let key = CacheKey {
            source_hash: "a".into(),
            formulatracer_version: "1".into(),
            ir_version: "1".into(),
            contract_version: "1".into(),
            knowledge_version: "1".into(),
            provider_version: "1".into(),
            schema_version: "1".into(),
        };
        let mut envelope = IntegrityEnvelope::create(&key, json!({"status":"VERIFIED"})).unwrap();
        envelope.payload = json!({"status":"DIVERGED"});
        assert!(!envelope.verify(&key).unwrap());
    }
}
