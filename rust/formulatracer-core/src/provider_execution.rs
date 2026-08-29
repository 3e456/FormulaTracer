//! Execution and numerical-relation semantics shared by provider adapters.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::coverage::CoverageLevel;
use crate::{FormulaTracerError, RelationKind, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum EvidenceAuthority {
    UpstreamReferenceGuarantee,
    FormulaTracerDerivedGuarantee,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum DaskOperationKind {
    Elementwise,
    Sum,
    Mean,
    Dot,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum NumericalProblemKind {
    LinearSolve,
    DefiniteIntegral,
    Optimization,
    Interpolation,
    SignalTransform,
}

fn required<'a>(request: &'a Value, key: &str) -> Result<&'a Value> {
    request.get(key).ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument(format!("provider request missing {key}"))
    })
}

fn dask(request: &Value) -> Result<Value> {
    let operation: DaskOperationKind =
        serde_json::from_value(required(request, "operation_kind")?.clone())?;
    let backend = request.get("backend").and_then(Value::as_str);
    let dtype = request.get("dtype").and_then(Value::as_str);
    let reduction = !matches!(operation, DaskOperationKind::Elementwise);
    let chunks = request
        .get("chunk_counts")
        .and_then(Value::as_array)
        .filter(|values| values.iter().all(|v| v.as_u64().is_some()));
    let split_every = request.get("split_every").and_then(Value::as_u64);
    let tree_known = !reduction || (chunks.is_some() && split_every.is_some_and(|v| v >= 2));

    let mathematical_target = match operation {
        DaskOperationKind::Elementwise => {
            json!({"op":"Elementwise","operator":request.get("operator")})
        }
        DaskOperationKind::Sum => json!({"op":"FiniteSum","axis":request.get("axis")}),
        DaskOperationKind::Mean => json!({"op":"Mean","axis":request.get("axis")}),
        DaskOperationKind::Dot => json!({"op":"TensorContraction","axes":request.get("axis")}),
    };
    let execution = if reduction {
        json!({
            "op":"ChunkedReduction",
            "stages":["CHUNK","COMBINE","AGGREGATE"],
            "chunk_counts":chunks,
            "split_every":split_every,
            "tree_known":tree_known,
            "backend":backend,
            "dtype":dtype
        })
    } else {
        json!({"op":"DataflowElementwise","backend":backend,"dtype":dtype})
    };

    let mut unresolved = vec![];
    if backend.is_none() {
        unresolved.push(json!({"code":"DASK_BACKEND_UNRESOLVED"}));
    }
    if dtype.is_none() {
        unresolved.push(json!({"code":"DASK_DTYPE_UNRESOLVED"}));
    }
    if reduction && !tree_known {
        unresolved.push(json!({"code":"DASK_REDUCTION_TREE_UNRESOLVED"}));
    }
    let status = if unresolved.is_empty() {
        CoverageLevel::FullReconstruction
    } else {
        CoverageLevel::PartialReconstruction
    };
    let error_status = if reduction && tree_known && backend.is_some() && dtype.is_some() {
        "CONDITIONAL_DERIVATION_AVAILABLE"
    } else {
        "UNRESOLVED"
    };
    Ok(json!({
        "status":status,
        "mathematical_target":mathematical_target,
        "execution_semantics":execution,
        "mathematical_execution_exact_equivalence":false,
        "error_certificate":{
            "status":error_status,
            "authority":EvidenceAuthority::FormulaTracerDerivedGuarantee,
            "certified":false,
            "proof_obligations":["IEEE754_BACKEND_CONTRACT","REDUCTION_TREE_VALIDATION"]
        },
        "evidence":[{
            "authority":EvidenceAuthority::UpstreamReferenceGuarantee,
            "reference":"https://docs.dask.org/en/stable/generated/dask.array.reduction.html",
            "claims":["chunk/combine/aggregate structure","axis","dtype","keepdims","split_every"]
        }],
        "unresolved":unresolved
    }))
}

fn numerical_relation(request: &Value) -> Result<Value> {
    let problem_kind: NumericalProblemKind =
        serde_json::from_value(required(request, "problem_kind")?.clone())?;
    let callback_required = matches!(
        problem_kind,
        NumericalProblemKind::DefiniteIntegral | NumericalProblemKind::Optimization
    );
    let callback = request.get("callback_ir").filter(|v| !v.is_null());
    if callback_required && callback.is_none() {
        return Ok(json!({
            "status":CoverageLevel::PartialReconstruction,
            "problem":required(request,"problem")?,
            "algorithm":required(request,"algorithm")?,
            "returned_approximation":required(request,"returned_approximation")?,
            "unresolved":[{"code":"CALLBACK_RECONSTRUCTION_UNRESOLVED"}],
            "exact_promotion":false,
            "certified_promotion":false
        }));
    }
    let error_estimate = request.get("error_estimate").filter(|v| !v.is_null());
    Ok(json!({
        "status":CoverageLevel::FullReconstruction,
        "problem_layer":{"kind":problem_kind,"target":required(request,"problem")?},
        "algorithm_layer":{
            "method":required(request,"algorithm")?,
            "callback":callback,
            "tolerances":request.get("tolerances").cloned().unwrap_or(json!({}))
        },
        "result_layer":required(request,"returned_approximation")?,
        "relation_chain":[
            {"kind":RelationKind::AlgorithmicallyRealizedBy,"from":"PROBLEM","to":"ALGORITHM"},
            {"kind":RelationKind::ApproximationOf,"from":"COMPUTED_RESULT","to":"PROBLEM"}
        ],
        "error_evidence": if let Some(estimate) = error_estimate {
            json!({"kind":"LIBRARY_RETURNED_ESTIMATE","value":estimate,"certified":false})
        } else { json!({"kind":"BOUND_NOT_AVAILABLE","certified":false}) },
        "exact_promotion":false,
        "certified_promotion":false,
        "evidence":[{
            "authority":EvidenceAuthority::UpstreamReferenceGuarantee,
            "reference":required(request,"official_reference")?
        }],
        "unresolved":[]
    }))
}

fn compare_reduction_trees(request: &Value) -> Result<Value> {
    let left = required(request, "left_tree")?;
    let right = required(request, "right_tree")?;
    Ok(json!({
        "same_mathematical_target":true,
        "same_execution_order":left == right,
        "bitwise_equivalent": if left == right { "NOT_ESTABLISHED" } else { "FALSE_OR_NOT_ESTABLISHED" },
        "exact_promotion":false
    }))
}

pub(crate) fn provider_execution_operation(request: &Value) -> Result<Value> {
    match required(request, "action")?.as_str().unwrap_or("") {
        "DASK_ANALYZE" => dask(request),
        "NUMERICAL_RELATION" => numerical_relation(request),
        "COMPARE_REDUCTION_TREES" => compare_reduction_trees(request),
        _ => Err(FormulaTracerError::InvalidSemanticDocument(
            "unknown provider-execution action".into(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_dask_backend_stays_partial() {
        let result = provider_execution_operation(&json!({
            "action":"DASK_ANALYZE", "operation_kind":"SUM", "dtype":"float64",
            "chunk_counts":[4], "split_every":2, "axis":0
        }))
        .unwrap();
        assert_eq!(result["status"], "PARTIAL_RECONSTRUCTION");
        assert_eq!(result["error_certificate"]["certified"], false);
    }

    #[test]
    fn scipy_error_estimate_is_not_a_certificate() {
        let result = provider_execution_operation(&json!({
            "action":"NUMERICAL_RELATION", "problem_kind":"DEFINITE_INTEGRAL",
            "problem":{"op":"Integral"}, "algorithm":"QUADPACK",
            "callback_ir":{"op":"Power","base":"x","exponent":2},
            "returned_approximation":"y", "error_estimate":"abserr",
            "official_reference":"https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.quad.html"
        })).unwrap();
        assert_eq!(result["status"], "FULL_RECONSTRUCTION");
        assert_eq!(result["error_evidence"]["certified"], false);
        assert_eq!(result["exact_promotion"], false);
    }

    #[test]
    fn different_reduction_trees_never_exact_promote() {
        let result = provider_execution_operation(&json!({
            "action":"COMPARE_REDUCTION_TREES", "left_tree":[[0,1],[2,3]],
            "right_tree":[[[0,1],2],3]
        }))
        .unwrap();
        assert_eq!(result["same_execution_order"], false);
        assert_eq!(result["exact_promotion"], false);
    }
}
