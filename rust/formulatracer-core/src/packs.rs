use crate::{typed_unify, FormulaTracerError, RelationKind, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct KnowledgeRule {
    pub rule_id: String,
    pub lhs: Value,
    pub rhs: Value,
    pub relation: RelationKind,
    #[serde(default)]
    pub required_algebraic_structures: Vec<String>,
    #[serde(default)]
    pub domain_conditions: Vec<String>,
    #[serde(default)]
    pub shape_conditions: Vec<String>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    pub direction: String,
    pub cost: u32,
    pub priority: i32,
    pub evidence: Value,
    pub reference: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct KnowledgePack {
    pub schema_version: String,
    pub pack_id: String,
    pub rules: Vec<KnowledgeRule>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderContract {
    pub provider_id: String,
    pub pattern: Value,
    pub relation: RelationKind,
    #[serde(default)]
    pub motifs: Vec<String>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub execution_metadata: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderPack {
    pub schema_version: String,
    pub pack_id: String,
    pub providers: Vec<ProviderContract>,
}

impl KnowledgePack {
    pub fn from_json(input: &str) -> Result<Self> {
        let pack: Self = serde_json::from_str(input)?;
        if pack.schema_version.is_empty() || pack.rules.iter().any(|rule| rule.rule_id.is_empty()) {
            Err(FormulaTracerError::InvalidPack(
                "knowledge pack requires version and rule IDs".into(),
            ))
        } else {
            Ok(pack)
        }
    }
}

impl ProviderPack {
    pub fn from_json(input: &str) -> Result<Self> {
        Ok(serde_json::from_str(input)?)
    }
    pub fn match_expression(&self, expression: &Value) -> Vec<ProviderMatch> {
        self.providers
            .iter()
            .filter_map(|provider| {
                let unification = typed_unify(&provider.pattern, expression);
                (unification.status != "NO_MATCH").then(|| ProviderMatch {
                    provider_id: provider.provider_id.clone(),
                    relation: provider.relation,
                    status: if unification.substitution.obligations.is_empty()
                        && provider.assumptions.is_empty()
                    {
                        if provider.relation.is_exact() {
                            "EXACT_MATCH"
                        } else {
                            "RELATIONAL_MATCH"
                        }
                    } else {
                        "MATCH_WITH_OBLIGATIONS"
                    }
                    .into(),
                    obligations: provider
                        .assumptions
                        .iter()
                        .cloned()
                        .chain(unification.substitution.obligations)
                        .collect(),
                })
            })
            .collect()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderMatch {
    pub provider_id: String,
    pub relation: RelationKind,
    pub status: String,
    pub obligations: Vec<String>,
}

/// Versioned scientific definitions composed from the existing Mathematical IR.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScientificDefinition {
    pub definition_id: String,
    pub name: String,
    pub expression: Value,
    pub expansion: Value,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub references: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum FormalizationLevel {
    Defined,
    TheoremRegistered,
    LeanStatementGenerated,
    LeanProved,
    LeanKernelVerified,
}

/// The native core decides applicability. Unknown facts remain obligations.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScientificTheorem {
    pub theorem_id: String,
    pub name: String,
    pub lhs: Value,
    pub rhs: Value,
    pub relation: RelationKind,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub domain_conditions: Vec<String>,
    #[serde(default)]
    pub shape_conditions: Vec<String>,
    pub formalization_level: FormalizationLevel,
    pub lean_theorem: Option<String>,
    #[serde(default)]
    pub references: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScientificRealization {
    pub realization_id: String,
    pub target: Value,
    pub implementation: Value,
    pub relation: RelationKind,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub proof_obligations: Vec<String>,
    pub error_evidence: Option<Value>,
    #[serde(default)]
    pub languages: Vec<String>,
    #[serde(default)]
    pub references: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ScientificFoundationPack {
    pub schema_version: String,
    pub pack_id: String,
    #[serde(default)]
    pub definitions: Vec<ScientificDefinition>,
    #[serde(default)]
    pub theorems: Vec<ScientificTheorem>,
    #[serde(default)]
    pub realizations: Vec<ScientificRealization>,
}

fn pack_error(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidPack(message.into())
}

impl ScientificFoundationPack {
    pub fn from_json(input: &str) -> Result<Self> {
        let pack: Self = serde_json::from_str(input)?;
        pack.validate()?;
        Ok(pack)
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema_version.is_empty() || self.pack_id.is_empty() {
            return Err(pack_error(
                "foundation pack requires schema_version and pack_id",
            ));
        }
        let mut ids = BTreeSet::new();
        for definition in &self.definitions {
            if definition.definition_id.is_empty() || !ids.insert(&definition.definition_id) {
                return Err(pack_error(
                    "foundation definition IDs must be non-empty and unique",
                ));
            }
        }
        for theorem in &self.theorems {
            if theorem.theorem_id.is_empty() || !ids.insert(&theorem.theorem_id) {
                return Err(pack_error(
                    "foundation theorem IDs must be non-empty and unique",
                ));
            }
            if theorem.relation == RelationKind::ExactUnderAssumptions
                && theorem.assumptions.is_empty()
                && theorem.domain_conditions.is_empty()
                && theorem.shape_conditions.is_empty()
            {
                return Err(pack_error("conditional exact theorem requires conditions"));
            }
            if theorem.formalization_level == FormalizationLevel::LeanKernelVerified
                && theorem.lean_theorem.as_deref().unwrap_or("").is_empty()
            {
                return Err(pack_error(
                    "kernel-verified theorem requires Lean theorem evidence",
                ));
            }
        }
        for realization in &self.realizations {
            if realization.realization_id.is_empty() || !ids.insert(&realization.realization_id) {
                return Err(pack_error(
                    "foundation realization IDs must be non-empty and unique",
                ));
            }
            if realization.relation.is_exact()
                && (!realization.proof_obligations.is_empty()
                    || realization.error_evidence.is_some())
            {
                return Err(pack_error(
                    "exact realization cannot carry approximation evidence",
                ));
            }
        }
        Ok(())
    }

    pub fn theorem_decision(&self, theorem_id: &str, facts: &BTreeSet<String>) -> Result<Value> {
        let theorem = self
            .theorems
            .iter()
            .find(|item| item.theorem_id == theorem_id)
            .ok_or_else(|| pack_error(format!("unknown foundation theorem: {theorem_id}")))?;
        let required = theorem
            .assumptions
            .iter()
            .chain(&theorem.domain_conditions)
            .chain(&theorem.shape_conditions)
            .cloned()
            .collect::<BTreeSet<_>>();
        let remaining = required.difference(facts).cloned().collect::<Vec<_>>();
        let applicable = remaining.is_empty();
        Ok(serde_json::json!({
            "theorem_id":theorem.theorem_id,
            "status":if applicable{"THEOREM_APPLICABLE"}else{"THEOREM_CONDITIONS_UNRESOLVED"},
            "relation":theorem.relation,
            "remaining_obligations":remaining,
            "formalization_level":theorem.formalization_level,
            "lean_theorem":theorem.lean_theorem,
            "rewrite_authorized":applicable && theorem.relation.is_exact()
        }))
    }

    pub fn realization_decision(
        &self,
        realization_id: &str,
        facts: &BTreeSet<String>,
    ) -> Result<Value> {
        let realization = self
            .realizations
            .iter()
            .find(|item| item.realization_id == realization_id)
            .ok_or_else(|| {
                pack_error(format!("unknown foundation realization: {realization_id}"))
            })?;
        let required = realization
            .assumptions
            .iter()
            .chain(&realization.proof_obligations)
            .cloned()
            .collect::<BTreeSet<_>>();
        let remaining = required.difference(facts).cloned().collect::<Vec<_>>();
        Ok(serde_json::json!({
            "realization_id":realization.realization_id,
            "status":if remaining.is_empty(){"REALIZATION_ADMISSIBLE"}else{"REALIZATION_OBLIGATIONS_UNRESOLVED"},
            "relation":realization.relation,
            "remaining_obligations":remaining,
            "error_evidence":realization.error_evidence,
            "languages":realization.languages,
            "exact_eclass_merge_allowed":remaining.is_empty() && realization.relation.is_exact()
        }))
    }
}

pub fn scientific_foundation_operation(request: &Value) -> Result<Value> {
    let pack: ScientificFoundationPack = serde_json::from_value(
        request
            .get("pack")
            .cloned()
            .ok_or_else(|| pack_error("foundation pack required"))?,
    )?;
    pack.validate()?;
    let facts = request
        .get("proven_facts")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect::<BTreeSet<_>>();
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "VALIDATE" => Ok(serde_json::json!({"status":"FOUNDATION_PACK_VALID",
            "definitions":pack.definitions.len(),"theorems":pack.theorems.len(),
            "realizations":pack.realizations.len()})),
        "CHECK_THEOREM" => pack.theorem_decision(
            request
                .get("theorem_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            &facts,
        ),
        "CHECK_REALIZATION" => pack.realization_decision(
            request
                .get("realization_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            &facts,
        ),
        action => Err(pack_error(format!(
            "unsupported foundation action: {action}"
        ))),
    }
}

#[cfg(test)]
mod scientific_tests {
    use super::*;
    use serde_json::json;

    fn pack() -> Value {
        json!({"schema_version":"1.0","pack_id":"test",
            "definitions":[{"definition_id":"gradient","name":"Gradient",
                "expression":{"op":"Gradient"},"expansion":{"op":"IndexedValue"}}],
            "theorems":[{"theorem_id":"mixed_partial","name":"Mixed partial symmetry",
                "lhs":{"op":"Derivative","order":["x","y"]},
                "rhs":{"op":"Derivative","order":["y","x"]},
                "relation":"EXACT_UNDER_ASSUMPTIONS","assumptions":["continuous_second_partials"],
                "formalization_level":"THEOREM_REGISTERED","lean_theorem":null}],
            "realizations":[{"realization_id":"central_difference","target":{"op":"Derivative"},
                "implementation":{"op":"CentralDifference"},"relation":"DISCRETIZATION_OF",
                "proof_obligations":["spacing_nonzero"],
                "error_evidence":{"order":2},"languages":["python","rust","cpp"]}]})
    }

    #[test]
    fn conditional_theorem_is_fail_closed_until_facts_are_proven() {
        let unresolved = scientific_foundation_operation(&json!({"action":"CHECK_THEOREM",
            "pack":pack(),"theorem_id":"mixed_partial","proven_facts":[]}))
        .unwrap();
        assert_eq!(unresolved["status"], "THEOREM_CONDITIONS_UNRESOLVED");
        assert_eq!(unresolved["rewrite_authorized"], false);
        let proven = scientific_foundation_operation(&json!({"action":"CHECK_THEOREM",
            "pack":pack(),"theorem_id":"mixed_partial",
            "proven_facts":["continuous_second_partials"]}))
        .unwrap();
        assert_eq!(proven["status"], "THEOREM_APPLICABLE");
        assert_eq!(proven["rewrite_authorized"], true);
    }

    #[test]
    fn discretization_never_enters_an_exact_eclass() {
        let decision = scientific_foundation_operation(&json!({"action":"CHECK_REALIZATION",
            "pack":pack(),"realization_id":"central_difference",
            "proven_facts":["spacing_nonzero"]}))
        .unwrap();
        assert_eq!(decision["status"], "REALIZATION_ADMISSIBLE");
        assert_eq!(decision["exact_eclass_merge_allowed"], false);
    }

    #[test]
    fn repository_physics_pack_is_native_validated() {
        let source = include_str!("../../../registry/scientific_foundations/physics-v1.json");
        let pack = ScientificFoundationPack::from_json(source).unwrap();
        assert!(pack.definitions.len() >= 10);
        assert!(pack.theorems.len() >= 10);
        assert!(pack.realizations.len() >= 5);
    }
}
