//! Native assembly of project-level verification claims.
//!
//! Frontends supply observations.  This module alone decides layer status,
//! error completeness, assumptions, and the aggregate verification result.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use crate::{FormulaTracerError, Result};

const VERIFIED: &[&str] = &[
    "KERNEL_VERIFIED",
    "KERNEL_VERIFIED_UNDER_ASSUMPTIONS",
    "ENCLOSURE_VERIFIED",
    "ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS",
    "REFERENCE_CONTRACT_VERIFIED",
    "NOT_APPLICABLE",
];

fn finite(value: &Value) -> bool {
    value.as_f64().is_some_and(f64::is_finite)
}

fn walk_has_float_or_call(value: &Value) -> bool {
    match value {
        Value::Array(values) => values.iter().any(walk_has_float_or_call),
        Value::Object(object) => {
            object.get("op").and_then(Value::as_str) == Some("FunctionCall")
                || object.get("value").is_some_and(|v| v.is_f64())
                || object.values().any(walk_has_float_or_call)
        }
        _ => false,
    }
}

fn integer_exact(value: &Value) -> bool {
    let Some(object) = value.as_object() else {
        return value.is_i64() || value.is_u64();
    };
    match object.get("op").and_then(Value::as_str).unwrap_or("") {
        "Constant" => object
            .get("value")
            .is_some_and(|v| v.is_i64() || v.is_u64()),
        "FreeVariable" | "BoundVariable" | "IndexedValue" => true,
        "Add" | "Subtract" | "Multiply" | "Negate" => object
            .get("args")
            .and_then(Value::as_array)
            .is_some_and(|items| items.iter().all(integer_exact)),
        "Power" => object
            .get("args")
            .and_then(Value::as_array)
            .is_some_and(|items| {
                items.len() == 2
                    && integer_exact(&items[0])
                    && items[1]
                        .get("value")
                        .is_some_and(|v| v.is_i64() || v.is_u64())
            }),
        _ => false,
    }
}

fn component_id(component: &Value) -> String {
    for key in ["component_id", "semantic_cause_id", "origin_id"] {
        if let Some(value) = component.get(key).and_then(Value::as_str) {
            return value.to_string();
        }
    }
    let digest = Sha256::digest(serde_json::to_vec(component).unwrap_or_default());
    format!("component:{digest:x}")[..26].to_string()
}

fn component_verified(component: &Value) -> bool {
    let status = component
        .pointer("/bound/status")
        .and_then(Value::as_str)
        .unwrap_or("");
    let proof = component
        .get("proof_status")
        .and_then(Value::as_str)
        .unwrap_or("");
    matches!(
        status,
        "EXACT_ZERO_BOUND"
            | "KERNEL_VERIFIED_BOUND"
            | "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS"
            | "REFERENCE_CONTRACT_BOUND"
            | "INTERVAL_BOUND"
    ) && !matches!(proof, "UNRESOLVED" | "FAILED" | "REFERENCE_THEOREM_ONLY")
}

fn layer(
    layer: &str,
    status: &str,
    explanation: &str,
    critical: bool,
    assumptions: Vec<Value>,
    obligations: Vec<Value>,
) -> Value {
    json!({"layer":layer,"status":status,"explanation":explanation,"evidence_ids":[],
        "assumptions":assumptions,"obligations":obligations,"critical":critical})
}

fn origins_for_ffi(value: &Value, result: &mut Vec<Value>) {
    match value {
        Value::Array(values) => {
            for item in values {
                origins_for_ffi(item, result);
            }
        }
        Value::Object(object) => {
            if let Some(boundary) = object.get("language_boundary").filter(|v| v.is_object()) {
                result.push(boundary.clone());
            }
            for child in object.values() {
                origins_for_ffi(child, result);
            }
        }
        _ => {}
    }
}

fn artifact_records(project: &Value, output: &Value) -> Vec<Value> {
    let name = output.get("name").and_then(Value::as_str).unwrap_or("");
    project.get("artifacts").and_then(Value::as_array).into_iter().flatten().filter_map(|artifact| {
        let matches = artifact.get("payload_symbol").and_then(Value::as_str) == Some(name)
            || artifact.get("dataset_variable").and_then(Value::as_str) == Some(name)
            || artifact.get("dataset_outputs").and_then(Value::as_array).is_some_and(|values| values.iter()
                .any(|item| item.get("name").and_then(Value::as_str) == Some(name)));
        if !matches { return None; }
        let contract = artifact.get("library_contract").cloned().unwrap_or_else(|| json!({}));
        let contract_status = contract.get("proof_status").or_else(|| contract.get("status"))
            .and_then(Value::as_str).unwrap_or("");
        let preserving = contract.get("value_preserving").and_then(Value::as_bool).unwrap_or(false)
            && matches!(contract_status, "REFERENCE_CONTRACT_VERIFIED" | "KERNEL_VERIFIED" | "KERNEL_VERIFIED_UNDER_ASSUMPTIONS");
        let mut obligations = artifact.get("range_obligations").and_then(Value::as_array).cloned().unwrap_or_default();
        if artifact.get("serialization_cast").is_some_and(|v| !v.is_null()) {
            obligations.push(json!({"kind":"SERIALIZATION_ERROR","status":"UNRESOLVED",
                "detail":artifact.get("serialization_cast")}));
        }
        if !preserving { obligations.push(json!({"kind":"SERIALIZATION_VALUE_PRESERVATION_REQUIRED","status":"UNRESOLVED"})); }
        let path = artifact.get("path_expression").and_then(Value::as_str);
        let (materialization, hash) = path.and_then(|p| std::fs::read(p).ok()).map_or(
            ("ARTIFACT_NOT_MATERIALIZED", Value::Null), |bytes| {
                ("ARTIFACT_MATERIALIZED", Value::String(format!("{:x}", Sha256::digest(bytes))))
            });
        let certified = artifact.get("certified_payload_range").is_some_and(|v| !v.is_null());
        let status = if preserving && obligations.is_empty() && certified {
            "ARTIFACT_PAYLOAD_ENCLOSURE_VERIFIED"
        } else { "ARTIFACT_PAYLOAD_ENCLOSURE_UNRESOLVED" };
        Some(json!({"artifact_id":artifact.get("sink_id"),"path":path,"format":artifact.get("format"),
            "payload_symbol":artifact.get("payload_symbol"),"dataset_variable":artifact.get("dataset_variable"),
            "payload_value_enclosure":output.get("value_interval"),"payload_error_enclosure":output.get("error_interval"),
            "serialization_contract":contract,"stored_dtype":artifact.get("dtype"),
            "materialization_status":materialization,"artifact_hash":hash,"status":status,"obligations":obligations}))
    }).collect()
}

fn claim_id(output: &Value, proof_chain: &Value) -> String {
    let digest = Sha256::digest(
        serde_json::to_vec(&json!([
            output.get("output_id"),
            proof_chain.get("chain_id")
        ]))
        .unwrap_or_default(),
    );
    format!("e2e-claim:{digest:x}")[..26].to_string()
}

fn output_root(project: &Value, output_id: &Value) -> Value {
    for root in project
        .get("roots")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let contains = root
            .get("outputs")
            .and_then(Value::as_array)
            .is_some_and(|outputs| {
                outputs
                    .iter()
                    .any(|item| item.get("output_id") == Some(output_id))
            });
        if contains {
            return root.get("root_id").cloned().unwrap_or(Value::Null);
        }
    }
    json!("root:unresolved")
}

fn proof_chain(output: &Value, layers: &[Value], has_artifacts: bool) -> Value {
    let mut ordered = vec![
        "TheoryExpression",
        "ImplementationExpression",
        "ApproximationErrorBound",
        "NumericErrorComponents",
        "TotalErrorBound",
        "ValueInterval",
        "TrueValueEnclosure",
    ];
    if has_artifacts {
        ordered.extend(["SerializationBoundary", "ArtifactEnclosure"]);
    }
    let edge_layers = [
        "THEORY_IMPLEMENTATION",
        "APPROXIMATION",
        "NUMERIC_EXECUTION",
        "ERROR",
        "RANGE",
        "RANGE",
        "SERIALIZATION",
        "ARTIFACT",
    ];
    let layer_by_name: BTreeMap<&str, &Value> = layers
        .iter()
        .filter_map(|item| {
            item.get("layer")
                .and_then(Value::as_str)
                .map(|name| (name, item))
        })
        .collect();
    let nodes: Vec<Value> = ordered
        .iter()
        .map(|name| json!({"node_id":name,"kind":name}))
        .collect();
    let edges: Vec<Value> = ordered
        .windows(2)
        .enumerate()
        .map(|(index, pair)| {
            let selected = layer_by_name.get(edge_layers[index]).copied();
            let theorem = match (pair[0], pair[1]) {
                ("TheoryExpression", "ImplementationExpression") => {
                    Some("CppAudit.EndToEnd.exact_chain_transitive")
                }
                ("NumericErrorComponents", "TotalErrorBound") => Some(
                    "CppAudit.EndToEnd.verified_component_bounds_imply_total_bound",
                ),
                ("ValueInterval", "TrueValueEnclosure") => {
                    Some("CppAudit.EndToEnd.value_error_enclosure_sound")
                }
                _ => None,
            };
            let reference_contract = if pair[0] == "SerializationBoundary"
                && selected.and_then(|item| item.get("status")).and_then(Value::as_str)
                    == Some("REFERENCE_CONTRACT_VERIFIED")
            {
                Some("SERIALIZATION_VALUE_PRESERVING")
            } else {
                None
            };
            json!({
                "source": pair[0], "target": pair[1],
                "rule": format!("compose_{}_to_{}", pair[0], pair[1]),
                "status": selected.and_then(|item| item.get("status")).cloned().unwrap_or_else(||json!("UNRESOLVED")),
                "lean_theorem": theorem, "reference_contract": reference_contract,
                "assumptions": selected.and_then(|item| item.get("assumptions")).cloned().unwrap_or_else(||json!([]))
            })
        })
        .collect();
    let mut evidence: Vec<Value> = output
        .pointer("/interval_propagation/evidence")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .map(|item| {
            json!({
                "evidence_id":item.get("evidence_id"),
                "kind":item.get("kind").cloned().unwrap_or_else(||json!("INTERVAL")),
                "status":item.get("status").cloned().unwrap_or_else(||json!("UNRESOLVED")),
                "source_id":Value::Null,
                "lean_theorem":item.get("theorem_reference"),
                "reference_contract":Value::Null,
                "assumptions":item.get("assumptions").cloned().unwrap_or_else(||json!([])),
                "proof_authority":item.get("proof_authority").and_then(Value::as_bool).unwrap_or(false),
                "provenance":item
            })
        })
        .collect();
    if output.get("lean_status").and_then(Value::as_str) == Some("LEAN_KERNEL_VERIFIED") {
        evidence.push(json!({
            "evidence_id":format!("evidence:{}", output.get("output_id").and_then(Value::as_str).unwrap_or("unresolved")),
            "kind":"THEORY_IMPLEMENTATION_EQUIVALENCE", "status":"KERNEL_VERIFIED",
            "source_id":output.get("output_id"), "lean_theorem":Value::Null,
            "reference_contract":Value::Null, "assumptions":[], "proof_authority":true,
            "provenance":{}
        }));
    }
    let status = if layers
        .iter()
        .filter(|item| {
            item.get("critical")
                .and_then(Value::as_bool)
                .unwrap_or(false)
        })
        .all(|item| VERIFIED.contains(&item.get("status").and_then(Value::as_str).unwrap_or("")))
    {
        "PROOF_CHAIN_COMPLETE"
    } else {
        "PROOF_CHAIN_PARTIAL"
    };
    let digest = Sha256::digest(
        serde_json::to_vec(&json!([nodes.clone(), edges.clone()])).unwrap_or_default(),
    );
    json!({"nodes":nodes,"edges":edges,"evidence":evidence,"status":status,
        "chain_id":format!("e2e-chain:{digest:x}")[..26].to_string()})
}

fn output_claim(
    project: &Value,
    output: &Value,
    observed: Option<&Value>,
    specification: Option<&Value>,
    model_scope: Option<&Value>,
) -> Value {
    let exact_theory = output.get("lean_status").and_then(Value::as_str)
        == Some("LEAN_KERNEL_VERIFIED")
        && output.get("status").and_then(Value::as_str) == Some("FULLY_VERIFIED");
    let formula = output.get("formula").cloned().unwrap_or(Value::Null);
    let theory = output
        .pointer("/residual/theory_expression")
        .cloned()
        .or_else(|| output.get("theory").cloned())
        .unwrap_or(Value::Null);
    let components = output
        .get("error_components")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let approximation: Vec<Value> = components
        .iter()
        .filter(|item| {
            matches!(
                item.get("source").and_then(Value::as_str),
                Some("APPROXIMATION_ERROR" | "DISCRETIZATION_ERROR")
            )
        })
        .cloned()
        .collect();
    let approximation_ok =
        !approximation.is_empty() && approximation.iter().all(component_verified);
    let approximation_assumptions: Vec<Value> = approximation
        .iter()
        .flat_map(|item| {
            item.get("assumptions")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
        })
        .collect();
    let numeric = output
        .pointer("/implementation/numeric_execution")
        .or_else(|| output.pointer("/implementation/numeric_type_semantics"));
    let float_route = numeric
        .is_some_and(|v| v.get("dtype").is_some() || v.get("cpp_types").is_some())
        || walk_has_float_or_call(&formula);
    let integer_route = exact_theory && integer_exact(&formula) && !float_route;
    let rounding_complete = components
        .iter()
        .filter(|item| {
            matches!(
                item.get("source").and_then(Value::as_str),
                Some("ROUNDING_ERROR" | "PARALLEL_ORDER_ERROR")
            )
        })
        .all(component_verified)
        && components.iter().any(|item| {
            matches!(
                item.get("source").and_then(Value::as_str),
                Some("ROUNDING_ERROR" | "PARALLEL_ORDER_ERROR")
            )
        });
    let execution_obligations: Vec<Value> = output
        .get("range_obligations")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|item| {
            matches!(
                item.get("kind").and_then(Value::as_str),
                Some("OVERFLOW_POSSIBLE" | "SUBNORMAL_RANGE_POSSIBLE" | "CAST_RANGE_UNRESOLVED")
            )
        })
        .cloned()
        .collect();
    let execution_status = if integer_route {
        "KERNEL_VERIFIED"
    } else if output
        .pointer("/execution_range/status")
        .and_then(Value::as_str)
        == Some("EXECUTION_RANGE_FINITE")
        && execution_obligations.is_empty()
        && (!float_route || rounding_complete)
    {
        "ENCLOSURE_VERIFIED"
    } else {
        "UNRESOLVED"
    };
    let constraint = output
        .get("range_constraint_status")
        .and_then(Value::as_str);
    let range_status = if integer_route
        && output.get("range_status").and_then(Value::as_str)
            == Some("TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")
        && output
            .get("range_obligations")
            .and_then(Value::as_array)
            .is_none_or(Vec::is_empty)
        && matches!(constraint, None | Some("OUTPUT_RANGE_CONSTRAINT_PROVEN"))
    {
        "KERNEL_VERIFIED"
    } else if output.get("range_status").and_then(Value::as_str)
        == Some("TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")
        && output
            .get("range_obligations")
            .and_then(Value::as_array)
            .is_none_or(Vec::is_empty)
        && matches!(constraint, None | Some("OUTPUT_RANGE_CONSTRAINT_PROVEN"))
    {
        "ENCLOSURE_VERIFIED"
    } else if output.get("range_status").and_then(Value::as_str)
        == Some("TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")
    {
        "ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS"
    } else {
        "UNRESOLVED"
    };
    let mut boundaries = vec![];
    origins_for_ffi(&formula, &mut boundaries);
    let ffi_unresolved: Vec<Value> = boundaries
        .iter()
        .filter(|item| {
            !matches!(
                item.get("representation_mapping").and_then(Value::as_str),
                Some("RANGE_PRESERVING" | "REPRESENTATION_MAPPING_VERIFIED" | "EXACT_WIDENING")
            )
        })
        .cloned()
        .collect();
    let ffi_status = if boundaries.is_empty() {
        "NOT_APPLICABLE"
    } else if ffi_unresolved.is_empty() {
        "REFERENCE_CONTRACT_VERIFIED"
    } else {
        "UNRESOLVED"
    };
    let artifacts = artifact_records(project, output);
    let mut seen = BTreeSet::new();
    let mut unresolved = vec![];
    let mut duplicate = vec![];
    let mut unique = vec![];
    for component in &components {
        let cause = component
            .get("semantic_cause_id")
            .or_else(|| component.get("origin_id"))
            .and_then(Value::as_str)
            .map(str::to_string)
            .unwrap_or_else(|| component_id(component));
        if !seen.insert(cause) {
            duplicate.push(component_id(component));
        } else {
            unique.push(component);
        }
    }
    let known = [
        "APPROXIMATION_ERROR",
        "DISCRETIZATION_ERROR",
        "ROUNDING_ERROR",
        "CAST_ERROR",
        "OVERFLOW_ERROR",
        "UNDERFLOW_ERROR",
        "PARALLEL_ORDER_ERROR",
        "FFI_CONVERSION_ERROR",
        "SERIALIZATION_ERROR",
        "INPUT_UNCERTAINTY",
        "MODEL_ERROR",
        "LIBRARY_CONTRACT_ERROR",
        "STATISTICAL_ERROR",
    ];
    for item in &unique {
        if !component_verified(item)
            || !known.contains(&item.get("source").and_then(Value::as_str).unwrap_or(""))
        {
            unresolved.push(component_id(item));
        }
    }
    if float_route && !integer_route && execution_status == "UNRESOLVED" {
        unresolved.push("ROUNDING_ERROR".into());
    }
    if !ffi_unresolved.is_empty() {
        unresolved.push("FFI_CONVERSION_ERROR".into());
    }
    if artifacts.iter().any(|a| {
        a.get("obligations")
            .and_then(Value::as_array)
            .is_some_and(|v| !v.is_empty())
    }) {
        unresolved.push("SERIALIZATION_ERROR".into());
    }
    unresolved.sort();
    unresolved.dedup();
    let completeness = if !unresolved.is_empty() {
        "ERROR_SOURCE_UNRESOLVED"
    } else if components.iter().any(|item| {
        item.get("assumptions")
            .and_then(Value::as_array)
            .is_some_and(|v| !v.is_empty())
    }) {
        "ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS"
    } else {
        "ERROR_MODEL_COMPLETE"
    };
    let error_status = if completeness == "ERROR_MODEL_COMPLETE"
        && output.get("range_status").and_then(Value::as_str)
            == Some("TOTAL_TRUE_VALUE_ENCLOSURE_VERIFIED")
    {
        "KERNEL_VERIFIED"
    } else if completeness == "ERROR_MODEL_COMPLETE_UNDER_ASSUMPTIONS" {
        "KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    } else {
        "UNRESOLVED"
    };
    let serialization_status = if artifacts.is_empty() {
        "NOT_APPLICABLE"
    } else if artifacts.iter().all(|a| {
        a.get("status").and_then(Value::as_str) == Some("ARTIFACT_PAYLOAD_ENCLOSURE_VERIFIED")
    }) {
        "REFERENCE_CONTRACT_VERIFIED"
    } else {
        "UNRESOLVED"
    };
    let artifact_status = if artifacts.is_empty() {
        "NOT_APPLICABLE"
    } else if serialization_status != "UNRESOLVED" {
        "ENCLOSURE_VERIFIED"
    } else {
        "UNRESOLVED"
    };
    let mut completeness_obligations = vec![];
    if !duplicate.is_empty() {
        completeness_obligations.push(json!({"kind":"SHARED_ERROR_CAUSE_DEDUPLICATED","status":"RESOLVED","component_ids":duplicate}));
    }
    if !unresolved.is_empty() {
        completeness_obligations.push(
            json!({"kind":"ERROR_SOURCE_UNRESOLVED","status":"UNRESOLVED","sources":unresolved}),
        );
    }
    let approximation_status = if approximation.is_empty() {
        "NOT_APPLICABLE"
    } else if approximation_ok && !approximation_assumptions.is_empty() {
        "KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
    } else if approximation_ok {
        "KERNEL_VERIFIED"
    } else {
        "UNRESOLVED"
    };
    let layers = vec![
        layer("THEORY", if theory.is_null() {"UNRESOLVED"} else {"REGISTERED"}, if theory.is_null() {"No theory expression is registered."} else {"An independent theory expression is registered."}, false, vec![], vec![]),
        layer("IMPLEMENTATION", "EXTRACTED", "The implementation expression was extracted from source.", false, vec![], vec![]),
        layer("THEORY_IMPLEMENTATION", if exact_theory {"KERNEL_VERIFIED"} else {"UNRESOLVED"}, if exact_theory {"Lean kernel verified the theory/implementation relation."} else {"The theory/implementation relation is not kernel verified."}, true, vec![], vec![]),
        layer("TRANSFORMATION", if output.pointer("/residual/transformation_trace").is_some_and(|v| !v.as_object().is_some_and(Map::is_empty)) {"RECORDED"} else {"NOT_APPLICABLE"}, if output.pointer("/residual/transformation_trace").is_some_and(|v| !v.as_object().is_some_and(Map::is_empty)) {"The implementation uses an explicit transformation trace."} else {"No transformation is required."}, false, vec![], vec![]),
        layer("APPROXIMATION", approximation_status, if approximation.is_empty() {"No approximation operator occurs on this route."} else {"Approximation proof obligations and bounds are composed."}, true, approximation_assumptions.clone(), vec![]),
        layer("RANGE", range_status, if range_status == "UNRESOLVED" {"The total true-value enclosure is unresolved."} else {"The value/error enclosure is total."}, true, vec![], output.get("range_obligations").and_then(Value::as_array).cloned().unwrap_or_default()),
        layer("ERROR", error_status, if error_status == "UNRESOLVED" {"At least one critical error source is missing or unresolved."} else {"Every critical error source is represented and bounded."}, true, vec![], completeness_obligations.clone()),
        layer("NUMERIC_EXECUTION", execution_status, if integer_route {"Execution is exact in the audited integer fragment."} else if execution_status == "ENCLOSURE_VERIFIED" {"Finite execution bounds and rounding components are enclosed."} else {"Numeric execution type/range/rounding semantics are unresolved."}, true, vec![], execution_obligations),
        layer("PARALLEL", output.pointer("/implementation/parallel_semantics/proof_status").and_then(Value::as_str).unwrap_or("NOT_APPLICABLE"), if output.pointer("/implementation/parallel_semantics").is_some() {"Parallel execution semantics are recorded."} else {"No parallel execution operator occurs."}, output.pointer("/implementation/parallel_semantics").is_some(), vec![], vec![]),
        layer("FFI", ffi_status, if boundaries.is_empty() {"No FFI boundary occurs on the project route."} else if ffi_status == "REFERENCE_CONTRACT_VERIFIED" {"Every FFI representation mapping is range preserving."} else {"At least one FFI representation mapping is unresolved."}, !boundaries.is_empty(), vec![], ffi_unresolved.iter().map(|b| json!({"kind":"FFI_REPRESENTATION_RANGE_UNRESOLVED","status":"UNRESOLVED","boundary_id":b.get("boundary_id")})).collect()),
        layer("SERIALIZATION", serialization_status, if artifacts.is_empty() {"No serialization boundary occurs."} else if serialization_status == "REFERENCE_CONTRACT_VERIFIED" {"Serialization contracts preserve the certified payload value."} else {"Serialization value preservation is unresolved."}, !artifacts.is_empty(), vec![], artifacts.iter().flat_map(|a| a.get("obligations").and_then(Value::as_array).cloned().unwrap_or_default()).collect()),
        layer("ARTIFACT", artifact_status, if artifacts.is_empty() {"No artifact is attached."} else if artifact_status == "ENCLOSURE_VERIFIED" {"Every attached artifact payload is enclosed."} else {"At least one artifact payload enclosure is unresolved."}, !artifacts.is_empty(), vec![], vec![]),
        layer("LEAN", if output.get("lean_status").and_then(Value::as_str) == Some("LEAN_KERNEL_VERIFIED") {"KERNEL_VERIFIED"} else {"UNRESOLVED"}, if output.get("lean_status").and_then(Value::as_str) == Some("LEAN_KERNEL_VERIFIED") {"Lean kernel accepted the generated theory relation."} else {"Lean kernel evidence is not available."}, false, vec![], vec![]),
    ];
    let mut assumptions: BTreeMap<String, Value> = BTreeMap::new();
    for range in project
        .pointer("/provenance/range_specification/ranges")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let text = format!(
            "{} in [{}, {}]",
            range.get("name").and_then(Value::as_str).unwrap_or("?"),
            range.get("lower").unwrap_or(&Value::Null),
            range.get("upper").unwrap_or(&Value::Null)
        );
        assumptions.insert(text.clone(), json!({"assumption":text,"status":"PROVIDED","sources":[range.get("name")],"layers":["RANGE"]}));
    }
    for component in &components {
        for text in component
            .get("assumptions")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if let Some(text) = text.as_str() {
                assumptions.insert(text.into(), json!({"assumption":text,"status":if component_verified(component){"PROVEN"}else{"UNRESOLVED"},"sources":[component_id(component)],"layers":["ERROR"]}));
            }
        }
    }
    let assumption_values: Vec<Value> = assumptions.into_values().collect();
    let assumption_dependencies: Vec<Value> = assumption_values
        .iter()
        .flat_map(|item| {
            let text = item.get("assumption").cloned().unwrap_or(Value::Null);
            let sources = item.get("sources").and_then(Value::as_array).cloned().unwrap_or_default();
            let layers = item.get("layers").and_then(Value::as_array).cloned().unwrap_or_default();
            layers.into_iter().flat_map(move |layer_name| {
                let text = text.clone();
                sources.clone().into_iter().map(move |source| json!({
                    "assumption":text,"layer":layer_name,"claim_dependency":output.get("output_id"),"source":source
                }))
            })
        })
        .collect();
    let critical_unresolved = layers.iter().any(|item| {
        item.get("critical")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            && !VERIFIED.contains(&item.get("status").and_then(Value::as_str).unwrap_or(""))
    });
    let verified_any = layers.iter().any(|item| {
        item.get("critical")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            && VERIFIED.contains(&item.get("status").and_then(Value::as_str).unwrap_or(""))
    });
    let observed_status = match (
        observed.and_then(Value::as_f64),
        output.get("true_value_enclosure"),
    ) {
        (Some(value), Some(bounds))
            if bounds.get("lower").is_some_and(finite)
                && bounds.get("upper").is_some_and(finite) =>
        {
            Some(
                if value >= bounds["lower"].as_f64().unwrap()
                    && value <= bounds["upper"].as_f64().unwrap()
                {
                    "OBSERVED_VALUE_WITHIN_CERTIFIED_RANGE"
                } else {
                    "OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE"
                },
            )
        }
        (Some(_), _) | (_, Some(_)) if observed.is_some() => {
            Some("OBSERVED_VALUE_COMPARISON_UNRESOLVED")
        }
        _ => None,
    };
    let failed = observed_status == Some("OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE")
        || constraint == Some("OUTPUT_RANGE_CONSTRAINT_VIOLATED");
    let assumptions_closed = assumption_values.iter().all(|a| {
        matches!(
            a.get("status").and_then(Value::as_str),
            Some("PROVEN" | "PROVIDED" | "REFERENCE_CONTRACT")
        )
    });
    let status = if failed {
        "END_TO_END_FAILED"
    } else if critical_unresolved {
        if verified_any {
            "PARTIAL_END_TO_END_VERIFICATION"
        } else {
            "END_TO_END_UNRESOLVED"
        }
    } else if !assumptions_closed {
        "PARTIAL_END_TO_END_VERIFICATION"
    } else if layers
        .iter()
        .filter(|v| v.get("critical").and_then(Value::as_bool).unwrap_or(false))
        .all(|v| {
            matches!(
                v.get("status").and_then(Value::as_str),
                Some("KERNEL_VERIFIED" | "NOT_APPLICABLE")
            )
        })
    {
        if assumption_values.is_empty() {
            "END_TO_END_KERNEL_VERIFIED"
        } else {
            "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
        }
    } else if assumption_values.is_empty() {
        "END_TO_END_ENCLOSURE_VERIFIED"
    } else {
        "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS"
    };
    let bound = output
        .get("total_bound")
        .and_then(|v| {
            v.get("exact_value")
                .or_else(|| v.pointer("/symmetric_bound/value"))
        })
        .and_then(Value::as_f64)
        .or_else(|| {
            output
                .pointer("/error_interval/interval/upper")
                .and_then(Value::as_f64)
                .map(f64::abs)
        });
    let tolerance = specification
        .and_then(|s| s.get("absolute_tolerance"))
        .and_then(Value::as_f64)
        .map(|tol| {
            if VERIFIED.contains(&error_status) && bound.is_some_and(|b| b <= tol) {
                "TOTAL_TOLERANCE_PROVEN"
            } else if bound.is_some_and(|b| b <= tol) {
                "KNOWN_BOUND_WITHIN_TOLERANCE"
            } else {
                "TOTAL_TOLERANCE_NOT_PROVEN"
            }
        });
    let remaining: Vec<Value> = layers
        .iter()
        .flat_map(|l| {
            l.get("obligations")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
        })
        .filter(|o| o.get("status").and_then(Value::as_str) != Some("RESOLVED"))
        .collect();
    let proof_chain = proof_chain(output, &layers, !artifacts.is_empty());
    let id = claim_id(output, &proof_chain);
    let explanation = if failed {
        "An observed value or required output constraint contradicts the certified enclosure."
    } else if critical_unresolved {
        "Verified subclaims are retained, but the overall audit remains incomplete."
    } else if status.contains("UNDER_ASSUMPTIONS") {
        "Every critical layer is enclosed, subject to the explicitly listed assumptions."
    } else {
        "Every critical layer required by this route is verified by the recorded proof chain."
    };
    json!({"claim_id":id,"root_id":output_root(project, output.get("output_id").unwrap_or(&Value::Null)),"output_id":output.get("output_id"),"output_name":output.get("name"),
        "theory_expression":theory,"implementation_expression":formula,"transformation_trace":output.pointer("/residual/transformation_trace").cloned().unwrap_or_else(||json!({})),
        "approximation_proofs":approximation,"value_enclosure":output.get("value_interval"),"error_components":components,
        "known_error_bound":output.get("known_bound"),"total_error_bound":output.get("error_bound").or_else(||output.get("total_bound")),
        "true_value_enclosure":output.get("true_value_enclosure"),"execution_semantics":{"implementation":output.get("implementation"),"execution_range":output.get("execution_range")},
        "ffi_boundaries":boundaries,"serialization_boundaries":[],"artifact":artifacts,"assumptions":assumption_values,"assumption_dependencies":assumption_dependencies,
        "remaining_obligations":remaining,"proof_chain":proof_chain,"verification_matrix":layers,"error_completeness_status":completeness,
        "tolerance_status":tolerance,"output_range_constraint_status":constraint,"observed_result":observed,"observed_result_status":observed_status,
        "model_error_scope":model_scope.cloned().unwrap_or_else(||json!("MODEL_ERROR_NOT_IN_SCOPE")),"status":status,"explanation":explanation,
        "enclosure":{"value_enclosure":output.get("value_interval"),"error_enclosure":output.get("error_interval"),"true_value_enclosure":output.get("true_value_enclosure"),
            "artifact_enclosures":artifacts,"output_range_constraint_status":constraint,"tolerance_status":tolerance,"status":status}})
}

pub fn assemble_project_verification(request: &Value) -> Result<Value> {
    let mut project = request
        .get("project")
        .cloned()
        .ok_or_else(|| FormulaTracerError::InvalidSemanticDocument("project required".into()))?;
    let observations = request.get("observed_results").and_then(Value::as_object);
    let specifications = request
        .get("error_specifications")
        .and_then(Value::as_object);
    let model_scopes = request.get("model_error_scopes").and_then(Value::as_object);
    let snapshot = project.clone();
    let outputs = project
        .get_mut("outputs")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| {
            FormulaTracerError::InvalidSemanticDocument("project outputs required".into())
        })?;
    let mut claims = vec![];
    let mut counts = BTreeMap::from([
        ("number_of_outputs", outputs.len()),
        ("fully_verified", 0),
        ("verified_under_assumptions", 0),
        ("partially_verified", 0),
        ("unresolved", 0),
        ("failed", 0),
    ]);
    for output in outputs.iter_mut() {
        let name = output
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        let claim = output_claim(
            &snapshot,
            output,
            observations.and_then(|v| v.get(&name)),
            specifications.and_then(|v| v.get(&name).or_else(|| v.get("*"))),
            model_scopes.and_then(|v| v.get(&name)),
        );
        let status = claim
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("END_TO_END_UNRESOLVED")
            .to_string();
        match status.as_str() {
            "END_TO_END_KERNEL_VERIFIED" | "END_TO_END_ENCLOSURE_VERIFIED" => {
                *counts.get_mut("fully_verified").unwrap() += 1
            }
            s if s.contains("UNDER_ASSUMPTIONS") => {
                *counts.get_mut("verified_under_assumptions").unwrap() += 1
            }
            "PARTIAL_END_TO_END_VERIFICATION" => {
                *counts.get_mut("partially_verified").unwrap() += 1
            }
            "END_TO_END_FAILED" => *counts.get_mut("failed").unwrap() += 1,
            _ => *counts.get_mut("unresolved").unwrap() += 1,
        }
        if let Some(object) = output.as_object_mut() {
            object.insert("end_to_end_status".into(), json!(status));
            object.insert("end_to_end_claim".into(), claim.clone());
            object.insert("proof_chain".into(), claim["proof_chain"].clone());
            object.insert("artifact_enclosure".into(), claim["artifact"].clone());
            object.insert(
                "total_error_bound".into(),
                claim["total_error_bound"].clone(),
            );
            object.insert(
                "remaining_obligations".into(),
                claim["remaining_obligations"].clone(),
            );
        }
        claims.push(claim);
    }
    let project_status = if counts["failed"] > 0 {
        "END_TO_END_FAILED"
    } else if counts["unresolved"] > 0
        && counts["fully_verified"]
            + counts["verified_under_assumptions"]
            + counts["partially_verified"]
            == 0
    {
        "END_TO_END_UNRESOLVED"
    } else if counts["unresolved"] > 0 || counts["partially_verified"] > 0 {
        "PARTIAL_END_TO_END_VERIFICATION"
    } else if counts["verified_under_assumptions"] > 0 {
        if !claims.is_empty()
            && claims
                .iter()
                .all(|claim| claim["status"] == "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS")
        {
            "END_TO_END_KERNEL_VERIFIED_UNDER_ASSUMPTIONS"
        } else {
            "END_TO_END_ENCLOSURE_VERIFIED_UNDER_ASSUMPTIONS"
        }
    } else if !claims.is_empty()
        && claims
            .iter()
            .all(|c| c["status"] == "END_TO_END_KERNEL_VERIFIED")
    {
        "END_TO_END_KERNEL_VERIFIED"
    } else if claims.is_empty() {
        "END_TO_END_UNRESOLVED"
    } else {
        "END_TO_END_ENCLOSURE_VERIFIED"
    };
    let object = project.as_object_mut().unwrap();
    object.insert("end_to_end_claims".into(), Value::Array(claims));
    object.insert("end_to_end_coverage".into(), serde_json::to_value(counts)?);
    object.insert("end_to_end_status".into(), json!(project_status));
    Ok(project)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unresolved_input_never_becomes_verified() {
        let request = json!({"project":{"outputs":[{"output_id":"o","name":"y","formula":{"op":"FunctionCall","name":"f"},"status":"UNRESOLVED","lean_status":"NOT_RUN","error_components":[],"range_obligations":[]}],"artifacts":[],"provenance":{}},"observed_results":{}});
        let result = assemble_project_verification(&request).unwrap();
        assert!(matches!(
            result["outputs"][0]["end_to_end_status"].as_str(),
            Some("END_TO_END_UNRESOLVED" | "PARTIAL_END_TO_END_VERIFICATION")
        ));
    }
}
