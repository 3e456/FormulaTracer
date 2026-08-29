//! Provider-independent reconstruction blockers.
//!
//! These decisions live in the native core so frontends only describe facts.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::{semantic_equal, substitute, FormulaTracerError, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum CoverageLevel {
    FullReconstruction,
    PartialReconstruction,
    StructuralOnly,
    Unresolved,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum OpaqueKind {
    ValueTransform,
    ShapeTransform,
    Control,
    Effect,
    External,
}

fn required<'a>(request: &'a Value, key: &str) -> Result<&'a Value> {
    request.get(key).ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument(format!("coverage request missing {key}"))
    })
}

fn full(value: Value, evidence: &str) -> Value {
    json!({
        "status": CoverageLevel::FullReconstruction,
        "semantic_object": value,
        "evidence": [{"kind":"FORMALLY_DERIVED","source":evidence}],
        "unresolved": []
    })
}

fn unresolved(code: &str, missing: &[&str]) -> Value {
    json!({
        "status": CoverageLevel::Unresolved,
        "semantic_object": null,
        "evidence": [],
        "unresolved": [{"code":code,"missing":missing}]
    })
}

fn compose_call(request: &Value) -> Result<Value> {
    if request.get("recursive").and_then(Value::as_bool) == Some(true) {
        return Ok(unresolved(
            "RECURSIVE_CALL_UNRESOLVED",
            &["termination proof"],
        ));
    }
    if request.get("effects_known_pure").and_then(Value::as_bool) != Some(true) {
        return Ok(unresolved(
            "CALL_EFFECTS_UNRESOLVED",
            &["callee purity/effect summary"],
        ));
    }
    let mapping: BTreeMap<String, Value> =
        serde_json::from_value(required(request, "arguments")?.clone())?;
    let expression = substitute(required(request, "callee_ir")?, &mapping);
    Ok(full(
        json!({"op":"ComposedCall","expression":expression,"arguments":mapping}),
        "native-interprocedural-substitution",
    ))
}

fn loop_fold(request: &Value) -> Result<Value> {
    let update = required(request, "update_op")?.as_str().unwrap_or("");
    let initializer = required(request, "initializer")?;
    let identity_ok = (update == "ADD" && initializer == &json!(0))
        || (update == "MULTIPLY" && initializer == &json!(1));
    let safe = request.get("bounded").and_then(Value::as_bool) == Some(true)
        && request.get("effects_known_pure").and_then(Value::as_bool) == Some(true)
        && request.get("has_break").and_then(Value::as_bool) != Some(true);
    if !identity_ok || !safe {
        return Ok(unresolved(
            "LOOP_FOLD_UNRESOLVED",
            &[
                "identity",
                "bounded iteration",
                "effect freedom",
                "break semantics",
            ],
        ));
    }
    let mut body = required(request, "body")?.clone();
    if let Some(condition) = request.get("path_condition") {
        body = json!({"op":"Multiply","args":[
            {"op":"Indicator","predicate":condition}, body
        ]});
    }
    Ok(full(
        json!({
            "op": if update == "ADD" { "FiniteSum" } else { "FiniteProduct" },
            "bound_index": required(request,"index")?,
            "index_domain": required(request,"domain")?,
            "body": body,
            "lowered_from":"LoopFold"
        }),
        "native-loop-fold",
    ))
}

fn container_access(request: &Value) -> Result<Value> {
    if request.get("effects_known_pure").and_then(Value::as_bool) != Some(true) {
        return Ok(unresolved("CONTAINER_ACCESS_UNRESOLVED", &["pure lookup"]));
    }
    if request.get("key_is_static").and_then(Value::as_bool) != Some(true) {
        let keys = request.get("possible_keys").and_then(Value::as_array);
        let values = request.get("possible_values").and_then(Value::as_object);
        let exhaustive = request
            .get("candidate_set_exhaustive_proven")
            .and_then(Value::as_bool)
            == Some(true);
        let (Some(keys), Some(values)) = (keys, values) else {
            return Ok(unresolved(
                "CONTAINER_ACCESS_UNRESOLVED",
                &["static key or finite candidate set", "value alternatives"],
            ));
        };
        if keys.is_empty()
            || !keys
                .iter()
                .all(|key| key.as_str().is_some_and(|k| values.contains_key(k)))
        {
            return Ok(unresolved(
                "CONTAINER_CANDIDATES_INVALID",
                &["non-empty keys", "value for every key"],
            ));
        }
        let key_expression = required(request, "key")?;
        let cases: Vec<Value> = keys
            .iter()
            .map(|key| {
                let text = key.as_str().expect("validated string key");
                json!({
                    "condition":{"op":"Equal","args":[key_expression,{"op":"Constant","value":text}]},
                    "value":values.get(text).expect("validated value")
                })
            })
            .collect();
        return Ok(json!({
            "status": if exhaustive { CoverageLevel::FullReconstruction } else { CoverageLevel::PartialReconstruction },
            "semantic_object":{"op":"Piecewise","cases":cases},
            "evidence":[{"kind": if exhaustive { "FORMALLY_DERIVED" } else { "USER_DECLARED" },
                         "source":"finite-container-key-analysis","verified":exhaustive}],
            "unresolved": if exhaustive { vec![] } else {
                vec![json!({"code":"FINITE_KEY_SET_EXHAUSTIVENESS_UNPROVEN"})]
            }
        }));
    }
    Ok(full(
        json!({
            "op":"TransparentContainerAccess",
            "container_kind":required(request,"container_kind")?,
            "container":required(request,"container")?,
            "key":required(request,"key")?,
            "value":required(request,"value")?
        }),
        "native-transparent-container-access",
    ))
}

fn tensor_index(request: &Value) -> Result<Value> {
    let shape = required(request, "shape")?.as_array().ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument("shape must be an array".into())
    })?;
    let indices = required(request, "indices")?.as_array().ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument("indices must be an array".into())
    })?;
    if indices.len() > shape.len() || shape.iter().any(Value::is_null) {
        return Ok(unresolved(
            "TENSOR_INDEX_UNRESOLVED",
            &["known rank/shape", "valid index arity"],
        ));
    }
    Ok(full(
        json!({
            "op":"TensorIndex",
            "value":required(request,"value")?,
            "shape":shape,
            "indices":indices,
            "broadcast":request.get("broadcast").cloned().unwrap_or(json!([]))
        }),
        "native-tensor-index-algebra",
    ))
}

fn higher_order(request: &Value) -> Result<Value> {
    let Some(callback) = request.get("callback_ir").filter(|v| !v.is_null()) else {
        return Ok(unresolved(
            "CALLBACK_RECONSTRUCTION_UNRESOLVED",
            &["callback Mathematical IR"],
        ));
    };
    let effects_proven = request
        .get("callback_effects_known_pure")
        .and_then(Value::as_bool)
        == Some(true);
    let evidence_kind = request
        .get("callback_evidence_kind")
        .and_then(Value::as_str)
        .unwrap_or("IMPLEMENTATION_DERIVED");
    if !effects_proven && evidence_kind != "USER_DECLARED" {
        return Ok(unresolved(
            "CALLBACK_EFFECTS_UNRESOLVED",
            &["callback purity/effect summary"],
        ));
    }
    let semantic_object = json!({
        "op":"HigherOrderCall",
        "algorithm":required(request,"algorithm")?,
        "callback":callback,
        "parameters":request.get("parameters").cloned().unwrap_or(json!({})),
        "effects":request.get("callback_effects").cloned().unwrap_or(json!("UNKNOWN_EFFECT"))
    });
    if evidence_kind == "USER_DECLARED" {
        return Ok(json!({
            "status":CoverageLevel::PartialReconstruction,
            "semantic_object":semantic_object,
            "evidence":[{"kind":"USER_DECLARED","verified":false}],
            "unresolved": if effects_proven { vec![] } else {
                vec![json!({"code":"USER_DECLARED_EFFECTS_UNVERIFIED"})]
            }
        }));
    }
    Ok(full(semantic_object, "native-higher-order-reconstruction"))
}

fn finite_dispatch(request: &Value) -> Result<Value> {
    let targets = required(request, "targets")?.as_array().ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument("targets must be an array".into())
    })?;
    let exhaustive = request
        .get("candidate_set_exhaustive_proven")
        .and_then(Value::as_bool)
        == Some(true);
    if targets.is_empty()
        || targets.iter().any(|target| {
            target.get("condition").is_none()
                || target.get("callee_ir").is_none()
                || target.get("effects_known_pure").and_then(Value::as_bool) != Some(true)
        })
    {
        return Ok(unresolved(
            "DYNAMIC_DISPATCH_UNRESOLVED",
            &[
                "non-empty targets",
                "target conditions",
                "callee IR",
                "pure effects",
            ],
        ));
    }
    let cases: Vec<Value> = targets
        .iter()
        .map(|target| json!({"condition":target["condition"],"value":target["callee_ir"]}))
        .collect();
    Ok(json!({
        "status":if exhaustive { CoverageLevel::FullReconstruction } else { CoverageLevel::PartialReconstruction },
        "semantic_object":{"op":"PiecewiseDispatch","receiver":request.get("receiver"),"cases":cases},
        "evidence":[{"kind":"FORMALLY_DERIVED","source":"finite-dispatch-analysis","verified":exhaustive}],
        "unresolved":if exhaustive { vec![] } else { vec![json!({"code":"DISPATCH_EXHAUSTIVENESS_UNPROVEN"})] }
    }))
}

fn user_declaration(request: &Value) -> Result<Value> {
    let declared = required(request, "declared_ir")?;
    let implementation = request
        .get("implementation_ir")
        .filter(|value| !value.is_null());
    let comparison = implementation.map_or("NOT_EVALUABLE", |actual| {
        if semantic_equal(declared, actual) {
            "MATCH"
        } else {
            "MISMATCH"
        }
    });
    Ok(json!({
        "status":comparison,
        "declared_semantics":declared,
        "implementation_semantics":implementation,
        "metadata":request.get("metadata").cloned().unwrap_or(json!({})),
        "evidence":[{"kind":"USER_DECLARED","verified":false,"proves_implementation":false}],
        "verification_status":"UNRESOLVED",
        "auto_verified":false
    }))
}

fn classify_opaque(request: &Value) -> Result<Value> {
    let kind: OpaqueKind = serde_json::from_value(required(request, "opaque_kind")?.clone())?;
    let value_semantics_preserved = matches!(kind, OpaqueKind::ShapeTransform)
        && request
            .get("value_preserving_proven")
            .and_then(Value::as_bool)
            == Some(true);
    Ok(json!({
        "status": if value_semantics_preserved {
            CoverageLevel::FullReconstruction
        } else {
            CoverageLevel::PartialReconstruction
        },
        "opaque_kind":kind,
        "value_semantics_preserved":value_semantics_preserved,
        "semantic_object": if value_semantics_preserved {
            json!({"op":"ValueIdentity","shape_transform":required(request,"call")?})
        } else { Value::Null },
        "unresolved": if value_semantics_preserved { vec![] } else {
            vec![json!({"code":"OPAQUE_SEMANTICS_REMAIN","kind":kind})]
        }
    }))
}

pub(crate) fn coverage_blocker_operation(request: &Value) -> Result<Value> {
    match required(request, "action")?.as_str().unwrap_or("") {
        "COMPOSE_CALL" => compose_call(request),
        "LOOP_TO_FOLD" => loop_fold(request),
        "CONTAINER_ACCESS" => container_access(request),
        "TENSOR_INDEX" => tensor_index(request),
        "HIGHER_ORDER_CALL" => higher_order(request),
        "FINITE_DISPATCH" => finite_dispatch(request),
        "USER_DECLARATION" => user_declaration(request),
        "CLASSIFY_OPAQUE" => classify_opaque(request),
        _ => Err(FormulaTracerError::InvalidSemanticDocument(
            "unknown coverage-blocker action".into(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn call_composition_and_dynamic_container_are_fail_closed() {
        let composed = coverage_blocker_operation(&json!({
            "action":"COMPOSE_CALL", "effects_known_pure":true, "recursive":false,
            "callee_ir":{"op":"Add","args":[{"op":"FreeVariable","name":"x"},1]},
            "arguments":{"x":{"op":"FreeVariable","name":"input"}}
        }))
        .unwrap();
        assert_eq!(composed["status"], "FULL_RECONSTRUCTION");
        let unresolved = coverage_blocker_operation(&json!({
            "action":"CONTAINER_ACCESS", "key_is_static":false, "effects_known_pure":true,
            "container_kind":"DICT", "container":"p", "key":"dynamic", "value":1
        }))
        .unwrap();
        assert_eq!(unresolved["status"], "UNRESOLVED");
    }

    #[test]
    fn conditional_loop_lowers_to_indicator_sum() {
        let result = coverage_blocker_operation(&json!({
            "action":"LOOP_TO_FOLD", "update_op":"ADD", "initializer":0,
            "bounded":true, "effects_known_pure":true, "has_break":false,
            "index":"i", "domain":{"start":0,"stop":"n"},
            "path_condition":{"op":"GreaterThan","args":["x_i",0]}, "body":"x_i"
        }))
        .unwrap();
        assert_eq!(result["semantic_object"]["op"], "FiniteSum");
        assert_eq!(
            result["semantic_object"]["body"]["args"][0]["op"],
            "Indicator"
        );
    }

    #[test]
    fn finite_keys_and_dispatch_require_exhaustiveness_evidence() {
        let keys = coverage_blocker_operation(&json!({
            "action":"CONTAINER_ACCESS", "key_is_static":false, "effects_known_pure":true,
            "container_kind":"DICT", "container":"p", "key":{"op":"FreeVariable","name":"k"},
            "possible_keys":["a","b"], "possible_values":{"a":1,"b":2},
            "candidate_set_exhaustive_proven":true
        }))
        .unwrap();
        assert_eq!(keys["status"], "FULL_RECONSTRUCTION");
        let dispatch = coverage_blocker_operation(&json!({
            "action":"FINITE_DISPATCH", "receiver":"x", "candidate_set_exhaustive_proven":false,
            "targets":[{"condition":true,"callee_ir":{"op":"FreeVariable","name":"f"},"effects_known_pure":true}]
        })).unwrap();
        assert_eq!(dispatch["status"], "PARTIAL_RECONSTRUCTION");
    }

    #[test]
    fn user_declaration_is_comparable_but_never_verification() {
        let matched = coverage_blocker_operation(&json!({
            "action":"USER_DECLARATION",
            "declared_ir":{"op":"Add","args":[{"op":"FreeVariable","name":"x"},1]},
            "implementation_ir":{"op":"Add","args":[1,{"op":"FreeVariable","name":"x"}]},
            "metadata":{"effects":"PURE"}
        }))
        .unwrap();
        assert_eq!(matched["status"], "MATCH");
        assert_eq!(matched["auto_verified"], false);
        let mismatch = coverage_blocker_operation(&json!({
            "action":"USER_DECLARATION", "declared_ir":{"op":"Constant","value":1},
            "implementation_ir":{"op":"Constant","value":2}
        }))
        .unwrap();
        assert_eq!(mismatch["status"], "MISMATCH");
        assert_eq!(mismatch["verification_status"], "UNRESOLVED");
    }
}
