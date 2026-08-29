//! Native owner for legacy expression normalization and transformation selection.

use std::cmp::Ordering;

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::{FormulaTracerError, Result};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

fn sorted(value: &Value) -> Value {
    match value {
        Value::Array(values) => Value::Array(values.iter().map(sorted).collect()),
        Value::Object(values) => {
            let mut keys = values.keys().collect::<Vec<_>>();
            keys.sort();
            Value::Object(
                keys.into_iter()
                    .map(|key| (key.clone(), sorted(&values[key])))
                    .collect(),
            )
        }
        _ => value.clone(),
    }
}

fn stable_id(kind: &str, value: &Value) -> Result<String> {
    let encoded = serde_json::to_string(&sorted(value))?;
    let digest = format!("{:x}", Sha256::digest(encoded.as_bytes()));
    Ok(format!("{kind}-{}", &digest[..16]))
}

fn constant(value: Value) -> Value {
    json!({"op":"Constant","value":value})
}

fn rename_bound(value: &Value, old: &str, new: &str) -> Value {
    match value {
        Value::Array(values) => Value::Array(
            values
                .iter()
                .map(|value| rename_bound(value, old, new))
                .collect(),
        ),
        Value::Object(values) => {
            let mut result: Map<String, Value> = values
                .iter()
                .map(|(key, value)| (key.clone(), rename_bound(value, old, new)))
                .collect();
            if result.get("op").and_then(Value::as_str) == Some("BoundVariable")
                && result.get("name").and_then(Value::as_str) == Some(old)
            {
                result.insert("name".into(), json!(new));
            }
            Value::Object(result)
        }
        _ => value.clone(),
    }
}

fn provenance_field(key: &str) -> bool {
    matches!(
        key,
        "original_index"
            | "source_node_ids"
            | "source_spans"
            | "source_span"
            | "operator_span"
            | "callable_span"
            | "argument_spans"
            | "keyword_spans"
            | "condition_span"
    )
}

fn normalize_node(value: &Value, trace: &mut Vec<Value>, depth: usize) -> Value {
    let Value::Object(values) = value else {
        return match value {
            Value::Array(values) => Value::Array(
                values
                    .iter()
                    .map(|value| normalize_node(value, trace, depth))
                    .collect(),
            ),
            _ => value.clone(),
        };
    };
    let mut current: Map<String, Value> = values
        .iter()
        .filter(|(key, _)| !provenance_field(key))
        .map(|(key, value)| (key.clone(), normalize_node(value, trace, depth)))
        .collect();
    let op = current
        .get("op")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    if matches!(
        op.as_str(),
        "FiniteSum" | "TransformReduce" | "FoldLeft" | "Map" | "Scan"
    ) {
        if let Some(old) = current
            .get("bound_index")
            .and_then(Value::as_str)
            .map(str::to_owned)
        {
            let new = format!("_i{depth}");
            if old != new {
                current = rename_bound(&Value::Object(current), &old, &new)
                    .as_object()
                    .cloned()
                    .unwrap_or_default();
                current.insert("bound_index".into(), json!(new));
                trace.push(json!({"rule_id":"alpha_rename","before":old,"after":new}));
            }
        }
    }
    if op == "TransformReduce"
        && current.get("reduction").and_then(Value::as_str) == Some("Add")
        && current.get("reduction_order").and_then(Value::as_str) == Some("left_to_right")
    {
        let finite = json!({
            "op":"FiniteSum",
            "bound_index":current.get("bound_index").cloned().unwrap_or(Value::Null),
            "index_domain":current.get("index_domain").cloned().unwrap_or(Value::Null),
            "body":current.get("transform").cloned().unwrap_or(Value::Null),
            "reduction_order":"left_to_right"
        });
        let initial = current.get("initial_value").cloned().unwrap_or(Value::Null);
        current = if initial == constant(json!(0)) || initial == constant(json!(0.0)) {
            finite.as_object().cloned().unwrap_or_default()
        } else {
            json!({"op":"Add","args":[initial,finite]})
                .as_object()
                .cloned()
                .unwrap_or_default()
        };
        trace.push(json!({"rule_id":"finite_sum_normalization","kind":"exact"}));
    }
    if matches!(
        current.get("op").and_then(Value::as_str),
        Some("Add" | "Multiply")
    ) {
        let identity = if current.get("op").and_then(Value::as_str) == Some("Add") {
            0
        } else {
            1
        };
        if let Some(args) = current.get("args").and_then(Value::as_array) {
            let filtered = args
                .iter()
                .filter(|arg| {
                    **arg != constant(json!(identity)) && **arg != constant(json!(identity as f64))
                })
                .cloned()
                .collect::<Vec<_>>();
            if filtered.len() != args.len() {
                trace.push(json!({"rule_id":"neutral_element_elimination","kind":"exact"}));
            }
            if filtered.len() == 1 {
                return filtered[0].clone();
            }
            current.insert("args".into(), Value::Array(filtered));
        }
    }
    Value::Object(current)
}

fn normalize_exact(expression: &Value) -> Result<Value> {
    let outputs = expression
        .get("outputs")
        .ok_or_else(|| invalid("EXPRESSION_OUTPUTS_REQUIRED"))?;
    let mut trace = Vec::new();
    let canonical = json!({"schema_version":"0.1","outputs":normalize_node(outputs,&mut trace,0)});
    Ok(json!({
        "status":if trace.is_empty(){"EXACT_CANONICAL_MATCH"}else{"EQUIVALENT_BY_EXACT_TRANSFORMATIONS"},
        "canonical_expression":canonical,
        "rewrite_trace":trace,
        "canonical_expression_id":stable_id("canonical-expression",&canonical)?
    }))
}

fn compare_exact(left: &Value, right: &Value) -> Result<Value> {
    let implementation = normalize_exact(left)?;
    let human = normalize_exact(right)?;
    let equal = implementation["canonical_expression"] == human["canonical_expression"];
    let changed = implementation["rewrite_trace"]
        .as_array()
        .is_some_and(|v| !v.is_empty())
        || human["rewrite_trace"]
            .as_array()
            .is_some_and(|v| !v.is_empty());
    Ok(json!({
        "status":if equal {if changed {"EQUIVALENT_BY_EXACT_TRANSFORMATIONS"} else {"EXACT_CANONICAL_MATCH"}} else {"NO_ALLOWED_APPROXIMATION_FOUND"},
        "match":equal,"implementation":implementation,"human":human
    }))
}

fn number(value: Option<&Value>) -> f64 {
    value.and_then(Value::as_f64).unwrap_or(f64::INFINITY)
}

fn rank(candidate: &Value, profile: &str) -> Vec<f64> {
    let cost = candidate.get("cost").unwrap_or(&Value::Null);
    let arithmetic = number(cost.get("symbolic_arithmetic_operations"));
    let memory = number(cost.get("asymptotic_memory_rank"));
    let path = cost
        .get("transformation_path_length")
        .and_then(Value::as_f64)
        .unwrap_or(1.0);
    let error = number(candidate.get("selection_error_estimate"));
    match profile {
        "minimum_error" => vec![error, arithmetic, memory, path],
        "locality" => vec![
            number(cost.get("memory_reads")),
            number(cost.get("memory_writes")),
            arithmetic,
            error,
        ],
        "frequency_fidelity" => vec![
            number(cost.get("frequency_phase_error")),
            arithmetic,
            memory,
            error,
        ],
        _ => vec![arithmetic, memory, path, error],
    }
}

fn compare_rank(left: &[f64], right: &[f64]) -> Ordering {
    for (left, right) in left.iter().zip(right) {
        let order = left.partial_cmp(right).unwrap_or(Ordering::Equal);
        if order != Ordering::Equal {
            return order;
        }
    }
    Ordering::Equal
}

fn select_transformation(request: &Value) -> Result<Value> {
    let set = request
        .get("transformation_set")
        .and_then(Value::as_object)
        .ok_or_else(|| invalid("TRANSFORMATION_SET_REQUIRED"))?;
    let rules = request
        .get("rules")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid("TRANSFORMATION_RULES_REQUIRED"))?;
    let profile = request
        .get("selection_profile")
        .and_then(Value::as_str)
        .unwrap_or("minimum_cost");
    if !matches!(
        profile,
        "minimum_cost" | "minimum_error" | "frequency_fidelity" | "stability" | "locality"
    ) {
        return Err(invalid(format!("unknown selection profile: {profile}")));
    }
    let strings = |value: Option<&Value>| -> Vec<String> {
        value
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect()
    };
    let allowed = strings(set.get("approximation_rules"));
    let forbidden = strings(set.get("forbidden_rules"));
    let mut required = strings(request.get("required_observables"));
    required.extend(strings(set.get("required_observables")));
    match profile {
        "frequency_fidelity" => required.push("frequency_response".into()),
        "stability" => required.push("stability_characterization".into()),
        _ => {}
    }
    required.sort();
    required.dedup();
    let maximum_error = set
        .get("hard_constraints")
        .and_then(|v| v.get("maximum_error"))
        .and_then(Value::as_f64);
    let mut candidates = Vec::new();
    for rule in rules {
        let rule_id = rule
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| invalid("TRANSFORMATION_RULE_ID_REQUIRED"))?;
        let observables = strings(rule.get("supported_observables"));
        let mut reasons = Vec::new();
        if !allowed.iter().any(|v| v == rule_id) {
            reasons.push(json!("APPROXIMATION_METHOD_NOT_ALLOWED"));
        }
        if forbidden.iter().any(|v| v == rule_id) {
            reasons.push(json!("FORBIDDEN_RULE"));
        }
        let missing = required
            .iter()
            .filter(|item| !observables.contains(item))
            .cloned()
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            reasons.push(json!(format!(
                "REQUIRED_OBSERVABLE_UNAVAILABLE: {}",
                missing.join(", ")
            )));
        }
        let error = rule
            .get("selection_error_estimate")
            .cloned()
            .unwrap_or(Value::Null);
        if maximum_error
            .zip(error.as_f64())
            .is_some_and(|(limit, error)| error > limit)
        {
            reasons.push(json!("APPROXIMATION_BOUND_EXCEEDED"));
        }
        candidates.push(
            json!({"rule_id":rule_id,"feasible":reasons.is_empty(),"rejection_reasons":reasons,
            "observables":observables,"cost":rule.get("cost").cloned().unwrap_or_else(||json!({})),
            "selection_error_estimate":error}),
        );
    }
    let mut feasible = candidates
        .iter()
        .filter(|item| item["feasible"] == json!(true))
        .cloned()
        .collect::<Vec<_>>();
    if feasible.is_empty() {
        return Ok(
            json!({"status":"NO_FEASIBLE_TRANSFORMATION","selected":null,"candidates":candidates}),
        );
    }
    feasible.sort_by(|left, right| {
        compare_rank(&rank(left, profile), &rank(right, profile))
            .then_with(|| left["rule_id"].as_str().cmp(&right["rule_id"].as_str()))
    });
    let best_rank = rank(&feasible[0], profile);
    if feasible
        .iter()
        .filter(|item| compare_rank(&rank(item, profile), &best_rank) == Ordering::Equal)
        .count()
        > 1
    {
        return Ok(
            json!({"status":"SELECTION_TIE_REQUIRES_USER","selected":null,"candidates":candidates}),
        );
    }
    Ok(
        json!({"status":"ALLOWED_APPROXIMATION_MATCH","selected":feasible[0],
        "selection_reason":format!("lexicographic selection profile: {profile}"),"candidates":candidates}),
    )
}

pub fn legacy_expression_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "NORMALIZE_EXACT" => normalize_exact(
            request
                .get("expression")
                .ok_or_else(|| invalid("EXPRESSION_REQUIRED"))?,
        ),
        "COMPARE_EXACT" => compare_exact(
            request
                .get("left")
                .ok_or_else(|| invalid("LEFT_EXPRESSION_REQUIRED"))?,
            request
                .get("right")
                .ok_or_else(|| invalid("RIGHT_EXPRESSION_REQUIRED"))?,
        ),
        "SELECT_TRANSFORMATION" => select_transformation(request),
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_EXPRESSION_ACTION:{action}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_non_matching_expression() {
        let left = json!({"outputs":[{"expression":{"op":"Constant","value":1}}]});
        let right = json!({"outputs":[{"expression":{"op":"Constant","value":2}}]});
        assert_eq!(
            compare_exact(&left, &right).unwrap()["status"],
            "NO_ALLOWED_APPROXIMATION_FOUND"
        );
    }
}
