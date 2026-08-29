//! Native assembly of residual, Error IR, obligations and enclosure evidence.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::{json, Value};

use crate::error_semantics::{constant, numeric, stable_id};
use crate::{
    compose_error_components, evaluate_error_budget, CompositionRequest, ErrorBound,
    ErrorComponent, FormulaTracerError, GraphPropagationRequest, ProofObligation, Result,
};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

fn first_output(ir: Option<&Value>) -> Option<&Value> {
    let ir = ir?;
    ir.get("outputs")
        .and_then(Value::as_array)
        .and_then(|v| v.first())
        .or(Some(ir))
}

fn root(ir: Option<&Value>) -> Option<Value> {
    first_output(ir)
        .and_then(|v| v.get("expression"))
        .cloned()
        .or_else(|| ir.cloned())
}

// Error bounds are serialized records with independent semantic fields. Keeping
// their construction explicit makes omissions visible at this trust boundary.
#[allow(clippy::too_many_arguments)]
fn bound(
    status: &str,
    metric: &str,
    expression: Option<Value>,
    exact: Option<Value>,
    theorem: Option<String>,
    assumptions: Vec<String>,
    parameters: Value,
    domain: Option<Value>,
    evidence: Value,
) -> ErrorBound {
    ErrorBound {
        status: status.into(),
        metric: metric.into(),
        expression,
        exact_value: exact,
        theorem_reference: theorem,
        assumptions,
        bound_id: String::new(),
        lower_bound: None,
        upper_bound: None,
        symmetric_bound: None,
        symbolic_expression: None,
        parameters,
        domain,
        proof_evidence: evidence,
    }
    .normalize()
}

fn obligation(
    id: impl Into<String>,
    kind: &str,
    description: impl Into<String>,
    component: Option<String>,
    required: Vec<String>,
    origin: Option<String>,
    cause: Option<String>,
) -> ProofObligation {
    let component_copy = component.clone();
    ProofObligation {
        obligation_id: id.into(),
        kind: kind.into(),
        description: description.into(),
        status: "UNRESOLVED".into(),
        component_id: component,
        required_evidence: required,
        origin_id: origin,
        semantic_cause_id: cause,
        source_component: component_copy,
    }
}

fn push_component(components: &mut Vec<ErrorComponent>, component: ErrorComponent) -> Result<()> {
    if let Some(existing) = components
        .iter()
        .find(|v| v.semantic_cause_id == component.semantic_cause_id)
    {
        if existing != &component {
            return Err(invalid(format!(
                "CONFLICTING_ERROR_COMPONENT: {}",
                component.semantic_cause_id
            )));
        }
    } else {
        components.push(component);
    }
    Ok(())
}

fn strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|v| v.as_str().map(str::to_owned))
        .collect()
}

fn specification(value: Option<&Value>, output: &str) -> Result<Value> {
    let mut spec = value
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    spec.entry("metric").or_insert(json!("ABSOLUTE"));
    spec.entry("output").or_insert(json!(output));
    let metric = spec.get("metric").and_then(Value::as_str).unwrap_or("");
    if !matches!(
        metric,
        "ABSOLUTE"
            | "RELATIVE"
            | "MIXED_ABSOLUTE_RELATIVE"
            | "COMPONENTWISE"
            | "L1"
            | "L2"
            | "LINF"
    ) {
        return Err(invalid("INVALID_ERROR_SPECIFICATION"));
    }
    if spec
        .get("absolute_tolerance")
        .and_then(Value::as_f64)
        .is_some_and(|v| v < 0.0)
    {
        return Err(invalid("NEGATIVE_ABSOLUTE_TOLERANCE"));
    }
    if spec
        .get("relative_tolerance")
        .and_then(Value::as_f64)
        .is_some_and(|v| v < 0.0)
    {
        return Err(invalid("NEGATIVE_RELATIVE_TOLERANCE"));
    }
    if metric == "RELATIVE" && spec.get("reference_nonzero").and_then(Value::as_bool) == Some(false)
    {
        return Err(invalid("RELATIVE_ERROR_DENOMINATOR_ZERO"));
    }
    if metric == "RELATIVE" && !spec.contains_key("reference_nonzero") {
        return Err(invalid("RELATIVE_ERROR_DOMAIN_UNRESOLVED"));
    }
    if metric == "MIXED_ABSOLUTE_RELATIVE"
        && !(spec.contains_key("absolute_tolerance") && spec.contains_key("relative_tolerance"))
    {
        return Err(invalid("MIXED_ERROR_REQUIRES_BOTH_TOLERANCES"));
    }
    for key in [
        "absolute_tolerance",
        "relative_tolerance",
        "reference_nonzero",
        "axis",
        "dimension",
        "mixed_tolerance",
        "per_axis",
        "per_dimension",
    ] {
        spec.entry(key).or_insert(Value::Null);
    }
    spec.entry("per_output").or_insert(json!({}));
    Ok(Value::Object(spec))
}

fn output_metadata(ir: Option<&Value>, name: &str) -> Option<Value> {
    first_output(ir)
        .and_then(|v| v.get(name))
        .or_else(|| ir.and_then(|v| v.get(name)))
        .cloned()
        .filter(|v| !v.is_null())
}

// Error components likewise require every provenance and proof field explicitly.
#[allow(clippy::too_many_arguments)]
fn component(
    id: &str,
    source: &str,
    expression: Value,
    metric: &str,
    error_bound: ErrorBound,
    proof_status: &str,
    provenance: Value,
    origin: &str,
    cause: &str,
) -> ErrorComponent {
    ErrorComponent {
        component_id: id.into(),
        source: source.into(),
        expression,
        metric: metric.into(),
        bound: error_bound,
        proof_status: proof_status.into(),
        provenance,
        origin_id: origin.into(),
        semantic_cause_id: cause.into(),
        assumptions: vec![],
        dependencies: vec![],
    }
}

fn normalize_residual(mut value: Value) -> Value {
    let expression = value.get("expression").cloned().unwrap_or(Value::Null);
    value["raw_relation"] = value
        .get("raw_relation")
        .cloned()
        .unwrap_or(expression.clone());
    value["normalized_residual"] = value
        .get("normalized_residual")
        .cloned()
        .unwrap_or(expression);
    value
}

pub fn build_error_analysis(request: &Value) -> Result<Value> {
    let output = request
        .get("output")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid("output required"))?;
    let relation = request
        .get("comparison_relation")
        .and_then(Value::as_str)
        .unwrap_or("UNRESOLVED");
    let theory = request.get("theory_ir").filter(|v| !v.is_null());
    let implementation = request
        .get("implementation_ir")
        .ok_or_else(|| invalid("implementation_ir required"))?;
    let comparison = request.get("comparison").filter(|v| !v.is_null());
    let types = request
        .get("numeric_type_semantics")
        .and_then(Value::as_object);
    let output_types = types
        .and_then(|v| v.get("outputs"))
        .and_then(Value::as_object);
    let output_type = output_types
        .and_then(|v| v.get(output).or_else(|| v.values().next()))
        .and_then(Value::as_object);
    let shape = output_type
        .and_then(|v| v.get("shape"))
        .cloned()
        .filter(|v| !v.is_null());
    let dimensions = output_type
        .and_then(|v| v.get("dimensions"))
        .cloned()
        .filter(|v| !v.is_null());
    let execution_domain = output_type
        .and_then(|v| v.get("mathematical_domain"))
        .cloned()
        .filter(|v| !v.is_null());
    let theory_shape = output_metadata(theory, "shape");
    let theory_dimensions = output_metadata(theory, "dimensions");
    let theory_domain = output_metadata(theory, "mathematical_domain");
    let shape_mismatch = shape.is_some() && theory_shape.is_some() && shape != theory_shape;
    let dimension_mismatch =
        dimensions.is_some() && theory_dimensions.is_some() && dimensions != theory_dimensions;
    let domain_mismatch =
        execution_domain.is_some() && theory_domain.is_some() && execution_domain != theory_domain;
    let componentwise = shape
        .as_ref()
        .and_then(Value::as_array)
        .is_some_and(|v| !v.is_empty())
        || dimensions
            .as_ref()
            .and_then(Value::as_array)
            .is_some_and(|v| !v.is_empty());
    let implementation_expression = root(Some(implementation)).unwrap_or(Value::Null);
    let theory_expression = root(theory);
    let exact = matches!(relation, "EXACT_EQUAL" | "EQUIVALENT_UNDER_ASSUMPTIONS")
        && comparison
            .and_then(|v| v.get("match"))
            .and_then(Value::as_bool)
            == Some(true)
        && !(shape_mismatch || dimension_mismatch || domain_mismatch);
    let spec = specification(request.get("specification"), output)?;
    let metric = spec
        .get("metric")
        .and_then(Value::as_str)
        .unwrap()
        .to_owned();
    let subtract_op = if componentwise {
        "ComponentwiseSubtract"
    } else {
        "Subtract"
    };
    let residual_expression = if theory_expression.is_none() {
        None
    } else if exact {
        Some(constant(0.0))
    } else {
        Some(json!({"op":subtract_op,"args":[implementation_expression,theory_expression]}))
    };
    let raw_relation = theory_expression.as_ref().map(|theory| {
        json!({"op":subtract_op,
        "args":[implementation_expression,theory]})
    });
    let theory_id = theory
        .and_then(|v| v.get("expression_id"))
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| theory_expression.as_ref().map(|v| stable_id("theory", v)));
    let implementation_id = implementation
        .get("expression_id")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| Some(stable_id("implementation", &implementation_expression)));
    let residual_id = stable_id(
        "residual",
        &json!([theory_id, implementation_id, residual_expression]),
    );
    let axes = shape
        .as_ref()
        .and_then(Value::as_array)
        .map(|v| (0..v.len()).collect::<Vec<_>>());
    let mut residual = normalize_residual(json!({
        "status":if theory_expression.is_none(){"THEORY_EXPRESSION_UNAVAILABLE"}else if exact{"EXACT_ZERO_RESIDUAL"}else{"SYMBOLIC_RESIDUAL"},
        "expression":residual_expression,"implementation_expression":implementation_expression,
        "theory_expression":theory_expression,"output":output,
        "scalar_or_componentwise":if componentwise{"COMPONENTWISE"}else{"SCALAR"},
        "shape":shape,"dimensions":dimensions,
        "alignment":if dimensions.is_some(){"DIMENSION_NAMES_PRESERVED"}else if shape.is_some(){"POSITIONAL_SHAPE_PRESERVED"}else{"SCALAR"},
        "numeric_samples_used_as_proof":false,"residual_id":residual_id,
        "theory_expression_id":theory_id,"implementation_expression_id":implementation_id,
        "raw_relation":raw_relation,"normalized_residual":residual_expression,
        "domain":theory_domain.clone().or(execution_domain.clone()),"axes":axes,
        "numeric_domain":execution_domain,"source_correspondence":comparison.and_then(|v|v.get("mapping")).cloned().unwrap_or_else(||json!({})),
        "transformation_trace":request.get("transformation_trace").cloned().unwrap_or_else(||json!({}))
    }));
    let mut components = Vec::new();
    let mut obligations = Vec::new();
    if shape_mismatch {
        residual["status"] = json!("SHAPE_MISMATCH");
        obligations.push(obligation(
            "residual-shape-match",
            "SHAPE_COMPATIBILITY",
            format!("Theory shape {theory_shape:?} must match implementation shape {shape:?}"),
            None,
            vec!["shape equality".into()],
            Some("residual".into()),
            Some("residual-shape".into()),
        ));
    }
    if dimension_mismatch {
        residual["status"] = json!("DIMENSION_ALIGNMENT_MISMATCH");
        obligations.push(obligation("residual-dimension-match", "DIMENSION_ALIGNMENT",
            format!("Theory dimensions {theory_dimensions:?} must match implementation dimensions {dimensions:?}"), None,
            vec!["named dimension alignment".into()], Some("residual".into()), Some("residual-dimensions".into())));
    }
    if domain_mismatch {
        residual["status"] = json!("DOMAIN_MISMATCH");
        obligations.push(obligation("residual-domain-match", "MATHEMATICAL_DOMAIN_COMPATIBILITY",
            format!("Theory domain {theory_domain:?} must match implementation domain {execution_domain:?}"), None,
            vec!["domain embedding or equality".into()], Some("residual".into()), Some("residual-domain".into())));
    }

    let approximation_proofs = request
        .get("approximation_proofs")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if exact {
        push_component(
            &mut components,
            component(
                "mathematical-residual",
                "MODEL_ERROR",
                constant(0.0),
                &metric,
                bound(
                    "EXACT_ZERO_BOUND",
                    &metric,
                    Some(constant(0.0)),
                    Some(json!(0)),
                    Some("CppAudit.Error.exact_equivalence_has_zero_residual".into()),
                    vec![],
                    json!({}),
                    None,
                    json!({}),
                ),
                "KERNEL_VERIFIABLE",
                json!({"kind":"SYMBOLIC_COMPARISON"}),
                "comparison",
                "exact-mathematical-residual",
            ),
        )?;
    } else if approximation_proofs.is_empty() {
        let cause = "unbounded-symbolic-residual";
        push_component(
            &mut components,
            component(
                cause,
                if theory_expression.is_some() {
                    "MODEL_ERROR"
                } else {
                    "UNKNOWN_ERROR_SOURCE"
                },
                residual_expression
                    .clone()
                    .unwrap_or_else(|| json!({"op":"OpaqueResidual"})),
                &metric,
                bound(
                    "BOUND_UNRESOLVED",
                    &metric,
                    None,
                    None,
                    None,
                    vec![],
                    json!({}),
                    None,
                    json!({}),
                ),
                "UNRESOLVED",
                json!({"kind":"INDEPENDENT_SYMBOLIC_RESIDUAL"}),
                cause,
                cause,
            ),
        )?;
        obligations.push(obligation(
            "bound-symbolic-residual",
            "MODEL_ERROR_BOUND_REQUIRED",
            "A bound for the unmatched symbolic residual is required",
            Some(cause.into()),
            vec!["model discrepancy bound".into()],
            Some(cause.into()),
            Some(cause.into()),
        ));
    }

    for proof in approximation_proofs {
        let theorem_id = proof
            .get("theorem_id")
            .or_else(|| proof.get("family_id"))
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let error = proof
            .get("error_bound")
            .cloned()
            .unwrap_or_else(|| json!({}));
        let family = proof.get("family_id").and_then(Value::as_str).unwrap_or("");
        let discrete = [
            "difference",
            "rectangle",
            "midpoint",
            "trapezoidal",
            "simpson",
        ]
        .iter()
        .any(|v| family.contains(v));
        let proof_status = proof
            .get("proof_status")
            .and_then(Value::as_str)
            .unwrap_or("UNRESOLVED");
        let verified = proof_status.starts_with("KERNEL_VERIFIED");
        let remaining = proof
            .get("remaining_obligations")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let assumptions = proof
            .get("assumptions")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|v| {
                v.get("statement")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            })
            .collect();
        let component_id = format!("approximation-{theorem_id}");
        push_component(
            &mut components,
            component(
                &component_id,
                if relation == "DISCRETIZATION_OF" || discrete {
                    "DISCRETIZATION_ERROR"
                } else {
                    "APPROXIMATION_ERROR"
                },
                error
                    .get("error_expression")
                    .cloned()
                    .unwrap_or_else(|| json!({"op":"Residual","family":family})),
                &metric,
                bound(
                    if verified && !remaining.is_empty() {
                        "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS"
                    } else if verified {
                        "KERNEL_VERIFIED_BOUND"
                    } else {
                        "BOUND_UNRESOLVED"
                    },
                    &metric,
                    error.get("bound").cloned(),
                    None,
                    proof
                        .get("evidence")
                        .and_then(|v| v.get("lean_theorem_name"))
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    assumptions,
                    proof
                        .get("parameters")
                        .cloned()
                        .unwrap_or_else(|| json!({})),
                    proof.get("domain").cloned(),
                    proof.get("evidence").cloned().unwrap_or_else(|| json!({})),
                ),
                proof_status,
                json!({"kind":"PHASE7_APPROXIMATION_PROOF","family_id":family,"error_role":"LOCAL_ERROR"}),
                &theorem_id,
                &theorem_id,
            ),
        )?;
        for item in remaining {
            let id = item
                .get("assumption_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .unwrap_or_else(|| stable_id("approx-obligation", &item));
            obligations.push(obligation(
                id.clone(),
                item.get("kind")
                    .and_then(Value::as_str)
                    .unwrap_or("APPROXIMATION_ASSUMPTION"),
                format!("Discharge approximation assumption {id}"),
                Some(component_id.clone()),
                vec![],
                Some(theorem_id.clone()),
                Some(format!("{theorem_id}:{id}")),
            ));
        }
    }

    let ieee = request.get("ieee754_semantics").and_then(Value::as_object);
    let operations = ieee
        .and_then(|v| v.get("operations"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if !operations.is_empty() {
        for (source, cause, description) in [
            (
                "ROUNDING_ERROR",
                "ieee754-rounding",
                "IEEE-754 rounding bound",
            ),
            (
                "OVERFLOW_ERROR",
                "ieee754-overflow",
                "finite-range overflow exclusion",
            ),
            (
                "UNDERFLOW_ERROR",
                "ieee754-underflow",
                "underflow/subnormal bound",
            ),
        ] {
            push_component(
                &mut components,
                component(
                    cause,
                    source,
                    json!({"op":"OpaqueErrorTerm","source":source}),
                    &metric,
                    bound(
                        "BOUND_NOT_EVALUATED",
                        &metric,
                        None,
                        None,
                        None,
                        vec![],
                        json!({}),
                        None,
                        json!({}),
                    ),
                    "UNRESOLVED",
                    json!({"kind":"IEEE754_SEMANTICS","operation_count":operations.len()}),
                    cause,
                    cause,
                ),
            )?;
            obligations.push(obligation(
                format!("bound-{cause}"),
                "NUMERICAL_EXECUTION_BOUND",
                description,
                Some(cause.into()),
                vec!["range analysis".into(), "machine error model".into()],
                Some(cause.into()),
                Some(cause.into()),
            ));
        }
    }
    for cast in types
        .and_then(|v| v.get("casts"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let cause = stable_id("cast", cast);
        let exact_cast = cast.get("exact").and_then(Value::as_str) == Some("EXACT");
        push_component(
            &mut components,
            component(
                &cause,
                "CAST_ERROR",
                json!({"op":"OpaqueErrorTerm","source":"CAST_ERROR","cast":cast}),
                &metric,
                bound(
                    if exact_cast {
                        "EXACT_ZERO_BOUND"
                    } else {
                        "BOUND_NOT_EVALUATED"
                    },
                    &metric,
                    exact_cast.then(|| constant(0.0)),
                    exact_cast.then(|| json!(0)),
                    None,
                    vec![],
                    json!({}),
                    None,
                    json!({}),
                ),
                if exact_cast {
                    "PROVEN_EXACT"
                } else {
                    "UNRESOLVED"
                },
                json!({"kind":"NUMERIC_CAST"}),
                &cause,
                &cause,
            ),
        )?;
        if !exact_cast {
            obligations.push(obligation(
                format!("bound-{cause}"),
                "CAST_ERROR_BOUND",
                "Bound inexact cast error",
                Some(cause.clone()),
                vec![],
                Some(cause.clone()),
                Some(cause),
            ));
        }
    }
    let parallel = request.get("parallel_semantics").and_then(Value::as_object);
    let parallel_claim = parallel
        .and_then(|v| v.get("claims"))
        .and_then(|v| v.get("PARALLEL_REDUCTION_ORDER_DIFFERS"))
        .and_then(Value::as_str);
    if matches!(parallel_claim, Some("POSSIBLE" | "MIXED")) {
        let cause = "parallel-reduction-order";
        let exact_parallel = matches!(
            execution_domain.as_ref().and_then(Value::as_str),
            Some("Integer" | "Rational")
        ) && operations.is_empty();
        push_component(
            &mut components,
            component(
                cause,
                "PARALLEL_ORDER_ERROR",
                if exact_parallel {
                    constant(0.0)
                } else {
                    json!({"op":"OpaqueErrorTerm","source":"PARALLEL_ORDER_ERROR"})
                },
                &metric,
                bound(
                    if exact_parallel {
                        "EXACT_ZERO_BOUND"
                    } else {
                        "BOUND_NOT_EVALUATED"
                    },
                    &metric,
                    exact_parallel.then(|| constant(0.0)),
                    exact_parallel.then(|| json!(0)),
                    None,
                    vec![],
                    json!({}),
                    None,
                    json!({}),
                ),
                if exact_parallel {
                    "PROVEN_EXACT_DOMAIN"
                } else {
                    "UNRESOLVED"
                },
                json!({"kind":"PARALLEL_SEMANTICS","policy":parallel.and_then(|v|v.get("overall_policy"))}),
                cause,
                cause,
            ),
        )?;
        if !exact_parallel {
            obligations.push(obligation(
                format!("bound-{cause}"),
                "PARALLEL_ORDER_BOUND",
                "Bound floating reduction reordering",
                Some(cause.into()),
                vec![],
                Some(cause.into()),
                Some(cause.into()),
            ));
        }
    }
    for contract in request
        .get("library_contracts")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let reference = contract
            .get("reference_status")
            .or_else(|| {
                contract
                    .get("provenance")
                    .and_then(|v| v.get("reference_status"))
            })
            .and_then(Value::as_str);
        let reference_only = contract.get("proof_status").and_then(Value::as_str)
            == Some("REFERENCE_CONTRACT_ONLY")
            || matches!(
                contract.get("reference_status").and_then(Value::as_str),
                Some("REFERENCE_ONLY" | "REFERENCE_CONTRACT_ONLY")
            )
            || matches!(
                contract.get("contract_status").and_then(Value::as_str),
                Some("REFERENCE_ONLY" | "NEEDS_CONTRACT")
            )
            || reference.is_some_and(|v| v != "LEAN_VERIFIED_MAPPING");
        if reference_only {
            let name = contract
                .get("qualified_callable")
                .or_else(|| contract.get("callable"))
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let cause = format!("library-contract:{name}");
            obligations.push(obligation(
                stable_id("library", &json!(cause)),
                "LIBRARY_SEMANTIC_PROOF_REQUIRED",
                format!("Kernel-level semantic mapping required for {name}"),
                None,
                vec!["formal semantic contract".into()],
                Some(name.into()),
                Some(cause),
            ));
        }
    }

    let context = request
        .get("propagation_context")
        .and_then(Value::as_object);
    let coefficient_map = context
        .and_then(|v| v.get("component_coefficients"))
        .and_then(Value::as_object);
    let coefficients = components
        .iter()
        .map(|v| {
            coefficient_map
                .and_then(|m| m.get(&v.component_id))
                .cloned()
                .unwrap_or(json!(1))
        })
        .collect();
    let axis = spec.get("axis").and_then(Value::as_i64).unwrap_or(0);
    let vector_length = shape
        .as_ref()
        .and_then(Value::as_array)
        .and_then(|v| v.get(axis as usize))
        .and_then(Value::as_i64);
    let composition_request = CompositionRequest {
        components: components.clone(),
        operation: context
            .and_then(|v| v.get("operation"))
            .and_then(Value::as_str)
            .unwrap_or("SUM")
            .into(),
        coefficients: Some(coefficients),
        output_metric: context
            .and_then(|v| v.get("output_metric"))
            .and_then(Value::as_str)
            .map(str::to_owned),
        value_bounds: context
            .and_then(|v| v.get("value_bounds"))
            .cloned()
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default(),
        denominator_lower_bound: context
            .and_then(|v| v.get("denominator_lower_bound"))
            .and_then(Value::as_f64),
        exponent: context
            .and_then(|v| v.get("exponent"))
            .and_then(Value::as_i64),
        dimension: context
            .and_then(|v| v.get("dimension"))
            .and_then(Value::as_i64),
        operator_norm: context.and_then(|v| v.get("operator_norm")).cloned(),
        sensitivity: context
            .and_then(|v| v.get("function_sensitivity"))
            .cloned()
            .and_then(|v| serde_json::from_value(v).ok()),
        count: context.and_then(|v| v.get("count")).and_then(Value::as_i64),
        assumptions: strings(context.and_then(|v| v.get("assumptions"))),
        vector_length,
        expected_coefficients: context
            .and_then(|v| v.get("expected_coefficients"))
            .cloned()
            .and_then(|v| serde_json::from_value(v).ok()),
        allow_exact_cancellation: context
            .and_then(|v| v.get("allow_exact_cancellation"))
            .and_then(Value::as_bool)
            .unwrap_or(false),
        dependence: context
            .and_then(|v| v.get("dependence"))
            .and_then(Value::as_str)
            .unwrap_or("DEPENDENCE_UNKNOWN")
            .into(),
        independence_proven: context
            .and_then(|v| v.get("independence_proven"))
            .and_then(Value::as_bool)
            .unwrap_or(false),
        kernel_checked: request
            .get("kernel_checked")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    };
    let mut composition = compose_error_components(composition_request)?;
    let mut graph_propagation = None;
    let component_paths = context
        .and_then(|v| v.get("component_paths"))
        .and_then(Value::as_object);
    if component_paths.is_some_and(|v| !v.is_empty()) {
        let by_id = components
            .iter()
            .map(|v| (v.component_id.clone(), v.clone()))
            .collect::<BTreeMap<_, _>>();
        let mut local_components: BTreeMap<String, Vec<ErrorComponent>> = BTreeMap::new();
        for (component_id, path) in component_paths.unwrap() {
            let item = by_id
                .get(component_id)
                .cloned()
                .ok_or_else(|| invalid(format!("ERROR_COMPONENT_PATH_UNKNOWN: {component_id}")))?;
            let key = path
                .as_str()
                .map(str::to_owned)
                .or_else(|| {
                    path.as_array().map(|parts| {
                        format!(
                            "/{}",
                            parts
                                .iter()
                                .map(|v| v
                                    .as_str()
                                    .map(str::to_owned)
                                    .unwrap_or_else(|| v.to_string()))
                                .collect::<Vec<_>>()
                                .join("/")
                        )
                    })
                })
                .unwrap_or_else(|| "/".into());
            local_components.entry(key).or_default().push(item);
        }
        let propagated = crate::propagate_expression_graph(GraphPropagationRequest {
            expression: implementation_expression.clone(),
            local_components,
            output: output.into(),
            contracts: context
                .and_then(|v| v.get("node_contracts"))
                .cloned()
                .and_then(|v| serde_json::from_value(v).ok())
                .unwrap_or_default(),
            kernel_checked: request
                .get("kernel_checked")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        })?;
        let mapped = component_paths
            .unwrap()
            .keys()
            .cloned()
            .collect::<BTreeSet<_>>();
        let final_components = propagated
            .output_components
            .iter()
            .cloned()
            .chain(
                components
                    .iter()
                    .filter(|v| !mapped.contains(&v.component_id))
                    .cloned(),
            )
            .collect();
        composition = compose_error_components(CompositionRequest {
            components: final_components,
            operation: "SUM".into(),
            kernel_checked: request
                .get("kernel_checked")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            ..Default::default()
        })?;
        composition.propagation_trace = propagated
            .propagation_trace
            .iter()
            .cloned()
            .chain(composition.propagation_trace)
            .collect();
        composition
            .obligations
            .extend(propagated.obligations.clone());
        graph_propagation = Some(propagated);
    }
    obligations.extend(composition.obligations.clone());
    let mut unique = BTreeMap::new();
    for item in obligations {
        unique.insert(
            item.semantic_cause_id
                .clone()
                .unwrap_or_else(|| item.obligation_id.clone()),
            item,
        );
    }
    let obligations = unique.into_values().collect::<Vec<_>>();
    let unresolved_components = components.is_empty()
        || components.iter().any(|v| {
            v.proof_status == "UNRESOLVED"
                || matches!(
                    v.bound.status.as_str(),
                    "BOUND_NOT_EVALUATED" | "BOUND_UNRESOLVED"
                )
        })
        || !obligations.is_empty();
    let verified_nonzero = components
        .iter()
        .any(|v| v.bound.status.starts_with("KERNEL_VERIFIED_BOUND"));
    let component_status = if verified_nonzero && unresolved_components {
        "PARTIAL_ERROR_BOUND_VERIFIED"
    } else if !unresolved_components {
        "ALL_COMPONENT_BOUNDS_VERIFIED"
    } else {
        "ERROR_COMPONENTS_UNRESOLVED"
    };
    let total_status = if composition.invalidated
        || unresolved_components
        || composition.total_status != "TOTAL_ERROR_BOUND_VERIFIED"
    {
        "TOTAL_ERROR_BOUND_UNRESOLVED"
    } else if exact
        && components
            .iter()
            .all(|v| v.bound.exact_value.as_ref().and_then(numeric) == Some(0.0))
    {
        "EXACT_ZERO_BOUND_VERIFIED"
    } else {
        "TOTAL_ERROR_BOUND_VERIFIED"
    };
    let total_bound = if total_status == "EXACT_ZERO_BOUND_VERIFIED" {
        bound(
            "EXACT_ZERO_BOUND",
            &metric,
            Some(constant(0.0)),
            Some(json!(0)),
            Some("CppAudit.Error.zero_residual_has_zero_absolute_error".into()),
            vec![],
            json!({}),
            None,
            json!({}),
        )
    } else {
        bound(
            if composition.invalidated {
                "BOUND_INVALID"
            } else if total_status != "TOTAL_ERROR_BOUND_VERIFIED" {
                "BOUND_NOT_EVALUATED"
            } else {
                &composition.known_bound.status
            },
            &metric,
            if composition.invalidated {
                None
            } else {
                composition.known_bound.expression.clone()
            },
            None,
            None,
            vec![],
            json!({}),
            None,
            json!({}),
        )
    };
    let propagation_id = format!("propagation:{output}");
    let mut nodes=components.iter().map(|v|json!({"node_id":v.component_id,"kind":"ERROR_COMPONENT","bound_status":v.bound.status})).collect::<Vec<_>>();
    nodes.push(json!({"node_id":propagation_id,"operation":composition.composition.operation,
        "input_bounds":components.iter().map(|v|v.bound.bound_id.clone()).collect::<Vec<_>>(),
        "local_error":components.iter().map(|v|v.component_id.clone()).collect::<Vec<_>>(),
        "propagated_error":components.iter().map(|v|v.semantic_cause_id.clone()).collect::<Vec<_>>(),
        "output_bound":composition.known_bound,"proof_rule":composition.composition.proof_rule,
        "status":composition.composition.status,"dependency_status":composition.composition.dependency_status}));
    let mut edges = components
        .iter()
        .map(|v| json!({"source":v.component_id,"target":propagation_id}))
        .chain(std::iter::once(
            json!({"source":propagation_id,"target":output}),
        ))
        .collect::<Vec<_>>();
    if let Some(propagated) = &graph_propagation {
        nodes.extend(
            propagated
                .nodes
                .iter()
                .map(|v| serde_json::to_value(v).expect("serializable")),
        );
        edges.extend(propagated.edges.clone());
    }
    let budget = evaluate_error_budget(
        &composition.known_bound,
        total_status,
        spec.get("absolute_tolerance").and_then(Value::as_f64),
    );
    let graph = json!({"status":if composition.invalidated{"ENCLOSURE_INVALIDATED"}else if
        !matches!(total_status,"TOTAL_ERROR_BOUND_VERIFIED"|"EXACT_ZERO_BOUND_VERIFIED"){"ENCLOSURE_UNRESOLVED"}else{"ENCLOSURE_VERIFIED"},
        "output":output,"nodes":nodes,"edges":edges,"output_bound":total_bound,"node_bounds":nodes,
        "edge_dependencies":edges,"input_bounds":[],
        "unresolved_nodes":components.iter().filter(|v|matches!(v.bound.status.as_str(),"BOUND_NOT_EVALUATED"|"BOUND_UNRESOLVED"))
            .map(|v|v.component_id.clone()).chain(obligations.iter().filter(|v|v.component_id.is_none()).map(|v|v.obligation_id.clone())).collect::<Vec<_>>(),
        "proof_dependencies":components.iter().filter_map(|v|v.bound.theorem_reference.clone()).collect::<Vec<_>>(),
        "propagation_trace":composition.propagation_trace,"known_output_bound":composition.known_bound,
        "total_output_status":total_status,"error_budget":budget});
    Ok(
        json!({"residual_expression":residual,"error_specification":spec,"error_components":components,
        "error_composition":composition.composition,"proof_obligations":obligations,"graph_enclosure":graph,
        "component_status":component_status,"total_status":total_status}),
    )
}
