use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

use crate::{quotient_normalize, structural_isomorphism, RelationKind, StructuralFacts};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReconstructionStatus {
    Exact,
    EquivalentUnderAssumptions,
    ApproximationReconstructed,
    DiscretizationReconstructed,
    TruncationReconstructed,
    SamplingReconstructed,
    AlgorithmicRealizationReconstructed,
    CompositeRelationReconstructed,
    CorrectlyUnresolved,
    FalseAcceptance,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReconstructionRelation {
    pub kind: RelationKind,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub provenance: Vec<String>,
    pub error_evidence: Option<Value>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct ReconstructionSafety {
    #[serde(default)]
    pub mutation: bool,
    #[serde(default)]
    pub aliasing: bool,
    #[serde(default)]
    pub side_effects: bool,
    #[serde(default)]
    pub exceptions: bool,
    #[serde(default)]
    pub evaluation_order_sensitive: bool,
    #[serde(default)]
    pub unknown_call_effects: bool,
}

impl ReconstructionSafety {
    fn inline_safe(&self) -> bool {
        !(self.mutation
            || self.aliasing
            || self.side_effects
            || self.exceptions
            || self.evaluation_order_sensitive
            || self.unknown_call_effects)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TemporaryAssignment {
    pub name: String,
    pub expression: Value,
    #[serde(default)]
    pub uses: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderProjection {
    pub provider_id: String,
    pub version: Option<String>,
    pub language: Option<String>,
    pub operation: String,
    pub mathematical_target: Value,
    pub relation: RelationKind,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub obligations: Vec<String>,
    pub error_model: Option<Value>,
    #[serde(default)]
    pub provenance: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReconstructionRequest {
    pub original_theory: Value,
    pub reconstructed_theory: Option<Value>,
    #[serde(default)]
    pub structural_facts: StructuralFacts,
    #[serde(default)]
    pub temporaries: Vec<TemporaryAssignment>,
    pub result_expression: Option<Value>,
    #[serde(default)]
    pub safety: ReconstructionSafety,
    pub algorithm_ir: Option<Value>,
    pub provider_projection: Option<ProviderProjection>,
    #[serde(default)]
    pub relation_chain: Vec<ReconstructionRelation>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub proof_obligations: Vec<String>,
    #[serde(default)]
    pub exact_egraph_verified: bool,
    pub error: Option<Value>,
    pub range: Option<Value>,
    pub provenance: Option<Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReconstructionResult {
    pub schema_version: String,
    pub status: ReconstructionStatus,
    pub original_theory: Value,
    pub reconstructed_theory: Option<Value>,
    pub structural_witness: Option<Value>,
    pub binder_index_witness: Option<Value>,
    pub algorithm_reconstruction: Option<Value>,
    pub provider_projection: Option<ProviderProjection>,
    #[serde(default)]
    pub relation_chain: Vec<ReconstructionRelation>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub proof_obligations: Vec<String>,
    pub error: Option<Value>,
    pub range: Option<Value>,
    #[serde(default)]
    pub evidence: Vec<Value>,
    pub provenance: Option<Value>,
    pub unresolved_reason: Option<Value>,
    #[serde(default)]
    pub temporary_mapping: BTreeMap<String, Value>,
}

fn substitute_temporary(value: &Value, assignments: &BTreeMap<String, Value>) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| substitute_temporary(item, assignments))
                .collect(),
        ),
        Value::Object(object)
            if matches!(
                object.get("op").and_then(Value::as_str),
                Some("Temporary" | "FreeVariable")
            ) =>
        {
            object
                .get("name")
                .and_then(Value::as_str)
                .and_then(|name| assignments.get(name))
                .cloned()
                .unwrap_or_else(|| value.clone())
        }
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(key, item)| (key.clone(), substitute_temporary(item, assignments)))
                .collect(),
        ),
        _ => value.clone(),
    }
}

fn inline_temporaries(
    request: &ReconstructionRequest,
) -> Result<(Option<Value>, BTreeMap<String, Value>), Value> {
    if request.temporaries.is_empty() {
        return Ok((request.result_expression.clone(), BTreeMap::new()));
    }
    if !request.safety.inline_safe() {
        return Err(json!({
            "code":"INLINE_RECONSTRUCTION_UNRESOLVED",
            "blocking_stage":"INLINE_UNINLINE",
            "reason":"execution-sensitive temporary graph cannot be inlined safely"
        }));
    }
    let mut values = BTreeMap::new();
    for assignment in &request.temporaries {
        let expanded = substitute_temporary(&assignment.expression, &values);
        values.insert(assignment.name.clone(), expanded);
    }
    Ok((
        request
            .result_expression
            .as_ref()
            .map(|value| substitute_temporary(value, &values)),
        values,
    ))
}

fn reconstruct_loop(value: &Value) -> Result<Option<(Value, Value)>, Value> {
    let Some(object) = value.as_object() else {
        return Ok(None);
    };
    if object.get("op").and_then(Value::as_str) != Some("Loop") {
        return Ok(None);
    }
    let operation = object
        .get("update_op")
        .and_then(Value::as_str)
        .unwrap_or("");
    let identity_ok = match operation {
        "ADD" => object.get("initializer") == Some(&json!(0)),
        "MULTIPLY" => object.get("initializer") == Some(&json!(1)),
        _ => false,
    };
    let safe = object.get("side_effects").and_then(Value::as_bool) == Some(false)
        && object.get("interfering_mutation").and_then(Value::as_bool) == Some(false)
        && object.get("terminates").and_then(Value::as_bool) == Some(true);
    if !identity_ok || !safe {
        return Err(json!({
            "code":"LOOP_FOLD_RECONSTRUCTION_UNRESOLVED",
            "blocking_stage":"LOOP_FOLD",
            "missing": ["identity", "termination", "side-effect freedom"]
        }));
    }
    let bound_index = object.get("loop_variable").cloned().unwrap_or(Value::Null);
    let domain = object.get("index_domain").cloned().unwrap_or(Value::Null);
    let body = object.get("contribution").cloned().unwrap_or(Value::Null);
    let fold = json!({
        "op":"Fold",
        "operation":operation,
        "initializer":object.get("initializer").cloned().unwrap_or(Value::Null),
        "bound_index":bound_index,
        "index_domain":domain,
        "body":body,
        "ordered":true
    });
    let mathematical = json!({
        "op": if operation == "ADD" { "FiniteSum" } else { "FiniteProduct" },
        "bound_index":object.get("loop_variable").cloned().unwrap_or(Value::Null),
        "index_domain":object.get("index_domain").cloned().unwrap_or(Value::Null),
        "body":object.get("contribution").cloned().unwrap_or(Value::Null)
    });
    Ok(Some((mathematical, fold)))
}

fn relation_status(chain: &[ReconstructionRelation]) -> Option<ReconstructionStatus> {
    if chain.is_empty() {
        return None;
    }
    let kinds = chain.iter().map(|edge| edge.kind).collect::<BTreeSet<_>>();
    if kinds.len() > 1 {
        return Some(ReconstructionStatus::CompositeRelationReconstructed);
    }
    Some(match chain[0].kind {
        // Exact labels are claims to verify, not evidence. The caller's
        // canonical/e-graph check owns exact acceptance.
        RelationKind::ExactEquality | RelationKind::ExactUnderAssumptions => return None,
        RelationKind::ApproximationOf => ReconstructionStatus::ApproximationReconstructed,
        RelationKind::DiscretizationOf => ReconstructionStatus::DiscretizationReconstructed,
        RelationKind::TruncatedTo => ReconstructionStatus::TruncationReconstructed,
        RelationKind::SampledAs => ReconstructionStatus::SamplingReconstructed,
        RelationKind::AlgorithmicallyRealizedBy => {
            ReconstructionStatus::AlgorithmicRealizationReconstructed
        }
    })
}

pub fn reconstruct(request: &ReconstructionRequest) -> ReconstructionResult {
    let mut assumptions = request.assumptions.iter().cloned().collect::<BTreeSet<_>>();
    let mut obligations = request
        .proof_obligations
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut relations = request.relation_chain.clone();
    for relation in &relations {
        assumptions.extend(relation.assumptions.iter().cloned());
    }
    let (inlined, temporary_mapping) = match inline_temporaries(request) {
        Ok(value) => value,
        Err(reason) => return unresolved(request, reason, BTreeMap::new()),
    };
    let mut reconstructed = request.reconstructed_theory.clone().or(inlined);
    let mut algorithm_reconstruction = None;
    if reconstructed.is_none() {
        if let Some(algorithm) = &request.algorithm_ir {
            match reconstruct_loop(algorithm) {
                Ok(Some((mathematical, fold))) => {
                    reconstructed = Some(mathematical);
                    algorithm_reconstruction = Some(fold);
                    let floating = algorithm.get("floating_point").and_then(Value::as_bool)
                        == Some(true)
                        || algorithm
                            .get("numeric_domain")
                            .and_then(Value::as_str)
                            .is_some_and(|domain| domain.starts_with("IEEE754"));
                    if floating {
                        relations.push(ReconstructionRelation {
                            kind: RelationKind::AlgorithmicallyRealizedBy,
                            assumptions: vec!["recorded accumulation order".into()],
                            provenance: vec!["native-loop-fold:floating-execution".into()],
                            error_evidence: None,
                        });
                        obligations.insert("FLOATING_REDUCTION_ERROR_BOUND".into());
                    }
                }
                Ok(None) => {}
                Err(reason) => return unresolved(request, reason, temporary_mapping),
            }
        }
    }
    if reconstructed.is_none() {
        if let Some(provider) = &request.provider_projection {
            reconstructed = Some(provider.mathematical_target.clone());
            assumptions.extend(provider.assumptions.iter().cloned());
            obligations.extend(provider.obligations.iter().cloned());
            relations.push(ReconstructionRelation {
                kind: provider.relation,
                assumptions: provider.assumptions.clone(),
                provenance: provider.provenance.clone(),
                error_evidence: provider.error_model.clone(),
            });
        }
    }
    let Some(reconstructed) = reconstructed else {
        return unresolved(
            request,
            json!({
                "code":"RECONSTRUCTION_INPUT_UNAVAILABLE",
                "blocking_stage":"LANGUAGE_FRONTEND",
                "missing_capability":"generated source or independently observed Mathematical IR"
            }),
            temporary_mapping,
        );
    };
    let structural = structural_isomorphism(
        &request.original_theory,
        &reconstructed,
        &request.structural_facts,
    );
    let witness_value = serde_json::to_value(&structural.witness).unwrap_or(Value::Null);
    let binder_index_witness = json!({
        "binder_mapping": structural.witness.binder_mapping,
        "index_mapping": structural.witness.index_mapping,
        "blocked_ambiguities": structural.witness.blocked_reasons,
    });
    let canonical_exact = quotient_normalize(&request.original_theory, &request.structural_facts)
        .representative
        == quotient_normalize(&reconstructed, &request.structural_facts).representative;
    let exact =
        canonical_exact || (request.exact_egraph_verified && structural.comparison_may_proceed);
    let status = if let Some(status) = relation_status(&relations) {
        // A recorded non-exact relation is semantically stronger than an
        // incidental canonical shape match; it must never be exact-merged.
        status
    } else if exact {
        if assumptions.is_empty() {
            ReconstructionStatus::Exact
        } else {
            ReconstructionStatus::EquivalentUnderAssumptions
        }
    } else {
        return ReconstructionResult {
            schema_version: "1.0".into(),
            status: ReconstructionStatus::CorrectlyUnresolved,
            original_theory: request.original_theory.clone(),
            reconstructed_theory: Some(reconstructed),
            structural_witness: Some(witness_value),
            binder_index_witness: Some(binder_index_witness),
            algorithm_reconstruction,
            provider_projection: request.provider_projection.clone(),
            relation_chain: relations,
            assumptions: assumptions.into_iter().collect(),
            proof_obligations: obligations.into_iter().collect(),
            error: request.error.clone(),
            range: request.range.clone(),
            evidence: vec![],
            provenance: request.provenance.clone(),
            unresolved_reason: Some(json!({
                "code":"RELATION_NOT_ESTABLISHED",
                "blocking_stage":"EXACT_EGRAPH_OR_RELATION_GRAPH",
                "structural_isomorphism_is_not_proof":true
            })),
            temporary_mapping,
        };
    };
    ReconstructionResult {
        schema_version: "1.0".into(),
        status,
        original_theory: request.original_theory.clone(),
        reconstructed_theory: Some(reconstructed),
        structural_witness: Some(witness_value),
        binder_index_witness: Some(binder_index_witness),
        algorithm_reconstruction,
        provider_projection: request.provider_projection.clone(),
        relation_chain: relations,
        assumptions: assumptions.into_iter().collect(),
        proof_obligations: obligations.into_iter().collect(),
        error: request.error.clone(),
        range: request.range.clone(),
        evidence: vec![json!({
            "kind": if exact { "EXACT_EGRAPH_OR_CANONICAL" } else { "RELATION_GRAPH" },
            "structural_witness_proof_authority":false
        })],
        provenance: request.provenance.clone(),
        unresolved_reason: None,
        temporary_mapping,
    }
}

fn unresolved(
    request: &ReconstructionRequest,
    reason: Value,
    temporary_mapping: BTreeMap<String, Value>,
) -> ReconstructionResult {
    ReconstructionResult {
        schema_version: "1.0".into(),
        status: ReconstructionStatus::CorrectlyUnresolved,
        original_theory: request.original_theory.clone(),
        reconstructed_theory: request.reconstructed_theory.clone(),
        structural_witness: None,
        binder_index_witness: None,
        algorithm_reconstruction: None,
        provider_projection: request.provider_projection.clone(),
        relation_chain: request.relation_chain.clone(),
        assumptions: request.assumptions.clone(),
        proof_obligations: request.proof_obligations.clone(),
        error: request.error.clone(),
        range: request.range.clone(),
        evidence: vec![],
        provenance: request.provenance.clone(),
        unresolved_reason: Some(reason),
        temporary_mapping,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(name: &str) -> Value {
        json!({"op":"FreeVariable","name":name})
    }

    fn request(theory: Value) -> ReconstructionRequest {
        ReconstructionRequest {
            original_theory: theory,
            reconstructed_theory: None,
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
        }
    }

    #[test]
    fn direct_exact_and_operator_mutation_do_not_collapse() {
        let theory = json!({"op":"Add","args":[v("x"),json!({"op":"Constant","value":1})]});
        let mut exact = request(theory.clone());
        exact.reconstructed_theory = Some(theory);
        assert_eq!(reconstruct(&exact).status, ReconstructionStatus::Exact);
        exact.reconstructed_theory =
            Some(json!({"op":"Subtract","args":[v("x"),json!({"op":"Constant","value":1})]}));
        assert_eq!(
            reconstruct(&exact).status,
            ReconstructionStatus::CorrectlyUnresolved
        );
    }

    #[test]
    fn safe_temporaries_inline_but_side_effects_fail_closed() {
        let theory = json!({"op":"Multiply","args":[v("a"),v("b")]});
        let mut item = request(theory.clone());
        item.temporaries = vec![TemporaryAssignment {
            name: "t".into(),
            expression: theory,
            uses: 1,
        }];
        item.result_expression = Some(json!({"op":"Temporary","name":"t"}));
        assert_eq!(reconstruct(&item).status, ReconstructionStatus::Exact);
        item.safety.side_effects = true;
        assert_eq!(
            reconstruct(&item).unresolved_reason.unwrap()["code"],
            "INLINE_RECONSTRUCTION_UNRESOLVED"
        );
    }

    #[test]
    fn safe_loop_reconstructs_sum_and_mutated_bound_does_not_match() {
        let theory = json!({"op":"FiniteSum","bound_index":"i","index_domain":{"lower":0,"upper_exclusive":"N"},"body":{"op":"BoundVariable","name":"i"}});
        let mut item = request(theory.clone());
        item.algorithm_ir = Some(
            json!({"op":"Loop","initializer":0,"update_op":"ADD","loop_variable":"i","index_domain":{"lower":0,"upper_exclusive":"N"},"contribution":{"op":"BoundVariable","name":"i"},"side_effects":false,"interfering_mutation":false,"terminates":true}),
        );
        assert_eq!(reconstruct(&item).status, ReconstructionStatus::Exact);
        item.algorithm_ir.as_mut().unwrap()["index_domain"]["upper_exclusive"] = json!("N+1");
        assert_eq!(
            reconstruct(&item).status,
            ReconstructionStatus::CorrectlyUnresolved
        );
    }

    #[test]
    fn floating_loop_is_algorithmic_realization_not_exact_sum() {
        let theory = json!({"op":"FiniteSum","bound_index":"i","index_domain":{"lower":0,"upper_exclusive":"N"},"body":{"op":"BoundVariable","name":"i"}});
        let mut item = request(theory);
        item.algorithm_ir = Some(
            json!({"op":"Loop","initializer":0,"update_op":"ADD","loop_variable":"i","index_domain":{"lower":0,"upper_exclusive":"N"},"contribution":{"op":"BoundVariable","name":"i"},"side_effects":false,"interfering_mutation":false,"terminates":true,"numeric_domain":"IEEE754_BINARY64"}),
        );
        let result = reconstruct(&item);
        assert_eq!(
            result.status,
            ReconstructionStatus::AlgorithmicRealizationReconstructed
        );
        assert_eq!(
            result.proof_obligations,
            vec!["FLOATING_REDUCTION_ERROR_BOUND"]
        );
    }

    #[test]
    fn provider_projection_preserves_non_exact_relation_and_obligations() {
        let theory = json!({"op":"Integral","variable":"x","body":v("f")});
        let mut item = request(theory);
        item.provider_projection = Some(ProviderProjection {
            provider_id: "generic.quadrature".into(),
            version: Some("1".into()),
            language: Some("python".into()),
            operation: "quadrature".into(),
            mathematical_target: json!({"op":"FiniteSum","bound_index":"i","body":v("w_i_f_i")}),
            relation: RelationKind::DiscretizationOf,
            assumptions: vec!["quadrature rule valid".into()],
            obligations: vec!["SMOOTHNESS_REQUIRED".into()],
            error_model: None,
            provenance: vec!["provider-pack:test".into()],
        });
        let result = reconstruct(&item);
        assert_eq!(
            result.status,
            ReconstructionStatus::DiscretizationReconstructed
        );
        assert_eq!(result.proof_obligations, vec!["SMOOTHNESS_REQUIRED"]);
        assert!(result.error.is_none());
    }

    #[test]
    fn composite_relations_are_not_exact_merged() {
        let mut item = request(v("continuous_transform"));
        item.reconstructed_theory = Some(v("fft_algorithm"));
        item.relation_chain = vec![
            ReconstructionRelation {
                kind: RelationKind::SampledAs,
                assumptions: vec!["sampling grid".into()],
                provenance: vec![],
                error_evidence: None,
            },
            ReconstructionRelation {
                kind: RelationKind::AlgorithmicallyRealizedBy,
                assumptions: vec![],
                provenance: vec![],
                error_evidence: None,
            },
        ];
        let result = reconstruct(&item);
        assert_eq!(
            result.status,
            ReconstructionStatus::CompositeRelationReconstructed
        );
        assert_eq!(result.assumptions, vec!["sampling grid"]);
    }

    #[test]
    fn structural_rename_alone_never_proves_exactness() {
        let mut item = request(v("x"));
        item.reconstructed_theory = Some(v("y"));
        item.structural_facts
            .symbol_types
            .insert("x".into(), json!({"domain":"REAL"}));
        item.structural_facts
            .symbol_types
            .insert("y".into(), json!({"domain":"REAL"}));
        let result = reconstruct(&item);
        assert_eq!(result.status, ReconstructionStatus::CorrectlyUnresolved);
        assert_eq!(result.structural_witness.unwrap()["proof_authority"], false);
    }
}
