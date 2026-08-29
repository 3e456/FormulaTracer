//! Native Rust API. The stable C ABI delegates to this exact implementation.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::{
    document_semantic_hash, parse_tex, semantic_equal, to_tex, AuditBundle, MathematicalFunction,
    ReconstructionResult, Result, SemanticDocument,
};

#[derive(Debug, Clone)]
pub struct Formula {
    document: SemanticDocument,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SemanticObject {
    pub schema_version: String,
    pub ir: Value,
    pub semantic_hash: Option<String>,
}

impl SemanticObject {
    fn from_document(document: &SemanticDocument) -> Self {
        Self {
            schema_version: document.schema_version.clone(),
            ir: document.payload.clone(),
            semantic_hash: document_semantic_hash(document).ok(),
        }
    }

    pub fn to_tex(&self) -> String {
        to_tex(&self.ir)
    }

    pub fn to_value(&self) -> Result<Value> {
        Ok(serde_json::to_value(self)?)
    }

    pub fn as_function(
        &self,
        assumptions: Vec<String>,
        evidence: Vec<Value>,
        provenance: Option<Value>,
    ) -> MathematicalFunction {
        MathematicalFunction::from_expression(self.ir.clone(), assumptions, evidence, provenance)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VerificationResult {
    pub schema_version: String,
    pub status: String,
    pub relation: String,
    pub theory_hash: Option<String>,
    pub implementation_hash: Option<String>,
    pub theory: Option<SemanticObject>,
    pub implementation: Option<SemanticObject>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub diagnostics: Vec<String>,
    #[serde(default)]
    pub evidence: Vec<Value>,
    pub error: Option<Value>,
    pub range: Option<Value>,
    pub provenance: Option<Value>,
    pub debugger: Option<Value>,
    #[serde(default)]
    pub reconstruction: Option<ReconstructionResult>,
    /// ABI-v1 compatibility projection. It is derived from `implementation`.
    pub tex: String,
}

impl VerificationResult {
    pub fn to_audit_bundle(
        &self,
        source_context: Value,
        environment: Value,
        artifact_lineage: Value,
    ) -> Result<AuditBundle> {
        AuditBundle::new(self.clone(), source_context, environment, artifact_lineage)
    }

    fn projected_function(&self, value: &Value, keys: &[&str]) -> Option<MathematicalFunction> {
        let expression = keys
            .iter()
            .find_map(|key| value.get(*key))
            .filter(|candidate| candidate.is_object())?;
        Some(MathematicalFunction::from_expression(
            expression.clone(),
            self.assumptions.clone(),
            self.evidence.clone(),
            self.provenance.clone(),
        ))
    }

    pub fn error_function(&self) -> Option<MathematicalFunction> {
        self.error.as_ref().and_then(|error| {
            let status = error.get("status").and_then(Value::as_str)?;
            if !matches!(
                status,
                "EXACT_ZERO_BOUND"
                    | "KERNEL_VERIFIED_BOUND"
                    | "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS"
                    | "REFERENCE_CONTRACT_BOUND"
                    | "SYMBOLIC_BOUND"
                    | "INTERVAL_BOUND"
                    | "COMPOSED_BOUND"
                    | "CERTIFIED_WITHIN_ERROR_BOUND"
            ) {
                return None;
            }
            self.projected_function(
                error,
                &["expression", "symbolic_expression", "error_expression"],
            )
        })
    }

    pub fn range_lower_function(&self) -> Option<MathematicalFunction> {
        self.range
            .as_ref()
            .and_then(|range| self.projected_function(range, &["lower", "lower_bound"]))
    }

    pub fn range_upper_function(&self) -> Option<MathematicalFunction> {
        self.range
            .as_ref()
            .and_then(|range| self.projected_function(range, &["upper", "upper_bound"]))
    }

    pub fn to_tex(&self) -> String {
        fn escaped(value: &str) -> String {
            value
                .replace('\\', r"\textbackslash{}")
                .replace('&', r"\&")
                .replace('%', r"\%")
                .replace('$', r"\$")
                .replace('#', r"\#")
                .replace('_', r"\_")
                .replace('{', r"\{")
                .replace('}', r"\}")
        }
        let mut out = String::from(
            "\\section*{FormulaTracer Verification Certificate}\n\\begin{description}\n",
        );
        out.push_str(&format!(
            "\\item[Status] \\texttt{{{}}}\n\\item[Relation] \\texttt{{{}}}\n",
            escaped(&self.status),
            escaped(&self.relation)
        ));
        out.push_str("\\end{description}\n");
        if let Some(theory) = &self.theory {
            out.push_str("\\subsection*{Ideal Theory}\n\\[\n");
            out.push_str(&theory.to_tex());
            out.push_str("\n\\]\n");
        }
        if let Some(implementation) = &self.implementation {
            out.push_str("\\subsection*{Reconstructed Implementation Mathematics}\n\\[\n");
            out.push_str(&implementation.to_tex());
            out.push_str("\n\\]\n");
        }
        if let Some(reconstruction) = &self.reconstruction {
            out.push_str("\\subsection*{Formula--Code--Formula Reconstruction}\n");
            out.push_str(&format!(
                "\\textbf{{Status:}} \\texttt{{{}}}\\\\\n",
                escaped(&format!("{:?}", reconstruction.status).to_uppercase())
            ));
            out.push_str("\\textbf{Original Theory:}\\[\n");
            out.push_str(&to_tex(&reconstruction.original_theory));
            out.push_str("\n\\]\n");
            if let Some(reconstructed) = &reconstruction.reconstructed_theory {
                out.push_str("\\textbf{Reconstructed Theory:}\\[\n");
                out.push_str(&to_tex(reconstructed));
                out.push_str("\n\\]\n");
            }
            if !reconstruction.relation_chain.is_empty() {
                out.push_str("\\textbf{Relation chain:}\\begin{itemize}\n");
                for edge in &reconstruction.relation_chain {
                    out.push_str(&format!("\\item \\texttt{{{:?}}}\n", edge.kind));
                }
                out.push_str("\\end{itemize}\n");
            }
            if !reconstruction.proof_obligations.is_empty() {
                out.push_str("\\textbf{Proof obligations:}\\begin{itemize}\n");
                for obligation in &reconstruction.proof_obligations {
                    out.push_str(&format!("\\item {}\n", escaped(obligation)));
                }
                out.push_str("\\end{itemize}\n");
            }
            if let Some(reason) = &reconstruction.unresolved_reason {
                out.push_str("\\textbf{Unresolved reason:}\\begin{verbatim}\n");
                out.push_str(&serde_json::to_string_pretty(reason).unwrap_or_default());
                out.push_str("\n\\end{verbatim}\n");
            }
        }
        if !self.assumptions.is_empty() {
            out.push_str("\\subsection*{Assumptions}\n\\begin{itemize}\n");
            for assumption in &self.assumptions {
                out.push_str(&format!("\\item {}\n", escaped(assumption)));
            }
            out.push_str("\\end{itemize}\n");
        }
        if let Some(error) = &self.error {
            out.push_str("\\subsection*{Error Evidence}\n\\begin{verbatim}\n");
            out.push_str(&serde_json::to_string_pretty(error).unwrap_or_default());
            out.push_str("\n\\end{verbatim}\n");
        } else {
            out.push_str("\\subsection*{Error Evidence}\n\\texttt{BOUND\\_NOT\\_AVAILABLE}\n");
        }
        if let Some(range) = &self.range {
            out.push_str("\\subsection*{Certified Range}\n\\begin{verbatim}\n");
            out.push_str(&serde_json::to_string_pretty(range).unwrap_or_default());
            out.push_str("\n\\end{verbatim}\n");
        }
        out.push_str("\\subsection*{Evidence}\n\\begin{itemize}\n");
        if self.evidence.is_empty() {
            out.push_str("\\item \\texttt{UNRESOLVED}\n");
        } else {
            for evidence in &self.evidence {
                let kind = evidence
                    .get("level")
                    .or_else(|| evidence.get("kind"))
                    .and_then(Value::as_str)
                    .unwrap_or("UNRESOLVED");
                out.push_str(&format!("\\item \\texttt{{{}}}\n", escaped(kind)));
            }
        }
        out.push_str("\\end{itemize}\n");
        if let Some(provenance) = &self.provenance {
            out.push_str("\\subsection*{Provenance Summary}\n\\begin{verbatim}\n");
            out.push_str(&serde_json::to_string_pretty(provenance).unwrap_or_default());
            out.push_str("\n\\end{verbatim}\n");
        }
        out
    }

    pub fn to_value(&self) -> Result<Value> {
        Ok(serde_json::to_value(self)?)
    }

    pub fn to_json(&self) -> Result<String> {
        Ok(serde_json::to_string(self)?)
    }

    pub fn explain(&self, language: &str) -> String {
        if language.starts_with("ja") {
            format!("検証状態: {} / 関係: {}", self.status, self.relation)
        } else {
            format!(
                "Verification status: {}; relation: {}",
                self.status, self.relation
            )
        }
    }
}

impl Formula {
    pub fn from_tex(input: &str) -> Result<Self> {
        Ok(Self {
            document: SemanticDocument {
                schema_version: "1.0".into(),
                kind: "MATHEMATICAL_IR".into(),
                payload: parse_tex(input)?,
                origins: vec![],
            },
        })
    }

    pub fn from_json(input: &str) -> Result<Self> {
        Ok(Self {
            document: SemanticDocument::from_json(input)?,
        })
    }

    pub fn from_document(document: SemanticDocument) -> Self {
        Self { document }
    }

    pub fn document(&self) -> &SemanticDocument {
        &self.document
    }

    pub fn verify_against(&self, implementation: &Self) -> VerificationResult {
        let exact = semantic_equal(&self.document.payload, &implementation.document.payload);
        let theory_object = SemanticObject::from_document(&self.document);
        let implementation_object = SemanticObject::from_document(&implementation.document);
        VerificationResult {
            schema_version: "1.0".into(),
            status: if exact { "EXACT_EQUALITY" } else { "DIVERGED" }.into(),
            relation: if exact { "EXACT_EQUALITY" } else { "NOT_EQUAL" }.into(),
            theory_hash: document_semantic_hash(&self.document).ok(),
            implementation_hash: document_semantic_hash(&implementation.document).ok(),
            theory: Some(theory_object),
            implementation: Some(implementation_object.clone()),
            assumptions: vec![],
            diagnostics: vec![],
            evidence: vec![json!({
                "kind":"NATIVE_SEMANTIC_COMPARISON",
                "level":"FORMALLY_DERIVED",
                "kernel_verified":false
            })],
            error: None,
            range: None,
            provenance: None,
            debugger: None,
            reconstruction: None,
            tex: implementation_object.to_tex(),
        }
    }

    pub fn inspect_without_theory(&self) -> VerificationResult {
        let implementation = SemanticObject::from_document(&self.document);
        VerificationResult {
            schema_version: "1.0".into(),
            status: "UNRESOLVED".into(),
            relation: "UNRESOLVED".into(),
            theory_hash: None,
            implementation_hash: document_semantic_hash(&self.document).ok(),
            theory: None,
            implementation: Some(implementation.clone()),
            assumptions: vec![],
            diagnostics: vec![
                "verification requires an independent theory and implementation".into(),
            ],
            evidence: vec![],
            error: None,
            range: None,
            provenance: None,
            debugger: None,
            reconstruction: None,
            tex: implementation.to_tex(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{reconstruct, ReconstructionRequest, ReconstructionSafety, StructuralFacts};

    #[test]
    fn native_api_exposes_the_same_complete_result_contract() {
        let theory = Formula::from_json(r#"{"op":"Constant","value":42,"radix":16}"#).unwrap();
        let implementation =
            Formula::from_json(r#"{"op":"Constant","value":42,"radix":10}"#).unwrap();
        let result = theory.verify_against(&implementation);
        assert_eq!(result.status, "EXACT_EQUALITY");
        assert_eq!(result.relation, "EXACT_EQUALITY");
        assert!(result.assumptions.is_empty());
        assert!(result.error.is_none() && result.range.is_none());
        assert_eq!(result.tex, "42");
        assert!(result.to_tex().contains("Verification Certificate"));
        assert_eq!(result.implementation.as_ref().unwrap().to_tex(), "42");
        assert_eq!(result.evidence[0]["kernel_verified"], false);
    }

    #[test]
    fn certified_error_and_range_project_to_functions_without_empirical_promotion() {
        let formula = Formula::from_json(r#"{"op":"FreeVariable","name":"x"}"#).unwrap();
        let mut result = formula.verify_against(&formula);
        result.error = Some(json!({
            "status":"CERTIFIED_WITHIN_ERROR_BOUND",
            "expression":{"op":"Multiply","args":[{"op":"Constant","value":0.1},{"op":"FreeVariable","name":"x"}]}
        }));
        result.range = Some(json!({
            "lower":{"op":"Negate","args":[{"op":"FreeVariable","name":"x"}]},
            "upper":{"op":"FreeVariable","name":"x"}
        }));
        assert!(result.error_function().is_some());
        assert!(result.range_lower_function().is_some());
        assert!(result.range_upper_function().is_some());
        result.error = Some(json!({"status":"EMPIRICALLY_WITHIN_TOLERANCE"}));
        assert!(result.error_function().is_none());
    }

    #[test]
    fn certificate_projects_native_reconstruction_without_reclassification() {
        let formula = Formula::from_json(r#"{"op":"Constant","value":2}"#).unwrap();
        let mut result = formula.verify_against(&formula);
        result.reconstruction = Some(reconstruct(&ReconstructionRequest {
            original_theory: json!({"op":"Constant","value":2}),
            reconstructed_theory: Some(json!({"op":"Constant","value":2})),
            structural_facts: StructuralFacts::default(),
            temporaries: vec![],
            result_expression: None,
            safety: ReconstructionSafety::default(),
            algorithm_ir: None,
            provider_projection: None,
            relation_chain: vec![],
            assumptions: vec![],
            proof_obligations: vec![],
            exact_egraph_verified: false,
            error: None,
            range: None,
            provenance: None,
        }));
        let tex = result.to_tex();
        assert!(tex.contains("Formula--Code--Formula Reconstruction"));
        assert!(tex.contains("EXACT"));
    }
}
