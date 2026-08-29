//! Approximation-family selection semantics over versioned registry data.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

pub fn approximation_family_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "METADATA" => {
            let family = request
                .pointer("/rule/approximation_family_id")
                .and_then(Value::as_str);
            let Some(family) = family else {
                return Ok(json!({"value":null}));
            };
            let value = request
                .pointer(&format!("/families/{family}"))
                .ok_or_else(|| invalid(format!("APPROXIMATION_FAMILY_NOT_FOUND: {family}")))?;
            Ok(json!({"value":value}))
        }
        "CLASSIFY_LIBRARY_CALL" => {
            let callable = request
                .get("qualified_callable")
                .and_then(Value::as_str)
                .unwrap_or("");
            let Some(mapping) = request.get("mapping").filter(|value| !value.is_null()) else {
                return Ok(
                    json!({"status":"NO_APPROXIMATION_FAMILY_MAPPING","qualified_callable":callable}),
                );
            };
            let mut exact = mapping
                .get("exact_semantic_operator")
                .cloned()
                .unwrap_or(Value::Null);
            let mut status = json!("EXACT_DISCRETE_SEMANTICS_RECORDED");
            let mut families = mapping
                .get("approximation_family_ids")
                .cloned()
                .unwrap_or_else(|| json!([]));
            if exact.as_str() == Some("Interpolation") {
                match request.get("domain_status").and_then(Value::as_str) {
                    Some("EXTRAPOLATION") => {
                        exact = json!("Extrapolation");
                        status = json!("EXTRAPOLATION_RECOGNIZED");
                        families = json!([]);
                    }
                    None => status = json!("INTERPOLATION_DOMAIN_UNRESOLVED"),
                    Some(_) => status = json!("INTERPOLATION_RECOGNIZED"),
                }
            }
            Ok(json!({
                "status":status,"qualified_callable":callable,"exact_semantic_operator":exact,
                "approximation_family_ids":families,"derivative_is_exact_semantics":false,
                "public_reference_semantics":mapping.get("public_reference_semantics").cloned().unwrap_or_else(||json!({})),
                "provenance":mapping.get("provenance").cloned().unwrap_or_else(||json!({}))
            }))
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_APPROXIMATION_FAMILY_ACTION:{action}"
        ))),
    }
}

fn string_set(value: Option<&Value>) -> std::collections::BTreeSet<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn discharge_assumption(assumption: &Value, context: &Value) -> Value {
    let mut item = assumption.clone();
    let id = assumption
        .get("assumption_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    let kind = assumption.get("kind").and_then(Value::as_str).unwrap_or("");
    let provided = string_set(context.get("provided_assumptions"));
    let contracts = string_set(context.get("reference_contract_assumptions"));
    let (status, evidence) = if id == "positive_step"
        && context
            .get("h")
            .and_then(Value::as_f64)
            .is_some_and(|h| h > 0.0)
    {
        (
            "ASSUMPTION_PROVEN",
            json!({"kind":"NUMERIC_POSITIVITY","value":context.get("h")}),
        )
    } else if id == "nonnegative_step"
        && context
            .get("h")
            .and_then(Value::as_f64)
            .is_some_and(|h| h >= 0.0)
    {
        (
            "ASSUMPTION_PROVEN",
            json!({"kind":"NUMERIC_NONNEGATIVITY","value":context.get("h")}),
        )
    } else if kind == "DOMAIN_CONDITION"
        && context
            .get("domain_condition_proven")
            .and_then(Value::as_bool)
            == Some(true)
    {
        ("ASSUMPTION_PROVEN", json!({"kind":"STATIC_DOMAIN_CHECK"}))
    } else if kind == "PARTITION_CONDITION"
        && context.get("partition_resolved").and_then(Value::as_bool) == Some(true)
    {
        (
            "ASSUMPTION_PROVEN",
            json!({"kind":"PHASE6_HARD_CONSTRAINT","partition":context.get("partition")}),
        )
    } else if provided.contains(id) {
        (
            "ASSUMPTION_PROVIDED",
            json!({"kind":"USER_PROVIDED_ASSUMPTION"}),
        )
    } else if contracts.contains(id) {
        (
            "ASSUMPTION_REFERENCE_CONTRACT",
            json!({"kind":"PUBLIC_REFERENCE_CONTRACT"}),
        )
    } else {
        ("ASSUMPTION_UNRESOLVED", Value::Null)
    };
    item["discharge_status"] = json!(status);
    item["evidence"] = evidence;
    item
}

pub fn approximation_proof_operation(request: &Value) -> Result<Value> {
    if request.get("action").and_then(Value::as_str) != Some("RESOLVE") {
        return Err(invalid("UNSUPPORTED_APPROXIMATION_PROOF_ACTION"));
    }
    let family_id = request
        .get("family_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    let raw = request
        .get("proof")
        .ok_or_else(|| invalid(format!("APPROXIMATION_PROOF_NOT_FOUND: {family_id}")))?;
    let family = request
        .get("family")
        .ok_or_else(|| invalid(format!("APPROXIMATION_PROOF_NOT_FOUND: {family_id}")))?;
    let context = request.get("context").unwrap_or(&Value::Null);
    let kernel_checked = request
        .get("kernel_checked")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if family.get("approximation_kind").and_then(Value::as_str) == Some("interpolation")
        && context
            .get("interpolation_domain_status")
            .and_then(Value::as_str)
            == Some("EXTRAPOLATION")
    {
        return Err(invalid(format!(
            "INTERPOLATION_PROOF_APPLIED_TO_EXTRAPOLATION: {family_id}"
        )));
    }
    let formal_order = raw.get("convergence_order").cloned().unwrap_or(Value::Null);
    let registry_status = raw
        .get("proof_status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let cross_check = if registry_status == "REFERENCE_THEOREM_ONLY" {
        "REFERENCE_CONVERGENCE_METADATA"
    } else if formal_order
        == family
            .get("convergence_order")
            .cloned()
            .unwrap_or(Value::Null)
    {
        "REFERENCE_ORDER_CONFIRMED_BY_FORMAL_PROOF"
    } else {
        return Err(invalid(format!(
            "REFERENCE_FORMAL_ORDER_MISMATCH: {family_id}"
        )));
    };
    let assumptions: Vec<Value> = raw
        .get("assumptions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .map(|item| discharge_assumption(item, context))
        .collect();
    let unresolved: Vec<&Value> = assumptions
        .iter()
        .filter(|item| {
            item.get("discharge_status").and_then(Value::as_str) == Some("ASSUMPTION_UNRESOLVED")
        })
        .collect();
    if registry_status.starts_with("KERNEL_VERIFIED")
        && raw.get("lean_theorem_name").is_none_or(Value::is_null)
    {
        return Err(invalid(format!(
            "KERNEL_PROOF_WITHOUT_THEOREM: {family_id}"
        )));
    }
    let conditional = assumptions.iter().any(|item| {
        item.get("discharge_status").and_then(Value::as_str) != Some("ASSUMPTION_PROVEN")
    });
    let mut proof_status = if kernel_checked || registry_status == "REFERENCE_THEOREM_ONLY" {
        registry_status
    } else {
        "REFERENCE_THEOREM_ONLY"
    };
    if kernel_checked
        && registry_status == "KERNEL_VERIFIED_ERROR_BOUND_UNDER_ASSUMPTIONS"
        && !conditional
    {
        proof_status = "KERNEL_VERIFIED_ERROR_BOUND";
    }
    let obligations: Vec<Value> = unresolved
        .into_iter()
        .map(|item| {
            let kind = item.get("kind").and_then(Value::as_str).unwrap_or("");
            let status = if matches!(
                kind,
                "SMOOTHNESS_BOUND"
                    | "TAYLOR_REMAINDER"
                    | "LOCAL_QUADRATURE_BOUND"
                    | "INTERPOLATION_REMAINDER"
            ) {
                "SMOOTHNESS_BOUND_UNRESOLVED"
            } else if kind == "DOMAIN_CONDITION" {
                "DOMAIN_CONDITION_UNRESOLVED"
            } else {
                "PROOF_OBLIGATION_REMAINING"
            };
            json!({"assumption_id":item.get("assumption_id"),"kind":kind,"status":status})
        })
        .collect();
    let raw_convergence = raw
        .get("convergence_status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let convergence_status = if !kernel_checked && raw_convergence.starts_with("KERNEL_VERIFIED") {
        "CONVERGENCE_NOT_PROVEN"
    } else if kernel_checked
        && raw_convergence == "KERNEL_VERIFIED_CONVERGENCE_UNDER_ASSUMPTIONS"
        && !conditional
    {
        "KERNEL_VERIFIED_CONVERGENCE"
    } else {
        raw_convergence
    };
    Ok(json!({
        "family_id":family_id,"theorem_id":raw.get("theorem_id"),"target_operator":raw.get("target_operator"),
        "approximation_expression":raw.get("approximation_expression"),"domain":raw.get("domain"),"parameters":raw.get("parameters"),
        "assumptions":assumptions,"error_bound":{"error_expression":raw.get("error_expression"),"bound":raw.get("error_bound"),
            "bound_constant":raw.get("bound_constant"),"exponent":raw.pointer("/parameters/exponent"),"error_kind":"APPROXIMATION_ERROR"},
        "convergence":{"order":formal_order,"parameter":family.get("convergence_parameter"),"target":family.get("convergence_target"),
            "status":convergence_status,"lean_theorem_name":raw.get("lean_convergence_theorem")},
        "proof_status":proof_status,"order_cross_check":cross_check,"evidence":{"lean_theorem_name":raw.get("lean_theorem_name"),
            "lean_source_hash":request.get("source_hash"),"kernel_checked":kernel_checked,"provenance":raw.get("provenance")},
        "remaining_obligations":obligations
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn interpolation_domain_is_fail_closed() {
        let mapping = json!({"exact_semantic_operator":"Interpolation","approximation_family_ids":["linear"]});
        let unresolved = approximation_family_operation(&json!({"action":"CLASSIFY_LIBRARY_CALL","qualified_callable":"x.interp","mapping":mapping})).unwrap();
        assert_eq!(unresolved["status"], "INTERPOLATION_DOMAIN_UNRESOLVED");
        let extrapolated = approximation_family_operation(&json!({"action":"CLASSIFY_LIBRARY_CALL","qualified_callable":"x.interp","mapping":mapping,"domain_status":"EXTRAPOLATION"})).unwrap();
        assert_eq!(extrapolated["exact_semantic_operator"], "Extrapolation");
        assert_eq!(extrapolated["approximation_family_ids"], json!([]));
    }
}
