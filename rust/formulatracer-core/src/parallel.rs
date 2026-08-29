//! Parallel execution-policy and numerical-equivalence decisions.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use std::collections::BTreeSet;

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn strings(value: Option<&Value>) -> BTreeSet<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn worker_effects(features: Option<&Value>) -> (bool, bool) {
    let Some(features) = features.filter(|value| !value.is_null()) else {
        return (false, false);
    };
    let targets = strings(features.get("assignment_target_kinds"));
    let mut race = features
        .get("has_global_nonlocal")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let mut cross = false;
    if targets.contains("Subscript")
        || targets.contains("Attribute")
        || features.get("mutating_call").and_then(Value::as_bool) == Some(true)
    {
        race = true;
        cross = true;
    }
    let loaded = strings(features.get("loaded_names"));
    let local = strings(features.get("local_names"));
    let safe: BTreeSet<String> = ["range", "len", "abs", "min", "max", "sum"]
        .into_iter()
        .map(str::to_owned)
        .collect();
    if loaded.difference(&local).any(|name| !safe.contains(name)) {
        race = true;
    }
    (race, cross)
}

fn aggregate_policy(operations: &[Value]) -> &'static str {
    if operations.is_empty() {
        return "SEQUENTIAL";
    }
    let present: BTreeSet<&str> = operations
        .iter()
        .filter_map(|item| item.get("policy").and_then(Value::as_str))
        .collect();
    for policy in [
        "PARALLEL_NONDETERMINISTIC",
        "UNKNOWN_EXECUTION_POLICY",
        "GPU_PARALLEL",
        "DISTRIBUTED",
        "PARALLEL_REORDERABLE",
        "PARALLEL_DETERMINISTIC",
    ] {
        if present.contains(policy) {
            return policy;
        }
    }
    "UNKNOWN_EXECUTION_POLICY"
}

pub fn parallel_operation(request: &Value) -> Result<Value> {
    if request.get("action").and_then(Value::as_str) != Some("ANALYZE") {
        return Err(invalid("UNSUPPORTED_PARALLEL_ACTION"));
    }
    let floating = request
        .get("floating")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let calls = request
        .get("calls")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid("PARALLEL_CALLS_REQUIRED"))?;
    let mut operations = Vec::new();
    let mut diagnostics = Vec::new();
    for call in calls {
        let name = call.get("callable").and_then(Value::as_str).unwrap_or("");
        let short = call.get("short").and_then(Value::as_str).unwrap_or("");
        let (race, cross) = worker_effects(call.get("worker_features"));
        let classified = if name.starts_with("dask.distributed.")
            || name.starts_with("client.")
            || name.starts_with("Client.")
            || matches!(short, "submit" | "gather")
        {
            Some((
                "distributed_task",
                "DISTRIBUTED",
                "DASK_DISTRIBUTED_SCHEDULER",
            ))
        } else if name.starts_with("dask.")
            || name.starts_with("da.")
            || matches!(
                short,
                "compute" | "persist" | "map_blocks" | "map_partitions"
            )
        {
            let backend_unknown =
                call.get("backend_status").and_then(Value::as_str) == Some("UNKNOWN");
            Some((
                "dask_graph",
                if backend_unknown {
                    "UNKNOWN_EXECUTION_POLICY"
                } else {
                    "PARALLEL_DETERMINISTIC"
                },
                if backend_unknown {
                    "DASK_BACKEND_UNRESOLVED"
                } else {
                    "DASK_GRAPH_SCHEDULER"
                },
            ))
        } else if matches!(
            short,
            "map" | "starmap" | "map_async" | "imap" | "imap_unordered"
        ) && ["pool", "Pool", "executor", "Executor"]
            .iter()
            .any(|token| name.contains(token))
        {
            Some((
                "parallel_map",
                if matches!(short, "imap_unordered" | "map_async") {
                    "PARALLEL_NONDETERMINISTIC"
                } else {
                    "PARALLEL_DETERMINISTIC"
                },
                "PROCESS_OR_FUTURE_SCHEDULER",
            ))
        } else if matches!(short, "Thread" | "start") || name.to_lowercase().contains("thread") {
            Some(("thread", "PARALLEL_NONDETERMINISTIC", "THREAD_INTERLEAVING"))
        } else if name.starts_with("cupy.")
            || name.starts_with("torch.")
            || name.starts_with("jax.")
        {
            Some(("gpu_kernel", "GPU_PARALLEL", "DEVICE_BACKEND_CONTRACT"))
        } else if matches!(short, "sum" | "prod" | "mean" | "dot" | "matmul" | "einsum")
            && (name.starts_with("np.") || name.starts_with("numpy."))
        {
            Some((
                "threaded_blas_or_reduction",
                "UNKNOWN_EXECUTION_POLICY",
                "THREAD_COUNT_AND_BACKEND_NOT_PINNED",
            ))
        } else {
            None
        };
        let Some((kind, mut policy, scheduler)) = classified else {
            continue;
        };
        let reduction =
            kind == "threaded_blas_or_reduction" || matches!(short, "sum" | "prod" | "mean");
        if reduction && policy == "PARALLEL_DETERMINISTIC" {
            policy = "PARALLEL_REORDERABLE";
        }
        let map_like = kind.contains("map")
            || matches!(
                short,
                "map"
                    | "starmap"
                    | "map_async"
                    | "imap"
                    | "imap_unordered"
                    | "map_blocks"
                    | "map_partitions"
            );
        let claims = json!({
            "PARALLEL_MAP_EQUIVALENT":if race||cross {"NOT_ESTABLISHED"} else if map_like {"ESTABLISHED_UNDER_PURITY_CONTRACT"} else {"NOT_APPLICABLE"},
            "PARALLEL_REDUCTION_EQUIVALENT_OVER_EXACT_DOMAIN":if reduction {"ESTABLISHED_UNDER_ASSOCIATIVITY"} else {"NOT_APPLICABLE"},
            "PARALLEL_REDUCTION_ORDER_DIFFERS":if reduction {"POSSIBLE"} else {"NOT_APPLICABLE"},
            "BITWISE_REPRODUCIBLE":if reduction||matches!(policy,"PARALLEL_NONDETERMINISTIC"|"UNKNOWN_EXECUTION_POLICY") {"NOT_ESTABLISHED"} else {"ESTABLISHED_UNDER_SCHEDULER_CONTRACT"},
            "NUMERICALLY_REPRODUCIBLE_WITHIN_TOLERANCE":if floating&&reduction {"REQUIRES_TOLERANCE_CONTRACT"} else {"NOT_APPLICABLE"},
            "POTENTIAL_DATA_RACE":if race {"DETECTED"} else {"NOT_DETECTED_STATICALLY"},
            "CROSS_ITERATION_DEPENDENCY":if cross {"DETECTED"} else {"NOT_DETECTED_STATICALLY"}
        });
        let span = call
            .get("source_span")
            .cloned()
            .unwrap_or_else(|| json!({}));
        if race {
            diagnostics.push(json!({"code":"POTENTIAL_DATA_RACE","message":format!("shared mutation in worker for {name}"),"source_span":span}));
        }
        if cross {
            diagnostics.push(json!({"code":"CROSS_ITERATION_DEPENDENCY","message":format!("worker iterations may depend on shared state for {name}"),"source_span":span}));
        }
        operations.push(
            json!({"callable":name,"kind":kind,"policy":policy,"source_span":span,
            "worker":call.get("worker"),"scheduler_contract":scheduler,"claims":claims}),
        );
    }
    let keys = [
        "PARALLEL_MAP_EQUIVALENT",
        "PARALLEL_REDUCTION_EQUIVALENT_OVER_EXACT_DOMAIN",
        "PARALLEL_REDUCTION_ORDER_DIFFERS",
        "BITWISE_REPRODUCIBLE",
        "NUMERICALLY_REPRODUCIBLE_WITHIN_TOLERANCE",
        "POTENTIAL_DATA_RACE",
        "CROSS_ITERATION_DEPENDENCY",
    ];
    let mut overall = serde_json::Map::new();
    for key in keys {
        let values: BTreeSet<&str> = operations
            .iter()
            .filter_map(|item| {
                item.pointer(&format!("/claims/{key}"))
                    .and_then(Value::as_str)
            })
            .collect();
        overall.insert(
            key.into(),
            json!(if values.is_empty() {
                "NOT_APPLICABLE"
            } else if values.len() == 1 {
                values.iter().next().copied().unwrap()
            } else {
                "MIXED"
            }),
        );
    }
    let unresolved = operations
        .iter()
        .any(|item| item.get("policy").and_then(Value::as_str) == Some("UNKNOWN_EXECUTION_POLICY"))
        || !diagnostics.is_empty();
    Ok(
        json!({"status":if unresolved{"PARALLEL_SEMANTICS_UNRESOLVED"}else{"PARALLEL_SEMANTICS_RESOLVED"},
        "overall_policy":aggregate_policy(&operations),"operations":operations,"claims":overall,"diagnostics":diagnostics}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reduction_is_never_bitwise_promoted() {
        let value=parallel_operation(&json!({"action":"ANALYZE","floating":true,"calls":[{"callable":"np.sum","short":"sum","source_span":{}}]})).unwrap();
        assert_eq!(
            value.pointer("/claims/BITWISE_REPRODUCIBLE").unwrap(),
            "NOT_ESTABLISHED"
        );
        assert_eq!(value["status"], "PARALLEL_SEMANTICS_UNRESOLVED");
    }
    #[test]
    fn unknown_dask_backend_is_fail_closed() {
        let value = parallel_operation(&json!({"action":"ANALYZE","floating":true,
            "calls":[{"callable":"dask.array.sum","short":"sum","backend_status":"UNKNOWN"}]}))
        .unwrap();
        assert_eq!(value["status"], "PARALLEL_SEMANTICS_UNRESOLVED");
        assert_eq!(
            value["operations"][0]["scheduler_contract"],
            "DASK_BACKEND_UNRESOLVED"
        );
        assert_eq!(value["claims"]["BITWISE_REPRODUCIBLE"], "NOT_ESTABLISHED");
    }
}
