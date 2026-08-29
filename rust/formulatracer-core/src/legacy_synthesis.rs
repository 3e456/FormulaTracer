//! Native ownership for synthesis safety, semantic round trips, and repair decisions.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn stable_id(prefix: &str, value: &Value) -> String {
    let digest = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(value).unwrap_or_default())
    );
    format!("{prefix}:{}", &digest[..16])
}
fn normalize(node: &Value) -> Value {
    match node {
        Value::Array(values) => Value::Array(values.iter().map(normalize).collect()),
        Value::Object(object) => {
            const IGNORED: &[&str] = &[
                "source_spans",
                "source_node_ids",
                "source_span",
                "operator_span",
                "callable_span",
                "argument_spans",
                "keyword_spans",
                "condition_span",
                "api",
                "local_name",
                "canonical_name",
                "shape_constraints",
                "alignment_constraints",
            ];
            let mut out: Map<String, Value> = object
                .iter()
                .filter(|(k, _)| !IGNORED.contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), normalize(v)))
                .collect();
            if matches!(
                out.get("op").and_then(Value::as_str),
                Some("FreeVariable" | "BoundVariable")
            ) {
                if let Some(name) = out.get("name").and_then(Value::as_str) {
                    out.insert(
                        "name".into(),
                        json!(name.replace("::", ".").rsplit('.').next().unwrap_or(name)),
                    );
                }
            }
            if out.get("op").and_then(Value::as_str) == Some("Constant") {
                if let Some(value) = out.get("value").and_then(Value::as_f64) {
                    if value.fract() == 0.0 {
                        out.insert("value".into(), json!(value as i64));
                    }
                }
            }
            Value::Object(out)
        }
        _ => node.clone(),
    }
}
fn relation_kind(expression: &Value) -> &'static str {
    match expression
        .get("implementation_relation")
        .or_else(|| expression.get("relation"))
        .and_then(Value::as_str)
        .unwrap_or("")
    {
        "EXACT_EQUAL" | "EXACT_IMPLEMENTATION" => "EXACT_IMPLEMENTATION",
        "EQUIVALENT_UNDER_ASSUMPTIONS" => "EQUIVALENT_UNDER_ASSUMPTIONS",
        "APPROXIMATION" | "APPROXIMATION_OF" | "APPROXIMATE_IMPLEMENTATION" => {
            "APPROXIMATE_IMPLEMENTATION"
        }
        "DISCRETIZATION" | "DISCRETIZATION_OF" | "DISCRETIZED_IMPLEMENTATION" => {
            "DISCRETIZED_IMPLEMENTATION"
        }
        "TRUNCATION" | "TRUNCATED_TO" | "TRUNCATED_IMPLEMENTATION" => "TRUNCATED_IMPLEMENTATION",
        "SAMPLED_AS" | "SAMPLED_IMPLEMENTATION" => "SAMPLED_IMPLEMENTATION",
        "ALGORITHMICALLY_REALIZED_BY" | "ALGORITHMIC_REALIZATION" => "ALGORITHMIC_REALIZATION",
        _ if expression.get("family_id").is_some() => "APPROXIMATE_IMPLEMENTATION",
        _ => "EXACT_IMPLEMENTATION",
    }
}
fn decision(r: &Value) -> Value {
    let language = r["language"].as_str().unwrap_or("").to_ascii_lowercase();
    let constraints = &r["constraints"];
    let expression = &r["expression"];
    let mut obligations = Vec::<String>::new();
    if !matches!(language.as_str(), "python" | "rust" | "cpp") {
        obligations.push("SUPPORTED_TARGET_LANGUAGE".into());
    }
    if constraints
        .get("language")
        .and_then(Value::as_str)
        .is_some_and(|x| !x.eq_ignore_ascii_case(&language))
    {
        obligations.push("LANGUAGE_CONSTRAINT_MATCH".into());
    }
    let allowed: BTreeSet<&str> = constraints
        .get("allowed_approximations")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect();
    if let Some(family) = expression.get("family_id").and_then(Value::as_str) {
        if !allowed.contains(family) {
            obligations.push(format!("AUTHORIZED_APPROXIMATION:{family}"));
        }
    }
    let assumptions: BTreeSet<&str> = r
        .get("assumptions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect();
    for required in expression
        .get("required_assumptions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        if !assumptions.contains(required) {
            obligations.push(format!("ASSUMPTION:{required}"));
        }
    }
    for item in expression
        .get("proof_obligations")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if item.get("status").and_then(Value::as_str) != Some("DISCHARGED") {
            obligations.push(
                item.get("statement")
                    .and_then(Value::as_str)
                    .unwrap_or("OPEN_PROOF_OBLIGATION")
                    .into(),
            );
        }
    }
    if let Some(provider) = r.get("provider").filter(|v| !v.is_null()) {
        if provider
            .get("language")
            .and_then(Value::as_str)
            .is_some_and(|x| !x.eq_ignore_ascii_case(&language))
        {
            obligations.push("PROVIDER_LANGUAGE_COMPATIBILITY".into());
        }
        if let (Some(want), Some(have)) = (
            constraints.get("numeric_domain").and_then(Value::as_str),
            provider.get("supported_domain").and_then(Value::as_str),
        ) {
            if want != have {
                obligations.push("PROVIDER_DOMAIN_COMPATIBILITY".into());
            }
        }
        for key in [
            "dtype",
            "shape",
            "axis",
            "normalization_convention",
            "sign_convention",
            "truncation_parameter",
        ] {
            if let (Some(a), Some(b)) = (r.get(key), provider.get(key)) {
                if !a.is_null() && !b.is_null() && a != b {
                    obligations.push(format!(
                        "PROVIDER_{}_COMPATIBILITY",
                        key.to_ascii_uppercase()
                    ));
                }
            }
        }
    }
    obligations.sort();
    obligations.dedup();
    let relation = relation_kind(expression);
    let exact = relation == "EXACT_IMPLEMENTATION";
    let status = if obligations.is_empty() && exact {
        "SAFE_TO_GENERATE_EXACT"
    } else if obligations.is_empty() {
        "GENERATABLE_WITH_EXPLICIT_RELATION"
    } else {
        "GENERATABLE_WITH_EXPLICIT_OBLIGATIONS"
    };
    json!({"decision_id":stable_id("generation-decision",&json!([expression,language,constraints,r.get("provider")])),"relation":relation,"status":status,"safe_to_generate_exact":status=="SAFE_TO_GENERATE_EXACT","remaining_obligations":obligations,"assumptions":assumptions,"generated_target_semantic_id":stable_id("generated-target",&normalize(expression)),"semantic_owner":"RUST_CORE","provider_compatible":!status.ends_with("OBLIGATIONS")})
}
fn round_trip(r: &Value) -> Value {
    if let Some(error) = r.get("error").and_then(Value::as_str) {
        return json!({"status":"ROUND_TRIP_UNRESOLVED","comparison":{"match":false,"error":error},"divergence":{"stage":"FRONTEND_REEXTRACTION","type":"FRONTEND_REEXTRACTION_DIVERGENCE","expected":r["expected"],"actual":{"error":error},"status":"FIRST_SYNTHESIS_DIVERGENCE"}});
    }
    let expected = normalize(&r["expected"]);
    let actual = normalize(&r["actual"]);
    let matched = expected == actual;
    json!({"status":if matched{"ROUND_TRIP_VERIFIED"}else{"ROUND_TRIP_DIVERGENCE_LOCALIZED"},"comparison":{"match":matched,"expected":expected,"actual":actual},"divergence":if matched{Value::Null}else{json!({"stage":"FRONTEND_REEXTRACTION","type":"FRONTEND_REEXTRACTION_DIVERGENCE","expected":expected,"actual":actual,"status":"FIRST_SYNTHESIS_DIVERGENCE"})}})
}
fn propose(r: &Value) -> Value {
    let finding = &r["finding"];
    let kind = finding.get("type").and_then(Value::as_str).unwrap_or("");
    if !matches!(
        kind,
        "OPERATOR_MISMATCH"
            | "CONSTANT_MISMATCH"
            | "AXIS_MISMATCH"
            | "REDUCTION_MISMATCH"
            | "APPROXIMATION_FAMILY_MISMATCH"
    ) || finding.get("source").is_none_or(Value::is_null)
    {
        return Value::Null;
    }
    let replacement = match kind {
        "CONSTANT_MISMATCH" => finding["expected"].get("value").map(|x| x.to_string()),
        "AXIS_MISMATCH" => finding["expected"].get("axes").map(|x| x.to_string()),
        _ => None,
    };
    json!({"repair_id":stable_id("repair",&json!([finding["finding_id"],finding["expected"]])),"divergence_type":kind,"source_file":finding["source"]["file"].as_str().unwrap_or(""),"source_span":finding["source"],"expected_semantics":finding["expected"],"actual_semantics":finding["actual"],"replacement_text":replacement,"status":"CANDIDATE_ONLY"})
}
pub fn legacy_synthesis_operation(r: &Value) -> Result<Value> {
    match r["action"].as_str().unwrap_or("") {
        "NORMALIZE" => Ok(normalize(&r["node"])),
        "DECIDE" => Ok(decision(r)),
        "ROUND_TRIP" => Ok(round_trip(r)),
        "PROPOSE_REPAIR" => Ok(propose(r)),
        "VERIFY_REPAIR" => {
            let success = r["debug_status"].as_str() == Some("NO_SEMANTIC_DIVERGENCE_FOUND")
                && matches!(
                    r["end_to_end_status"].as_str(),
                    Some(
                        "END_TO_END_KERNEL_VERIFIED"
                            | "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
                            | "END_TO_END_ENCLOSURE_VERIFIED"
                            | "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS"
                    )
                );
            Ok(
                json!({"candidate_status":if success{"REPAIR_VERIFIED"}else{"REPAIR_REANALYSIS_FAILED"},"status":if success{"REPAIR_VERIFIED"}else{"REPAIR_NOT_VERIFIED"}}),
            )
        }
        other => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_SYNTHESIS_ACTION:{other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn open_obligation_never_becomes_safe() {
        let d = decision(
            &json!({"language":"python","expression":{"op":"Add","proof_obligations":[{"statement":"x>0","status":"OPEN"}]},"constraints":{"language":"python","allowed_approximations":[],"numeric_domain":"real"},"assumptions":[]}),
        );
        assert_eq!(d["safe_to_generate_exact"], false);
    }
    #[test]
    fn formatting_metadata_does_not_change_round_trip() {
        let r = round_trip(
            &json!({"expected":{"op":"FreeVariable","name":"m::x"},"actual":{"op":"FreeVariable","name":"x","source_span":{"line":1}}}),
        );
        assert_eq!(r["status"], "ROUND_TRIP_VERIFIED");
    }
}
