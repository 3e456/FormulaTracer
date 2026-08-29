//! Versioned, integrity-protected native audit bundle.
//!
//! The bundle is a serialization boundary.  It never upgrades evidence or
//! verification status; all claims are copied from the canonical result object.

use crate::{FormulaTracerError, Result, VerificationResult};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

/// Canonical multi-output project bundle assembled from the native project
/// VerificationResult. Bindings may serialize it but cannot alter its claims.
pub fn project_audit_bundle(request: &Value) -> Result<Value> {
    let project = request
        .get("project")
        .ok_or_else(|| FormulaTracerError::InvalidSemanticDocument("project required".into()))?;
    let outputs = project
        .get("outputs")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let payload = json!({
        "schema_version":"1.0", "status":project.get("end_to_end_status"),
        "claims":project.get("end_to_end_claims"),
        "theory":outputs.iter().map(|o|o.get("theory").cloned().unwrap_or(Value::Null)).collect::<Vec<_>>(),
        "implementation":outputs.iter().map(|o|o.get("implementation").cloned().unwrap_or(Value::Null)).collect::<Vec<_>>(),
        "mathematical_ir":outputs.iter().map(|o|o.get("formula").cloned().unwrap_or(Value::Null)).collect::<Vec<_>>(),
        "relation":outputs.iter().map(|o|o.pointer("/end_to_end_claim/verification_matrix").cloned().unwrap_or_else(||json!([]))).collect::<Vec<_>>(),
        "assumptions":outputs.iter().map(|o|o.pointer("/end_to_end_claim/assumptions").cloned().unwrap_or_else(||json!([]))).collect::<Vec<_>>(),
        "error":outputs.iter().map(|o|o.get("total_error_bound").cloned().unwrap_or(Value::Null)).collect::<Vec<_>>(),
        "range":outputs.iter().map(|o|o.get("true_value_enclosure").cloned().unwrap_or(Value::Null)).collect::<Vec<_>>(),
        "proof_obligations":outputs.iter().map(|o|o.get("remaining_obligations").cloned().unwrap_or_else(||json!([]))).collect::<Vec<_>>(),
        "evidence":project.get("proofs"), "provenance":project.get("provenance"),
        "debugger":request.get("debugger"), "root_cause":request.pointer("/debugger/root_causes"),
        "lineage":project.pointer("/provenance/data_lineage"), "schema":project.pointer("/provenance/output_schemas"),
        "provider":project.pointer("/provenance/selected_providers"), "generation_decision":request.get("generation_decisions"),
        "structural_normalization":request.get("structural_normalization"), "structural_witness":request.get("structural_isomorphism"),
        "reconstruction":request.get("reconstruction"),
        "input_provenance":project.pointer("/provenance/input_artifacts"),
        "configuration_provenance":project.pointer("/provenance/configuration_resolution"),
        "environment_provenance":project.pointer("/provenance/environment"),
        "dependency_provenance":project.get("dependencies"), "artifact_fingerprints":project.get("artifacts")
    });
    let payload_hash = format!("{:x}", Sha256::digest(serde_json::to_vec(&payload)?));
    Ok(
        json!({"payload":payload,"payload_hash":payload_hash,"integrity_status":"AUDIT_BUNDLE_INTEGRITY_VERIFIED"}),
    )
}

#[cfg(test)]
mod project_tests {
    use super::*;

    #[test]
    fn project_bundle_preserves_semantic_fields_and_is_deterministic() {
        let request = json!({
            "project": {
                "end_to_end_status": "VERIFIED",
                "end_to_end_claims": [{"claim_id": "claim-1"}],
                "outputs": [{
                    "theory": {"op": "FreeVariable", "name": "t"},
                    "implementation": {"kind": "implementation_ir"},
                    "formula": {"op": "FreeVariable", "name": "x"},
                    "end_to_end_claim": {
                        "verification_matrix": [{"layer": "THEORY", "status": "VERIFIED"}],
                        "assumptions": ["x is real"]
                    },
                    "total_error_bound": {"status": "CERTIFIED_WITHIN_ERROR_BOUND"},
                    "true_value_enclosure": {"status": "ENCLOSED"},
                    "remaining_obligations": []
                }],
                "proofs": [{"status": "KERNEL_VERIFIED"}],
                "provenance": {"data_lineage": {"nodes": []}},
                "dependencies": [],
                "artifacts": []
            },
            "debugger": {"status": "NO_DIVERGENCE"},
            "generation_decisions": [{"provider": "numpy.sum"}],
            "structural_normalization": {"status": "NORMALIZED"},
            "structural_isomorphism": {"status": "ISOMORPHIC"}
        });
        let first = project_audit_bundle(&request).unwrap();
        let second = project_audit_bundle(&request).unwrap();
        assert_eq!(first, second);
        assert_eq!(first["payload"]["status"], "VERIFIED");
        assert_eq!(first["payload"]["theory"][0]["name"], "t");
        assert_eq!(
            first["payload"]["implementation"][0]["kind"],
            "implementation_ir"
        );
        assert_eq!(first["payload"]["mathematical_ir"][0]["name"], "x");
        assert_eq!(
            first["payload"]["generation_decision"][0]["provider"],
            "numpy.sum"
        );
        assert_eq!(first["payload_hash"].as_str().unwrap().len(), 64);
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AuditBundle {
    pub schema_version: String,
    pub result: VerificationResult,
    #[serde(default)]
    pub source_context: Value,
    #[serde(default)]
    pub environment: Value,
    #[serde(default)]
    pub artifact_lineage: Value,
    #[serde(default)]
    pub data_schema: Value,
    #[serde(default)]
    pub provider_decisions: Value,
    #[serde(default)]
    pub generation_decisions: Value,
    #[serde(default)]
    pub structural_normalization: Value,
    #[serde(default)]
    pub structural_isomorphism: Value,
    #[serde(default)]
    pub ignored_representation_differences: Value,
    #[serde(default)]
    pub reconstruction: Value,
    pub payload_hash: String,
}

impl AuditBundle {
    pub fn new(
        result: VerificationResult,
        source_context: Value,
        environment: Value,
        artifact_lineage: Value,
    ) -> Result<Self> {
        Self::new_complete(
            result,
            source_context,
            environment,
            artifact_lineage,
            json!({}),
            json!([]),
            json!([]),
        )
    }

    pub fn new_complete(
        result: VerificationResult,
        source_context: Value,
        environment: Value,
        artifact_lineage: Value,
        data_schema: Value,
        provider_decisions: Value,
        generation_decisions: Value,
    ) -> Result<Self> {
        Self::new_with_structural(
            result,
            source_context,
            environment,
            artifact_lineage,
            data_schema,
            provider_decisions,
            generation_decisions,
            json!({}),
            json!({}),
            json!([]),
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn new_with_structural(
        result: VerificationResult,
        source_context: Value,
        environment: Value,
        artifact_lineage: Value,
        data_schema: Value,
        provider_decisions: Value,
        generation_decisions: Value,
        structural_normalization: Value,
        structural_isomorphism: Value,
        ignored_representation_differences: Value,
    ) -> Result<Self> {
        let mut bundle = Self {
            schema_version: "1.0".into(),
            result,
            source_context,
            environment,
            artifact_lineage,
            data_schema,
            provider_decisions,
            generation_decisions,
            structural_normalization,
            structural_isomorphism,
            ignored_representation_differences,
            reconstruction: json!(null),
            payload_hash: String::new(),
        };
        bundle.payload_hash = bundle.compute_hash()?;
        Ok(bundle)
    }

    fn hash_payload(&self) -> Value {
        json!({
            "schema_version": self.schema_version,
            "result": self.result,
            "source_context": self.source_context,
            "environment": self.environment,
            "artifact_lineage": self.artifact_lineage,
            "data_schema": self.data_schema,
            "provider_decisions": self.provider_decisions,
            "generation_decisions": self.generation_decisions,
            "structural_normalization": self.structural_normalization,
            "structural_isomorphism": self.structural_isomorphism,
            "ignored_representation_differences": self.ignored_representation_differences,
            "reconstruction": self.reconstruction,
        })
    }

    pub fn compute_hash(&self) -> Result<String> {
        let bytes = serde_json::to_vec(&self.hash_payload())?;
        Ok(format!("{:x}", Sha256::digest(bytes)))
    }

    pub fn verify_integrity(&self) -> Result<()> {
        if self.payload_hash != self.compute_hash()? {
            return Err(FormulaTracerError::InvalidSemanticDocument(
                "AUDIT_BUNDLE_HASH_MISMATCH".into(),
            ));
        }
        Ok(())
    }

    pub fn to_json(&self) -> Result<String> {
        self.verify_integrity()?;
        Ok(serde_json::to_string(self)?)
    }

    pub fn from_json(source: &str) -> Result<Self> {
        let bundle: Self = serde_json::from_str(source)?;
        bundle.verify_integrity()?;
        Ok(bundle)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Formula;

    #[test]
    fn audit_bundle_is_native_deterministic_and_tamper_evident() {
        let formula = Formula::from_json(r#"{"op":"FreeVariable","name":"x"}"#).unwrap();
        let result = formula.verify_against(&formula);
        let bundle = AuditBundle::new(
            result,
            json!({"source_hash":"abc"}),
            json!({"core_version":"0.1.0"}),
            json!({"artifact":"report.tex"}),
        )
        .unwrap();
        let encoded = bundle.to_json().unwrap();
        assert_eq!(AuditBundle::from_json(&encoded).unwrap(), bundle);

        let mut tampered: Value = serde_json::from_str(&encoded).unwrap();
        tampered["result"]["status"] = json!("EXACT_EQUALITY");
        tampered["result"]["relation"] = json!("NOT_EQUAL");
        let error = AuditBundle::from_json(&serde_json::to_string(&tampered).unwrap()).unwrap_err();
        assert!(error.to_string().contains("AUDIT_BUNDLE_HASH_MISMATCH"));
    }
}
