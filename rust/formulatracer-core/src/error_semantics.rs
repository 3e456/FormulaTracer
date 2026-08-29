//! Native Error IR and conservative error propagation.
//!
//! This is the semantic owner for Error composition.  Bindings may project the
//! serialized values into ergonomic language objects, but must not recompute a
//! bound or discharge an obligation.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Number, Value};
use sha2::{Digest, Sha256};

use crate::{FormulaTracerError, Result};

const UNKNOWN_BOUND_STATUSES: &[&str] =
    &["BOUND_NOT_EVALUATED", "BOUND_UNRESOLVED", "BOUND_INVALID"];

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ErrorBound {
    pub status: String,
    pub metric: String,
    pub expression: Option<Value>,
    #[serde(default)]
    pub exact_value: Option<Value>,
    #[serde(default)]
    pub theorem_reference: Option<String>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub bound_id: String,
    #[serde(default)]
    pub lower_bound: Option<Value>,
    #[serde(default)]
    pub upper_bound: Option<Value>,
    #[serde(default)]
    pub symmetric_bound: Option<Value>,
    #[serde(default)]
    pub symbolic_expression: Option<Value>,
    #[serde(default)]
    pub parameters: Value,
    #[serde(default)]
    pub domain: Option<Value>,
    #[serde(default)]
    pub proof_evidence: Value,
}

impl ErrorBound {
    pub(crate) fn normalize(mut self) -> Self {
        if self.bound_id.is_empty() {
            self.bound_id = stable_id(
                "bound",
                &json!([
                    self.status,
                    self.metric,
                    self.expression,
                    self.theorem_reference
                ]),
            );
        }
        if self.symbolic_expression.is_none() {
            self.symbolic_expression = self.expression.clone();
        }
        if self.symmetric_bound.is_none() && self.expression.is_some() {
            self.symmetric_bound = self.expression.clone();
        }
        if self.exact_value.as_ref().and_then(Value::as_f64) == Some(0.0) {
            self.lower_bound.get_or_insert(json!(0));
            self.upper_bound.get_or_insert(json!(0));
        } else if let Some(expression) = self.expression.clone() {
            self.lower_bound
                .get_or_insert_with(|| json!({"op":"Negate","args":[expression.clone()]}));
            self.upper_bound.get_or_insert(expression);
        }
        if self.theorem_reference.is_some()
            && self.proof_evidence.as_object().is_none_or(Map::is_empty)
        {
            self.proof_evidence = json!({
                "kind":"LEAN_THEOREM_REFERENCE",
                "theorem":self.theorem_reference
            });
        }
        self
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ErrorComponent {
    pub component_id: String,
    pub source: String,
    pub expression: Value,
    pub metric: String,
    pub bound: ErrorBound,
    pub proof_status: String,
    #[serde(default)]
    pub provenance: Value,
    pub origin_id: String,
    pub semantic_cause_id: String,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub dependencies: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProofObligation {
    pub obligation_id: String,
    pub kind: String,
    pub description: String,
    #[serde(default = "unresolved")]
    pub status: String,
    #[serde(default)]
    pub component_id: Option<String>,
    #[serde(default)]
    pub required_evidence: Vec<String>,
    #[serde(default)]
    pub origin_id: Option<String>,
    #[serde(default)]
    pub semantic_cause_id: Option<String>,
    #[serde(default)]
    pub source_component: Option<String>,
}

fn unresolved() -> String {
    "UNRESOLVED".into()
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FunctionSensitivityContract {
    pub function: String,
    pub metric: String,
    pub lipschitz_bound: Value,
    pub domain: Value,
    #[serde(default)]
    pub assumptions: Vec<String>,
    pub proof_status: String,
    #[serde(default)]
    pub theorem_reference: Option<String>,
    #[serde(default)]
    pub provenance: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ErrorComposition {
    pub rule: String,
    pub status: String,
    pub component_ids: Vec<String>,
    #[serde(default)]
    pub cancellation_assumed: bool,
    pub kind: String,
    pub composition_id: String,
    pub operation: String,
    pub input_components: Vec<String>,
    pub input_bounds: Vec<ErrorBound>,
    pub output_metric: Option<String>,
    pub output_bound: Option<ErrorBound>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    pub proof_rule: Option<String>,
    #[serde(default)]
    pub proof_evidence: Value,
    #[serde(default)]
    pub provenance: Value,
    #[serde(default = "unknown_dependency")]
    pub dependency_status: String,
}

fn unknown_dependency() -> String {
    "DEPENDENCE_UNKNOWN".into()
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CompositionResult {
    pub composition: ErrorComposition,
    pub known_bound: ErrorBound,
    pub total_status: String,
    pub obligations: Vec<ProofObligation>,
    pub propagation_trace: Vec<Value>,
    #[serde(default)]
    pub invalidated: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PropagationNode {
    pub node_id: String,
    pub operation: String,
    pub input_bounds: Vec<String>,
    pub local_error: Vec<String>,
    pub propagated_error: Vec<String>,
    pub output_bound: Option<ErrorBound>,
    pub proof_rule: Option<String>,
    pub status: String,
    pub semantic_causes: Vec<String>,
    pub dependency_status: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GraphPropagationResult {
    pub nodes: Vec<PropagationNode>,
    pub edges: Vec<Value>,
    pub output_components: Vec<ErrorComponent>,
    pub output_composition: CompositionResult,
    pub obligations: Vec<ProofObligation>,
    pub propagation_trace: Vec<Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GraphPropagationRequest {
    pub expression: Value,
    #[serde(default)]
    pub local_components: BTreeMap<String, Vec<ErrorComponent>>,
    #[serde(default = "default_output")]
    pub output: String,
    #[serde(default)]
    pub contracts: BTreeMap<String, Value>,
    #[serde(default)]
    pub kernel_checked: bool,
}

fn default_output() -> String {
    "output".into()
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CompositionRequest {
    #[serde(default)]
    pub components: Vec<ErrorComponent>,
    #[serde(default = "sum_operation", rename = "error_operation")]
    pub operation: String,
    #[serde(default)]
    pub coefficients: Option<Vec<Value>>,
    #[serde(default)]
    pub output_metric: Option<String>,
    #[serde(default)]
    pub value_bounds: BTreeMap<String, Value>,
    #[serde(default)]
    pub denominator_lower_bound: Option<f64>,
    #[serde(default)]
    pub exponent: Option<i64>,
    #[serde(default)]
    pub dimension: Option<i64>,
    #[serde(default)]
    pub operator_norm: Option<Value>,
    #[serde(default)]
    pub sensitivity: Option<FunctionSensitivityContract>,
    #[serde(default)]
    pub count: Option<i64>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub vector_length: Option<i64>,
    #[serde(default)]
    pub expected_coefficients: Option<Vec<Value>>,
    #[serde(default)]
    pub allow_exact_cancellation: bool,
    #[serde(default = "unknown_dependency")]
    pub dependence: String,
    #[serde(default)]
    pub independence_proven: bool,
    #[serde(default)]
    pub kernel_checked: bool,
}

impl Default for CompositionRequest {
    fn default() -> Self {
        Self {
            components: vec![],
            operation: sum_operation(),
            coefficients: None,
            output_metric: None,
            value_bounds: BTreeMap::new(),
            denominator_lower_bound: None,
            exponent: None,
            dimension: None,
            operator_norm: None,
            sensitivity: None,
            count: None,
            assumptions: vec![],
            vector_length: None,
            expected_coefficients: None,
            allow_exact_cancellation: false,
            dependence: unknown_dependency(),
            independence_proven: false,
            kernel_checked: false,
        }
    }
}

fn sum_operation() -> String {
    "SUM".into()
}

pub(crate) fn stable_id(prefix: &str, value: &Value) -> String {
    let encoded = serde_json::to_vec(value).expect("JSON Value serialization is infallible");
    let digest = Sha256::digest(encoded);
    format!("{prefix}-{}", hex_prefix(&digest, 12))
}

fn hex_prefix(bytes: &[u8], chars: usize) -> String {
    let mut output = String::new();
    for byte in bytes {
        output.push_str(&format!("{byte:02x}"));
        if output.len() >= chars {
            output.truncate(chars);
            break;
        }
    }
    output
}

fn number(value: f64) -> Value {
    if value.fract() == 0.0 && value >= i64::MIN as f64 && value <= i64::MAX as f64 {
        Value::Number(Number::from(value as i64))
    } else {
        Number::from_f64(value)
            .map(Value::Number)
            .unwrap_or(Value::Null)
    }
}

pub(crate) fn numeric(value: &Value) -> Option<f64> {
    value
        .as_f64()
        .filter(|value| value.is_finite())
        .or_else(|| {
            value
                .as_object()
                .filter(|map| map.get("op").and_then(Value::as_str) == Some("Constant"))
                .and_then(|map| map.get("value"))
                .and_then(Value::as_f64)
                .filter(|value| value.is_finite())
        })
}

pub(crate) fn constant(value: f64) -> Value {
    json!({"op":"Constant","value":number(value)})
}

fn add(values: impl IntoIterator<Item = Value>) -> Value {
    let mut flattened = Vec::new();
    let mut total = 0.0;
    for value in values {
        if value.is_null() {
            continue;
        }
        if let Some(value) = numeric(&value) {
            total += value;
        } else if value.get("op").and_then(Value::as_str) == Some("AddBounds") {
            flattened.extend(
                value
                    .get("args")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default(),
            );
        } else {
            flattened.push(value);
        }
    }
    if total != 0.0 || flattened.is_empty() {
        flattened.push(constant(total));
    }
    if flattened.len() == 1 {
        flattened.pop().unwrap()
    } else {
        json!({"op":"AddBounds","args":flattened})
    }
}

fn mul(left: Value, right: Value) -> Value {
    let left = if left.is_number() {
        constant(numeric(&left).unwrap())
    } else {
        left
    };
    let right = if right.is_number() {
        constant(numeric(&right).unwrap())
    } else {
        right
    };
    if numeric(&left) == Some(0.0) || numeric(&right) == Some(0.0) {
        return constant(0.0);
    }
    if numeric(&left) == Some(1.0) {
        return right;
    }
    if numeric(&right) == Some(1.0) {
        return left;
    }
    if let (Some(left), Some(right)) = (numeric(&left), numeric(&right)) {
        return constant(left * right);
    }
    json!({"op":"MultiplyBounds","args":[left,right]})
}

fn divide(left: Value, right: Value) -> Result<Value> {
    let left = if left.is_number() {
        constant(numeric(&left).unwrap())
    } else {
        left
    };
    let right = if right.is_number() {
        constant(numeric(&right).unwrap())
    } else {
        right
    };
    if numeric(&right) == Some(0.0) {
        return Err(invalid("DENOMINATOR_MAY_CROSS_ZERO"));
    }
    Ok(json!({"op":"DivideBounds","args":[left,right]}))
}

fn power(base: Value, exponent: i64) -> Value {
    match exponent {
        0 => constant(1.0),
        1 => base,
        _ => json!({"op":"PowerBound","args":[base,constant(exponent as f64)]}),
    }
}

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

fn known(component: &ErrorComponent) -> bool {
    !UNKNOWN_BOUND_STATUSES.contains(&component.bound.status.as_str())
}

fn metric(components: &[ErrorComponent], output: Option<&str>) -> Result<String> {
    let mut metrics = components
        .iter()
        .filter(|item| known(item))
        .map(|item| item.metric.clone())
        .collect::<BTreeSet<_>>();
    if let Some(output) = output {
        metrics.insert(output.into());
    }
    if metrics.len() > 1 {
        return Err(invalid("INCOMPATIBLE_ERROR_METRICS"));
    }
    Ok(metrics
        .into_iter()
        .next()
        .unwrap_or_else(|| output.unwrap_or("ABSOLUTE").into()))
}

fn bound_expression(component: &ErrorComponent) -> Value {
    component
        .bound
        .symbolic_expression
        .clone()
        .or_else(|| component.bound.expression.clone())
        .unwrap_or(Value::Null)
}

fn obligation(kind: &str, description: &str, operation: &str) -> ProofObligation {
    let cause = format!("composition:{operation}:{kind}");
    ProofObligation {
        obligation_id: stable_id("obligation", &Value::String(cause.clone())),
        kind: kind.into(),
        description: description.into(),
        status: unresolved(),
        component_id: None,
        required_evidence: vec![kind.into()],
        origin_id: Some(operation.into()),
        semantic_cause_id: Some(cause),
        source_component: None,
    }
}

fn proof_status(
    known: &[ErrorComponent],
    unresolved: &[ErrorComponent],
    assumptions: &[String],
    theorem: Option<&str>,
    kernel_checked: bool,
) -> String {
    if !unresolved.is_empty() && !known.is_empty() {
        return "COMPOSITION_PARTIALLY_RESOLVED".into();
    }
    if !unresolved.is_empty() || known.is_empty() {
        return "COMPOSITION_UNRESOLVED".into();
    }
    let formal = known.iter().all(|item| {
        matches!(
            item.bound.status.as_str(),
            "EXACT_ZERO_BOUND"
                | "KERNEL_VERIFIED_BOUND"
                | "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS"
        )
    });
    let conditional = !assumptions.is_empty()
        || known
            .iter()
            .any(|item| item.bound.status == "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS");
    if formal && theorem.is_some() && kernel_checked {
        if conditional {
            "COMPOSITION_KERNEL_VERIFIED_UNDER_ASSUMPTIONS".into()
        } else {
            "COMPOSITION_KERNEL_VERIFIED".into()
        }
    } else {
        "COMPOSITION_SYMBOLICALLY_DERIVED".into()
    }
}

fn validate_operation(operation: &str) -> Result<()> {
    const OPS: &[&str] = &[
        "SUM",
        "MAX",
        "NORM",
        "SCALAR_MULTIPLICATION",
        "PRODUCT_PROPAGATION",
        "QUOTIENT_PROPAGATION",
        "POWER_PROPAGATION",
        "FUNCTION_PROPAGATION",
        "LINEAR_MAP_PROPAGATION",
        "REDUCTION_PROPAGATION",
        "CUSTOM",
        "UNRESOLVED",
        "RSS",
    ];
    OPS.contains(&operation)
        .then_some(())
        .ok_or_else(|| invalid(format!("UNKNOWN_ERROR_COMPOSITION: {operation}")))
}

/// Compose error components without assuming independence, finite sensitivity,
/// or a denominator separation that is not explicitly evidenced.
pub fn compose_error_components(mut request: CompositionRequest) -> Result<CompositionResult> {
    validate_operation(&request.operation)?;
    if request.operation == "RSS" && !request.independence_proven {
        return Err(invalid("RSS_REQUIRES_PROVEN_INDEPENDENCE"));
    }
    for component in &mut request.components {
        component.bound = component.bound.clone().normalize();
    }
    let output_metric = if request.operation == "NORM" {
        request
            .output_metric
            .clone()
            .unwrap_or_else(|| "ABSOLUTE".into())
    } else {
        metric(&request.components, request.output_metric.as_deref())?
    };
    let known_components = request
        .components
        .iter()
        .filter(|item| known(item))
        .cloned()
        .collect::<Vec<_>>();
    let unresolved_components = request
        .components
        .iter()
        .filter(|item| !known(item))
        .cloned()
        .collect::<Vec<_>>();
    let coefficients = request
        .coefficients
        .clone()
        .unwrap_or_else(|| vec![json!(1); request.components.len()]);
    if coefficients.len() != request.components.len()
        || coefficients.iter().any(|value| numeric(value).is_none())
    {
        return Err(invalid("INVALID_PROPAGATION_COEFFICIENT"));
    }
    if request
        .expected_coefficients
        .as_ref()
        .is_some_and(|value| value != &coefficients)
    {
        return Err(invalid("WRONG_PROPAGATION_COEFFICIENT"));
    }
    let mut dependency = request.dependence.clone();
    if request
        .components
        .iter()
        .map(|item| &item.semantic_cause_id)
        .collect::<BTreeSet<_>>()
        .len()
        < request.components.len()
    {
        dependency = "SHARED_ERROR_CAUSE".into();
    }

    if request
        .components
        .iter()
        .any(|item| item.source == "OVERFLOW_ERROR" && !known(item))
    {
        let finite = known_components
            .iter()
            .map(bound_expression)
            .collect::<Vec<_>>();
        let expression = (!finite.is_empty()).then(|| add(finite));
        let bound = ErrorBound {
            status: if expression.is_some() {
                "SYMBOLIC_BOUND"
            } else {
                "BOUND_UNRESOLVED"
            }
            .into(),
            metric: output_metric.clone(),
            expression,
            exact_value: None,
            theorem_reference: None,
            assumptions: vec![],
            bound_id: String::new(),
            lower_bound: None,
            upper_bound: None,
            symmetric_bound: None,
            symbolic_expression: None,
            parameters: json!({}),
            domain: None,
            proof_evidence: json!({"scope":"KNOWN_COMPONENTS_ONLY","overflow_excluded":false}),
        }
        .normalize();
        let composition = make_composition(
            &request,
            "FINITE_ERROR_ENCLOSURE_INVALIDATED",
            "COMPOSITION_INVALID",
            &output_metric,
            &bound,
            &dependency,
            None,
        );
        let trace = make_trace(
            &request.components,
            &coefficients,
            &request.operation,
            "FINITE_ERROR_ENCLOSURE_INVALIDATED",
            &bound,
            None,
            &[],
        );
        return Ok(CompositionResult {
            composition,
            known_bound: bound,
            total_status: "FINITE_ERROR_ENCLOSURE_INVALIDATED".into(),
            obligations: vec![obligation(
                "OVERFLOW_EXCLUSION_REQUIRED",
                "Potential overflow invalidates a finite enclosure",
                &request.operation,
            )],
            propagation_trace: trace,
            invalidated: true,
        });
    }

    let mut obligations = Vec::new();
    let mut theorem: Option<&str> = None;
    let mut rule = request.operation.clone();
    let mut expression: Option<Value> = None;
    match request.operation.as_str() {
        "SUM" => {
            theorem = Some("CppAudit.ErrorComposition.add_error_bound");
            if coefficients == vec![json!(1), json!(-1)] {
                theorem = Some("CppAudit.ErrorComposition.sub_error_bound");
                rule = "SUB".into();
            }
            let mut groups: BTreeMap<String, Vec<(&ErrorComponent, f64)>> = BTreeMap::new();
            for (component, coefficient) in request.components.iter().zip(&coefficients) {
                groups
                    .entry(component.semantic_cause_id.clone())
                    .or_default()
                    .push((component, numeric(coefficient).unwrap()));
            }
            let mut terms = Vec::new();
            let mut cancelled = false;
            for occurrences in groups.values() {
                let occurrences = occurrences
                    .iter()
                    .filter(|(item, _)| known(item))
                    .collect::<Vec<_>>();
                if occurrences.is_empty() {
                    continue;
                }
                let signed = occurrences.iter().map(|(_, value)| *value).sum::<f64>();
                if request.allow_exact_cancellation && signed == 0.0 && occurrences.len() > 1 {
                    cancelled = true;
                    continue;
                }
                let magnitude = if occurrences.len() > 1 && !request.allow_exact_cancellation {
                    occurrences.iter().map(|(_, value)| value.abs()).sum()
                } else if occurrences.len() > 1 {
                    signed.abs()
                } else {
                    occurrences[0].1.abs()
                };
                terms.push(mul(number(magnitude), bound_expression(occurrences[0].0)));
            }
            expression = Some(add(terms));
            if cancelled {
                rule = "SAFE_EXACT_CANCELLATION".into();
                theorem = Some("CppAudit.ErrorComposition.safe_exact_cancellation");
            }
        }
        "RSS" => {
            // RSS is statistical, exact only under the explicitly proven independence contract.
            let squares: Vec<Value> = known_components
                .iter()
                .map(|item| power(bound_expression(item), 2))
                .collect();
            expression = Some(json!({"op":"RootSumSquares","args":squares}));
            rule = "RSS_UNDER_PROVEN_INDEPENDENCE".into();
            request.assumptions.push("INPUTS_INDEPENDENT".into());
        }
        "MAX" => {
            if !known_components.is_empty() {
                expression = Some(
                    json!({"op":"MaxBounds","args":known_components.iter().map(bound_expression).collect::<Vec<_>>() }),
                );
            }
            rule = "CONSERVATIVE_MAXIMUM".into();
        }
        "SCALAR_MULTIPLICATION" => {
            if request.components.len() != 1 {
                return Err(invalid("SCALAR_PROPAGATION_REQUIRES_ONE_INPUT"));
            }
            if known(&request.components[0]) {
                expression = Some(mul(
                    number(numeric(&coefficients[0]).unwrap().abs()),
                    bound_expression(&request.components[0]),
                ));
            }
            theorem = Some("CppAudit.ErrorComposition.scale_error_bound");
            rule = "EXACT_SCALAR_MULTIPLICATION".into();
        }
        "PRODUCT_PROPAGATION" => {
            theorem = Some("CppAudit.ErrorComposition.mul_error_bound");
            if request.components.len() != 2 {
                return Err(invalid("PRODUCT_PROPAGATION_REQUIRES_TWO_INPUTS"));
            }
            if !(request.value_bounds.contains_key("x_abs")
                && request.value_bounds.contains_key("y_abs"))
            {
                obligations.push(obligation(
                    "INPUT_RANGE_REQUIRED",
                    "Product propagation requires |x| and |y| bounds",
                    &request.operation,
                ));
                rule = "PRODUCT_BOUND_UNRESOLVED".into();
            } else if known_components.len() == 2 {
                let bx = bound_expression(&request.components[0]);
                let by = bound_expression(&request.components[1]);
                expression = Some(add(vec![
                    mul(request.value_bounds["y_abs"].clone(), bx.clone()),
                    mul(request.value_bounds["x_abs"].clone(), by.clone()),
                    mul(bx, by),
                ]));
                request
                    .assumptions
                    .push("NOMINAL_INPUT_RANGES_BOUND".into());
            }
        }
        "QUOTIENT_PROPAGATION" => {
            if request.components.len() != 2 {
                return Err(invalid("QUOTIENT_PROPAGATION_REQUIRES_TWO_INPUTS"));
            }
            let denominator_error = request.components[1]
                .bound
                .exact_value
                .as_ref()
                .and_then(numeric);
            match request.denominator_lower_bound {
                None => {
                    obligations.push(obligation(
                        "DENOMINATOR_LOWER_BOUND_REQUIRED",
                        "A positive lower bound on |y| is required",
                        &request.operation,
                    ));
                    rule = "QUOTIENT_BOUND_UNRESOLVED".into();
                }
                Some(lower)
                    if lower <= 0.0 || denominator_error.is_some_and(|error| lower <= error) =>
                {
                    obligations.push(obligation(
                        "DENOMINATOR_MAY_CROSS_ZERO",
                        "The perturbed denominator may cross zero",
                        &request.operation,
                    ));
                    rule = "QUOTIENT_BOUND_UNRESOLVED".into();
                }
                Some(lower)
                    if known_components.len() == 2
                        && request.value_bounds.contains_key("x_abs")
                        && request.value_bounds.contains_key("y_abs") =>
                {
                    let bx = bound_expression(&request.components[0]);
                    let by = bound_expression(&request.components[1]);
                    let numerator = add(vec![
                        mul(request.value_bounds["y_abs"].clone(), bx),
                        mul(request.value_bounds["x_abs"].clone(), by.clone()),
                    ]);
                    expression = Some(divide(
                        numerator,
                        mul(
                            number(lower),
                            add(vec![number(lower), mul(number(-1.0), by)]),
                        ),
                    )?);
                    request
                        .assumptions
                        .push("DENOMINATOR_SEPARATED_FROM_ZERO".into());
                }
                Some(_) => {
                    obligations.push(obligation(
                        "INPUT_RANGE_REQUIRED",
                        "Quotient propagation requires numerator and denominator ranges",
                        &request.operation,
                    ));
                    rule = "QUOTIENT_BOUND_UNRESOLVED".into();
                }
            }
        }
        "POWER_PROPAGATION" => match request.exponent {
            None => obligations.push(obligation(
                "INTEGER_EXPONENT_REQUIRED",
                "Only integer powers are supported",
                &request.operation,
            )),
            Some(_)
                if request.components.len() != 1 || !request.value_bounds.contains_key("x_abs") =>
            {
                obligations.push(obligation(
                    "INPUT_RANGE_REQUIRED",
                    "Power propagation requires an input range",
                    &request.operation,
                ))
            }
            Some(exponent) if !known_components.is_empty() => {
                let bx = bound_expression(&known_components[0]);
                let expanded = add(vec![request.value_bounds["x_abs"].clone(), bx.clone()]);
                expression = Some(mul(
                    number((exponent as f64).abs()),
                    mul(
                        power(expanded, exponent.unsigned_abs().saturating_sub(1) as i64),
                        bx,
                    ),
                ));
                request
                    .assumptions
                    .push("INTEGER_POWER_DOMAIN_RESOLVED".into());
            }
            _ => {}
        },
        "FUNCTION_PROPAGATION" => match request.sensitivity.as_ref() {
            None => obligations.push(obligation(
                "FUNCTION_SENSITIVITY_UNRESOLVED",
                "A derivative or Lipschitz bound is required",
                &request.operation,
            )),
            Some(value) if value.metric != output_metric => {
                return Err(invalid("INCOMPATIBLE_ERROR_METRICS"))
            }
            Some(value) if known_components.len() == 1 => {
                expression = Some(mul(
                    value.lipschitz_bound.clone(),
                    bound_expression(&known_components[0]),
                ));
                request.assumptions.extend(value.assumptions.clone());
                theorem = value.theorem_reference.as_deref();
                rule = "LIPSCHITZ_FUNCTION_PROPAGATION".into();
            }
            _ => {}
        },
        "LINEAR_MAP_PROPAGATION" => match request.operator_norm.clone() {
            None => obligations.push(obligation(
                "OPERATOR_NORM_REQUIRED",
                "Linear-map propagation requires a compatible operator norm",
                &request.operation,
            )),
            Some(_) if !matches!(output_metric.as_str(), "COMPONENTWISE" | "L1" | "LINF") => {
                return Err(invalid("LINEAR_MAP_METRIC_UNSUPPORTED"))
            }
            Some(norm) if known_components.len() == 1 => {
                expression = Some(mul(norm, bound_expression(&known_components[0])));
                theorem = Some("CppAudit.ErrorComposition.linear_map_error_bound");
                request
                    .assumptions
                    .push("COMPATIBLE_OPERATOR_NORM_BOUND".into());
            }
            _ => {}
        },
        "REDUCTION_PROPAGATION" => {
            theorem = Some("CppAudit.ErrorComposition.sum_error_bound");
            expression = Some(add(known_components
                .iter()
                .map(bound_expression)
                .collect::<Vec<_>>()));
            if let Some(count) = request.count {
                if count <= 0 {
                    obligations.push(obligation(
                        "POSITIVE_REDUCTION_COUNT_REQUIRED",
                        "Mean requires n > 0",
                        &request.operation,
                    ));
                    expression = None;
                } else {
                    expression = Some(divide(expression.take().unwrap(), number(count as f64))?);
                    theorem = Some("CppAudit.ErrorComposition.mean_error_bound");
                    request.assumptions.push("0 < n".into());
                }
            }
        }
        "NORM" => {
            let input_metrics = request
                .components
                .iter()
                .map(|item| item.metric.as_str())
                .collect::<BTreeSet<_>>();
            if output_metric == "L1" && input_metrics == BTreeSet::from(["LINF"]) {
                match request.dimension {
                    None => obligations.push(obligation(
                        "NORM_DIMENSION_REQUIRED",
                        "Linf to L1 conversion requires vector length",
                        &request.operation,
                    )),
                    Some(value) if value < 0 => return Err(invalid("INVALID_NORM_DIMENSION")),
                    Some(value) if request.vector_length.is_some_and(|length| length != value) => {
                        return Err(invalid("WRONG_NORM_FACTOR"))
                    }
                    Some(value) => {
                        expression = request
                            .components
                            .first()
                            .map(|item| mul(number(value as f64), bound_expression(item)));
                        theorem = Some("CppAudit.ErrorComposition.linf_to_l1_bound");
                        request.assumptions.push("VECTOR_DIMENSION_RESOLVED".into());
                    }
                }
            } else if output_metric == "L1" && input_metrics == BTreeSet::from(["L1"]) {
                expression = Some(add(known_components
                    .iter()
                    .map(bound_expression)
                    .collect::<Vec<_>>()));
            } else {
                obligations.push(obligation(
                    "NORM_CONVERSION_UNRESOLVED",
                    "No verified conversion exists for these metrics",
                    &request.operation,
                ));
            }
        }
        _ => obligations.push(obligation(
            "CUSTOM_COMPOSITION_CONTRACT_REQUIRED",
            "Custom propagation needs a formal contract",
            &request.operation,
        )),
    }

    let unresolved_by_rule = !obligations.is_empty() || expression.is_none();
    let effective_unresolved = if unresolved_by_rule {
        request.components.clone()
    } else {
        unresolved_components
    };
    let status = proof_status(
        &known_components,
        &effective_unresolved,
        &request.assumptions,
        theorem,
        request.kernel_checked,
    );
    let bound_status = match status.as_str() {
        "COMPOSITION_KERNEL_VERIFIED_UNDER_ASSUMPTIONS" => {
            "KERNEL_VERIFIED_BOUND_UNDER_ASSUMPTIONS"
        }
        "COMPOSITION_KERNEL_VERIFIED" => "KERNEL_VERIFIED_BOUND",
        _ if expression.is_some() => "SYMBOLIC_BOUND",
        _ => "BOUND_UNRESOLVED",
    };
    let bound = ErrorBound {
        status: bound_status.into(),
        metric: output_metric.clone(),
        expression: expression.clone(),
        exact_value: None,
        theorem_reference: theorem.map(str::to_owned),
        assumptions: request.assumptions.clone(),
        bound_id: String::new(),
        lower_bound: None,
        upper_bound: None,
        symmetric_bound: None,
        symbolic_expression: None,
        parameters: json!({}),
        domain: None,
        proof_evidence: json!({"composition_status":status}),
    }
    .normalize();
    let total_status = if !effective_unresolved.is_empty() || !obligations.is_empty() {
        "TOTAL_ERROR_BOUND_UNRESOLVED"
    } else {
        "TOTAL_ERROR_BOUND_VERIFIED"
    }
    .into();
    let composition = make_composition(
        &request,
        &rule,
        &status,
        &output_metric,
        &bound,
        &dependency,
        theorem,
    );
    let trace = make_trace(
        &request.components,
        &coefficients,
        &request.operation,
        &rule,
        &bound,
        theorem,
        &request.assumptions,
    );
    Ok(CompositionResult {
        composition,
        known_bound: bound,
        total_status,
        obligations,
        propagation_trace: trace,
        invalidated: false,
    })
}

fn make_composition(
    request: &CompositionRequest,
    rule: &str,
    status: &str,
    metric: &str,
    bound: &ErrorBound,
    dependency: &str,
    theorem: Option<&str>,
) -> ErrorComposition {
    let ids = request
        .components
        .iter()
        .map(|item| item.component_id.clone())
        .collect::<Vec<_>>();
    ErrorComposition {
        rule: rule.into(),
        status: status.into(),
        component_ids: ids.clone(),
        cancellation_assumed: false,
        kind: request.operation.clone(),
        composition_id: stable_id("composition", &json!([request.operation, ids, rule])),
        operation: request.operation.clone(),
        input_components: ids,
        input_bounds: request
            .components
            .iter()
            .map(|item| item.bound.clone())
            .collect(),
        output_metric: Some(metric.into()),
        output_bound: Some(bound.clone()),
        assumptions: request.assumptions.clone(),
        proof_rule: Some(rule.into()),
        proof_evidence: json!({"lean_theorem":theorem,"kernel_applicable":status.starts_with("COMPOSITION_KERNEL_VERIFIED")}),
        provenance: json!({"phase":9,"numeric_samples_used_as_proof":false}),
        dependency_status: dependency.into(),
    }
}

fn make_trace(
    components: &[ErrorComponent],
    coefficients: &[Value],
    operation: &str,
    rule: &str,
    bound: &ErrorBound,
    theorem: Option<&str>,
    assumptions: &[String],
) -> Vec<Value> {
    components
        .iter()
        .zip(coefficients)
        .map(|(item, coefficient)| {
            json!({
                "source_component":item.component_id,"semantic_cause_id":item.semantic_cause_id,
                "source_bound":item.bound,"operation":operation,"propagation_rule":rule,
                "coefficient":coefficient,"result_bound":bound,"lean_theorem":theorem,
                "assumptions":assumptions,"source_kind":"LOCAL_ERROR","kind":"PROPAGATED_ERROR"
            })
        })
        .collect()
}

pub fn evaluate_error_budget(
    bound: &ErrorBound,
    total_status: &str,
    tolerance: Option<f64>,
) -> Value {
    let numeric_bound = bound
        .exact_value
        .as_ref()
        .and_then(numeric)
        .or_else(|| bound.expression.as_ref().and_then(numeric));
    let known_status = match (tolerance, numeric_bound) {
        (Some(tolerance), Some(value)) if value <= tolerance => "KNOWN_BOUND_WITHIN_TOLERANCE",
        (Some(_), Some(_)) => "KNOWN_BOUND_EXCEEDS_TOLERANCE",
        _ => "TOLERANCE_NOT_SPECIFIED",
    };
    let total = if total_status == "TOTAL_ERROR_BOUND_VERIFIED"
        && known_status == "KNOWN_BOUND_WITHIN_TOLERANCE"
    {
        "TOTAL_TOLERANCE_PROVEN"
    } else {
        "TOTAL_TOLERANCE_NOT_PROVEN"
    };
    json!({"known_bound":bound.expression,"absolute_tolerance":tolerance,
        "known_bound_status":known_status,"total_tolerance_status":total})
}

struct GraphState<'a> {
    request: &'a GraphPropagationRequest,
    nodes: Vec<PropagationNode>,
    edges: Vec<Value>,
    obligations: Vec<ProofObligation>,
    trace: Vec<Value>,
}

fn path_key(path: &[String]) -> String {
    if path.is_empty() {
        "/".into()
    } else {
        format!("/{}", path.join("/"))
    }
}

fn constant_value(node: &Value) -> Option<f64> {
    (node.get("op").and_then(Value::as_str) == Some("Constant"))
        .then(|| node.get("value").and_then(Value::as_f64))
        .flatten()
}

fn derived_component(
    result: &CompositionResult,
    inputs: &[ErrorComponent],
    node_id: &str,
) -> ErrorComponent {
    let causes = inputs
        .iter()
        .map(|item| item.semantic_cause_id.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let sources = inputs
        .iter()
        .map(|item| item.source.clone())
        .collect::<BTreeSet<_>>();
    let source = if sources.len() == 1 {
        sources.into_iter().next().unwrap()
    } else {
        "UNKNOWN_ERROR_SOURCE".into()
    };
    let cause = if causes.len() == 1 {
        causes[0].clone()
    } else {
        stable_id("composed-cause", &json!(causes))
    };
    ErrorComponent {
        component_id: format!("propagated-{node_id}"),
        source,
        expression: json!({"op":"PropagatedError","composition_id":result.composition.composition_id}),
        metric: result.known_bound.metric.clone(),
        bound: result.known_bound.clone(),
        proof_status: result.composition.status.clone(),
        provenance: json!({"phase":9,"error_role":"PROPAGATED_ERROR","composition_id":result.composition.composition_id}),
        origin_id: if inputs.len() == 1 {
            inputs[0].origin_id.clone()
        } else {
            result.composition.composition_id.clone()
        },
        semantic_cause_id: cause,
        assumptions: result.composition.assumptions.clone(),
        dependencies: causes,
    }
}

impl GraphState<'_> {
    fn walk(&mut self, node: &Value, path: &mut Vec<String>) -> Result<Vec<ErrorComponent>> {
        let key = path_key(path);
        if let Some(direct) = self
            .request
            .local_components
            .get(&key)
            .filter(|items| !items.is_empty())
        {
            let direct = direct.clone();
            self.nodes.push(PropagationNode {
                node_id: key,
                operation: "LOCAL_ERROR".into(),
                input_bounds: vec![],
                local_error: direct
                    .iter()
                    .map(|item| item.component_id.clone())
                    .collect(),
                propagated_error: vec![],
                output_bound: (direct.len() == 1).then(|| direct[0].bound.clone()),
                proof_rule: None,
                status: "LOCAL_BOUND_ATTACHED".into(),
                semantic_causes: direct
                    .iter()
                    .map(|item| item.semantic_cause_id.clone())
                    .collect(),
                dependency_status: "DEPENDENCE_UNKNOWN".into(),
            });
            return Ok(direct);
        }
        let Some(object) = node.as_object() else {
            return Ok(vec![]);
        };
        let op = object
            .get("op")
            .and_then(Value::as_str)
            .unwrap_or("UNRESOLVED");
        let args = object
            .get("args")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let mut child_groups = Vec::new();
        for (index, child) in args.iter().enumerate() {
            path.extend(["args".into(), index.to_string()]);
            child_groups.push(self.walk(child, path)?);
            path.truncate(path.len() - 2);
        }
        if op == "Reduce" {
            if let Some(input) = object.get("input") {
                path.push("input".into());
                child_groups.push(self.walk(input, path)?);
                path.pop();
            }
        }
        let flat = child_groups.iter().flatten().cloned().collect::<Vec<_>>();
        if flat.is_empty() {
            return Ok(vec![]);
        }
        let contract = self.request.contracts.get(&key).and_then(Value::as_object);
        let mut composition_request = CompositionRequest {
            components: flat.clone(),
            kernel_checked: self.request.kernel_checked,
            ..Default::default()
        };
        let mut coefficients = vec![json!(1); flat.len()];
        match op {
            "Subtract" if child_groups.len() >= 2 => {
                coefficients = child_groups[0]
                    .iter()
                    .map(|_| json!(1))
                    .chain(child_groups[1].iter().map(|_| json!(-1)))
                    .collect();
            }
            "Multiply" if args.len() == 2 => {
                let left = constant_value(&args[0]);
                let right = constant_value(&args[1]);
                if let Some(left) =
                    left.filter(|_| !child_groups[1].is_empty() && child_groups[0].is_empty())
                {
                    composition_request.operation = "SCALAR_MULTIPLICATION".into();
                    coefficients = vec![number(left); flat.len()];
                } else if let Some(right) =
                    right.filter(|_| !child_groups[0].is_empty() && child_groups[1].is_empty())
                {
                    composition_request.operation = "SCALAR_MULTIPLICATION".into();
                    coefficients = vec![number(right); flat.len()];
                } else {
                    composition_request.operation = "PRODUCT_PROPAGATION".into();
                    composition_request.value_bounds = contract
                        .and_then(|v| v.get("value_bounds"))
                        .cloned()
                        .and_then(|v| serde_json::from_value(v).ok())
                        .unwrap_or_default();
                }
            }
            "Divide" if args.len() == 2 => {
                let denominator = constant_value(&args[1]);
                if denominator.is_some_and(|v| v != 0.0)
                    && !child_groups[0].is_empty()
                    && child_groups[1].is_empty()
                {
                    composition_request.operation = "SCALAR_MULTIPLICATION".into();
                    coefficients = vec![number(1.0 / denominator.unwrap()); flat.len()];
                } else {
                    composition_request.operation = "QUOTIENT_PROPAGATION".into();
                    composition_request.value_bounds = contract
                        .and_then(|v| v.get("value_bounds"))
                        .cloned()
                        .and_then(|v| serde_json::from_value(v).ok())
                        .unwrap_or_default();
                    composition_request.denominator_lower_bound = contract
                        .and_then(|v| v.get("denominator_lower_bound"))
                        .and_then(Value::as_f64);
                }
            }
            "Power" if args.len() == 2 => {
                composition_request.operation = "POWER_PROPAGATION".into();
                composition_request.exponent = constant_value(&args[1])
                    .filter(|v| v.fract() == 0.0)
                    .map(|v| v as i64);
                composition_request.value_bounds = contract
                    .and_then(|v| v.get("value_bounds"))
                    .cloned()
                    .and_then(|v| serde_json::from_value(v).ok())
                    .unwrap_or_default();
            }
            "FiniteSum" | "TransformReduce" | "Reduce" => {
                composition_request.operation = "REDUCTION_PROPAGATION".into();
                if object.get("reduction").and_then(Value::as_str) == Some("Mean")
                    || object.get("normalization").and_then(Value::as_str)
                        == Some("arithmetic_mean")
                {
                    composition_request.count = contract
                        .and_then(|v| v.get("count"))
                        .and_then(Value::as_i64);
                }
            }
            "FunctionCall" | "OpaqueNumericCall" => {
                composition_request.operation = "FUNCTION_PROPAGATION".into();
                composition_request.sensitivity = contract
                    .and_then(|v| v.get("function_sensitivity"))
                    .cloned()
                    .and_then(|v| serde_json::from_value(v).ok());
            }
            _ => {}
        }
        composition_request.coefficients = Some(coefficients);
        composition_request.allow_exact_cancellation = contract
            .and_then(|v| v.get("allow_exact_cancellation"))
            .and_then(Value::as_bool)
            .unwrap_or(false);
        composition_request.expected_coefficients = contract
            .and_then(|v| v.get("expected_coefficients"))
            .cloned()
            .and_then(|v| serde_json::from_value(v).ok());
        let result = match compose_error_components(composition_request) {
            Ok(result) => result,
            Err(error) => {
                self.obligations.push(obligation(
                    "GRAPH_PROPAGATION_UNRESOLVED",
                    &error.to_string(),
                    op,
                ));
                compose_error_components(CompositionRequest {
                    components: flat.clone(),
                    operation: "UNRESOLVED".into(),
                    kernel_checked: self.request.kernel_checked,
                    ..Default::default()
                })?
            }
        };
        self.obligations.extend(result.obligations.clone());
        self.trace.extend(result.propagation_trace.clone());
        let node_id = stable_id("graph-node", &json!([key, op]));
        let derived = derived_component(&result, &flat, &node_id);
        for item in &flat {
            self.edges
                .push(json!({"source":item.component_id,"target":node_id}));
        }
        self.nodes.push(PropagationNode {
            node_id: node_id.clone(),
            operation: op.into(),
            input_bounds: flat
                .iter()
                .map(|item| item.bound.bound_id.clone())
                .collect(),
            local_error: vec![],
            propagated_error: vec![derived.component_id.clone()],
            output_bound: Some(result.known_bound.clone()),
            proof_rule: result.composition.proof_rule.clone(),
            status: result.composition.status.clone(),
            semantic_causes: flat
                .iter()
                .map(|item| item.semantic_cause_id.clone())
                .collect(),
            dependency_status: result.composition.dependency_status.clone(),
        });
        Ok(vec![derived])
    }
}

pub fn propagate_expression_graph(
    request: GraphPropagationRequest,
) -> Result<GraphPropagationResult> {
    let mut state = GraphState {
        request: &request,
        nodes: vec![],
        edges: vec![],
        obligations: vec![],
        trace: vec![],
    };
    let outputs = state.walk(&request.expression, &mut vec![])?;
    let final_result = compose_error_components(CompositionRequest {
        components: outputs.clone(),
        operation: "SUM".into(),
        kernel_checked: request.kernel_checked,
        ..Default::default()
    })?;
    state.trace.extend(final_result.propagation_trace.clone());
    state.obligations.extend(final_result.obligations.clone());
    for item in &outputs {
        state
            .edges
            .push(json!({"source":item.component_id,"target":request.output}));
    }
    Ok(GraphPropagationResult {
        nodes: state.nodes,
        edges: state.edges,
        output_components: outputs,
        output_composition: final_result,
        obligations: state.obligations,
        propagation_trace: state.trace,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn component(id: &str, value: f64) -> ErrorComponent {
        ErrorComponent {
            component_id: id.into(),
            source: "INPUT_UNCERTAINTY".into(),
            expression: constant(value),
            metric: "ABSOLUTE".into(),
            bound: ErrorBound {
                status: "SYMBOLIC_BOUND".into(),
                metric: "ABSOLUTE".into(),
                expression: Some(constant(value)),
                exact_value: Some(number(value)),
                theorem_reference: None,
                assumptions: vec![],
                bound_id: String::new(),
                lower_bound: None,
                upper_bound: None,
                symmetric_bound: None,
                symbolic_expression: None,
                parameters: json!({}),
                domain: None,
                proof_evidence: json!({}),
            },
            proof_status: "FORMALLY_DERIVED".into(),
            provenance: json!({}),
            origin_id: id.into(),
            semantic_cause_id: id.into(),
            assumptions: vec![],
            dependencies: vec![],
        }
    }

    #[test]
    fn unknown_dependency_never_enables_rss() {
        let request = CompositionRequest {
            components: vec![component("a", 1.0)],
            operation: "RSS".into(),
            ..Default::default()
        };
        assert!(compose_error_components(request)
            .unwrap_err()
            .to_string()
            .contains("RSS_REQUIRES_PROVEN_INDEPENDENCE"));
    }

    #[test]
    fn quotient_crossing_zero_stays_unresolved() {
        let request = CompositionRequest {
            components: vec![component("x", 1.0), component("y", 1.0)],
            operation: "QUOTIENT_PROPAGATION".into(),
            denominator_lower_bound: Some(1.0),
            value_bounds: BTreeMap::from([("x_abs".into(), json!(2)), ("y_abs".into(), json!(2))]),
            ..Default::default()
        };
        let result = compose_error_components(request).unwrap();
        assert_eq!(result.total_status, "TOTAL_ERROR_BOUND_UNRESOLVED");
        assert_eq!(result.obligations[0].kind, "DENOMINATOR_MAY_CROSS_ZERO");
    }
}
