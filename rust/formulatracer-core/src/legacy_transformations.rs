//! Authorized transformation search. Approximation relations never become equality.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
fn invalid(m: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(m.into())
}
fn stable_id(prefix: &str, v: &Value) -> String {
    let text = serde_json::to_string(v).unwrap_or_default();
    let hash = format!("{:x}", Sha256::digest(text.as_bytes()));
    format!("{prefix}-{}", &hash[..16])
}
fn contains_op(v: &Value, op: &str) -> bool {
    match v {
        Value::Array(a) => a.iter().any(|x| contains_op(x, op)),
        Value::Object(m) => {
            m.get("op").and_then(Value::as_str) == Some(op)
                || m.values().any(|x| contains_op(x, op))
        }
        _ => false,
    }
}
fn contains_derivative(v: &Value, order: &Value) -> bool {
    match v {
        Value::Array(a) => a.iter().any(|x| contains_derivative(x, order)),
        Value::Object(m) => {
            (m.get("op").and_then(Value::as_str) == Some("Derivative")
                && m.get("order") == Some(order))
                || m.values().any(|x| contains_derivative(x, order))
        }
        _ => false,
    }
}
fn rename_bound(v: &Value, old: &str, new: &str) -> Value {
    match v {
        Value::Array(a) => Value::Array(a.iter().map(|x| rename_bound(x, old, new)).collect()),
        Value::Object(m) => {
            let mut o = m
                .iter()
                .map(|(k, x)| (k.clone(), rename_bound(x, old, new)))
                .collect::<serde_json::Map<_, _>>();
            if o.get("op").and_then(Value::as_str) == Some("BoundVariable")
                && o.get("name").and_then(Value::as_str) == Some(old)
            {
                o.insert("name".into(), json!(new));
            }
            Value::Object(o)
        }
        _ => v.clone(),
    }
}
fn apply_exact_node(v: &Value, rule: &str, depth: usize) -> Value {
    match v {
        Value::Array(a) => {
            Value::Array(a.iter().map(|x| apply_exact_node(x, rule, depth)).collect())
        }
        Value::Object(m) => {
            let mut current = Value::Object(m.clone());
            let mut next_depth = depth;
            if rule == "alpha_rename"
                && matches!(
                    current.get("op").and_then(Value::as_str),
                    Some("FiniteSum" | "TransformReduce" | "FoldLeft" | "Map" | "Scan")
                )
            {
                if let Some(old) = current.get("bound_index").and_then(Value::as_str) {
                    let new = format!("_i{depth}");
                    current = rename_bound(&current, old, &new);
                    current["bound_index"] = json!(new);
                    next_depth += 1;
                }
            }
            let mut o = current
                .as_object()
                .unwrap()
                .iter()
                .filter(|(k, _)| {
                    !["original_index", "source_node_ids", "source_spans"].contains(&k.as_str())
                })
                .map(|(k, x)| (k.clone(), apply_exact_node(x, rule, next_depth)))
                .collect::<serde_json::Map<_, _>>();
            if rule == "finite_sum_normalization"
                && o.get("op").and_then(Value::as_str) == Some("TransformReduce")
                && o.get("reduction").and_then(Value::as_str) == Some("Add")
            {
                let finite = json!({"op":"FiniteSum","bound_index":o["bound_index"],"index_domain":o["index_domain"],"body":o["transform"],"reduction_order":o.get("reduction_order").cloned().unwrap_or(json!("left_to_right"))});
                let initial = o.get("initial_value").cloned().unwrap_or(Value::Null);
                return if initial == json!({"op":"Constant","value":0})
                    || initial == json!({"op":"Constant","value":0.0})
                {
                    finite
                } else {
                    json!({"op":"Add","args":[initial,finite]})
                };
            }
            if rule == "neutral_element_elimination"
                && matches!(
                    o.get("op").and_then(Value::as_str),
                    Some("Add" | "Multiply")
                )
            {
                let identity = if o.get("op").and_then(Value::as_str) == Some("Add") {
                    0
                } else {
                    1
                };
                let args = o
                    .get("args")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default()
                    .into_iter()
                    .filter(|x| {
                        *x != json!({"op":"Constant","value":identity})
                            && *x != json!({"op":"Constant","value":identity as f64})
                    })
                    .collect::<Vec<_>>();
                if args.len() == 1 {
                    return args[0].clone();
                }
                o.insert("args".into(), json!(args));
            }
            if rule == "simple_commutative_normalization"
                && matches!(
                    o.get("op").and_then(Value::as_str),
                    Some("Add" | "Multiply")
                )
            {
                if let Some(a) = o.get_mut("args").and_then(Value::as_array_mut) {
                    a.sort_by_key(|x| serde_json::to_string(x).unwrap_or_default())
                }
            }
            Value::Object(o)
        }
        _ => v.clone(),
    }
}
fn hard_constraints(rule: &Value, set: &Value, theory: &Value, context: &Value) -> Value {
    let mut checks = Vec::new();
    let mut failures = Vec::new();
    let hard = set.get("hard_constraints").unwrap_or(&Value::Null);
    let mut check = |name: &str, required: bool, satisfied: bool, detail: String| {
        if required {
            checks.push(json!({"constraint":name,"status":if satisfied{"SATISFIED"}else{"FAILED"},"detail":detail}));
            if !satisfied {
                failures.push(json!(name))
            }
        }
    };
    check(
        "finite_domain_required",
        hard.get("finite_domain_required")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        contains_op(theory, "FiniteSum")
            || context
                .get("finite_domain")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        "finite domain must be explicit".into(),
    );
    if rule.pointer("/source_pattern/op").and_then(Value::as_str) == Some("Derivative") {
        if let Some(order) = rule.pointer("/source_pattern/order") {
            check(
                "required_derivative_order",
                true,
                contains_derivative(
                    theory.pointer("/outputs/0/expression").unwrap_or(theory),
                    order,
                ),
                format!("required order {order}"),
            )
        }
    }
    let required = strings(set.get("required_observables"))
        .into_iter()
        .chain(strings(context.get("required_observables")))
        .collect::<BTreeSet<_>>();
    let supported = strings(rule.get("supported_observables"))
        .into_iter()
        .collect::<BTreeSet<_>>();
    for observable in required {
        check(
            "required_observable",
            true,
            supported.contains(&observable),
            format!("required observable {observable}"),
        );
    }
    for name in [
        "axis_compatibility",
        "shape_compatibility",
        "domain_restriction",
        "nonzero_denominator",
    ] {
        let requirement = rule
            .pointer(&format!("/hard_constraints/{name}"))
            .or_else(|| hard.get(name));
        if let Some(requirement) = requirement {
            check(
                name,
                true,
                context.get(name).and_then(Value::as_bool).unwrap_or(false),
                requirement.to_string(),
            )
        }
    }
    let max = hard
        .get("maximum_selection_error")
        .or_else(|| hard.get("maximum_error"))
        .and_then(Value::as_f64);
    let estimate = rule.get("selection_error_estimate").and_then(Value::as_f64);
    if let (Some(max), Some(estimate)) = (max, estimate) {
        check(
            "maximum_error",
            true,
            estimate <= max,
            format!("unproven selection estimate={estimate}, maximum={max}"),
        )
    }
    let family = rule
        .get("approximation_family_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    if family.contains("difference") {
        check(
            "spacing_resolved",
            true,
            context
                .get("spacing_resolved")
                .and_then(Value::as_bool)
                .unwrap_or(false)
                || context.get("spacing").is_some_and(|v| !v.is_null()),
            "finite-difference spacing must be explicit".into(),
        );
        if family.starts_with("central_difference") {
            check(
                "boundary_stencil",
                true,
                context.get("stencil_region").and_then(Value::as_str) == Some("interior"),
                "central stencil requires an explicitly interior location".into(),
            )
        }
        if (family.starts_with("forward_difference") || family.starts_with("backward_difference"))
            && context
                .get("at_boundary")
                .and_then(Value::as_bool)
                .unwrap_or(false)
        {
            check(
                "boundary_stencil",
                true,
                context
                    .get("boundary_stencil_authorized")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                "one-sided boundary stencil must be authorized".into(),
            )
        }
    }
    if family.ends_with("rule") {
        check(
            "integration_partition",
            true,
            context
                .get("partition_resolved")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            "integration partition and step must be explicit".into(),
        );
        if family == "simpson_rule" {
            check(
                "simpson_even_intervals",
                true,
                context
                    .get("even_interval_count")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                "composite Simpson rule requires an even interval count".into(),
            )
        }
    }
    if family.contains("interpolation") {
        let status = context
            .get("interpolation_domain_status")
            .and_then(Value::as_str);
        check(
            "interpolation_domain",
            true,
            matches!(status, Some("INTERPOLATION" | "EXTRAPOLATION")),
            "query/support domain relation must be known".into(),
        );
        check(
            "not_extrapolation",
            true,
            status != Some("EXTRAPOLATION"),
            "extrapolation is not interpolation".into(),
        )
    }
    json!({"checks":checks,"failures":failures})
}
fn application(
    rule: &Value,
    source: &Value,
    target: &Value,
    checks: &Value,
    assumptions: &Value,
    provenance: &Value,
) -> Value {
    let known = strings(Some(assumptions));
    let mut discharged = Vec::new();
    let mut remaining = Vec::new();
    for (i, s) in strings(rule.get("conditions")).iter().enumerate() {
        let exact = known.contains(s);
        let item = json!({"obligation_id":stable_id("obligation",&json!([rule["id"],i,s])),"statement":s,"kind":"RULE_ASSUMPTION","status":if exact{"DISCHARGED"}else{"REMAINING"},"evidence":if exact{json!("user supplied assumption")}else{Value::Null}});
        if exact {
            discharged.push(item)
        } else {
            remaining.push(item)
        }
    }
    let kind = rule
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("exact")
        .to_uppercase();
    if kind == "APPROXIMATION" && rule.get("error_theorem").is_none_or(Value::is_null) {
        remaining.push(json!({"obligation_id":stable_id("obligation",&json!([rule["id"],"approximation_error"])),"statement":"approximation error bound","kind":"APPROXIMATION_ERROR_BOUND","status":"REMAINING","evidence":null}))
    }
    let status = if kind == "APPROXIMATION"
        && (!remaining.is_empty() || rule.get("error_theorem").is_none_or(Value::is_null))
    {
        "APPROXIMATION_ERROR_NOT_YET_PROVEN"
    } else if !remaining.is_empty() {
        "TRANSFORMATION_OBLIGATION_REMAINING"
    } else if kind == "EXACT_UNDER_ASSUMPTIONS" {
        "EXACT_TRANSFORMATION_VERIFIED_UNDER_ASSUMPTIONS"
    } else {
        "EXACT_TRANSFORMATION_VERIFIED"
    };
    let mut reference = provenance.clone();
    reference["rule_provenance"] = rule.get("provenance").cloned().unwrap_or(Value::Null);
    reference["theorem_reference"] = rule
        .get("theorem_reference")
        .cloned()
        .unwrap_or(Value::Null);
    reference["library_contract"] = rule.get("library_contract").cloned().unwrap_or(Value::Null);
    if let Some(f) = rule.get("approximation_family") {
        reference["approximation_family"] = f.clone();
        reference["convergence_status"] = json!("CONVERGENCE_ORDER_RECORDED");
        reference["convergence_proof_status"] = json!("CONVERGENCE_PROOF_NOT_YET_ESTABLISHED");
        reference["error_proof_status"] = json!("APPROXIMATION_ERROR_NOT_YET_PROVEN");
    }
    if rule["id"] == json!("neutral_element_elimination") {
        reference["theorem_reference"] = json!(if contains_op(source, "Multiply") {
            "CppAudit.Semantics.Transformation.multiply_neutral_sound"
        } else {
            "CppAudit.Semantics.Transformation.add_neutral_sound"
        })
    }
    if rule["id"] == json!("simple_commutative_normalization") && contains_op(source, "Multiply") {
        reference["theorem_reference"] =
            json!("CppAudit.Semantics.Transformation.multiply_commutative_sound")
    }
    let parameter_names = strings(rule.get("parameters"));
    let supplied = provenance.get("parameters").and_then(Value::as_object);
    let parameters = parameter_names
        .into_iter()
        .filter_map(|name| {
            supplied
                .and_then(|m| m.get(&name))
                .cloned()
                .map(|value| (name, value))
        })
        .collect::<serde_json::Map<_, _>>();
    json!({"rule_id":rule["id"],"source_expression_id":source.get("expression_id").and_then(Value::as_str).map(str::to_owned).unwrap_or_else(||stable_id("expression",source.get("outputs").unwrap_or(source))),"target_expression_id":target.get("expression_id").and_then(Value::as_str).map(str::to_owned).unwrap_or_else(||stable_id("expression",target.get("outputs").unwrap_or(target))),"parameters":parameters,"rule_kind":kind,"assumptions":known,"hard_constraints":checks,"discharged_obligations":discharged,"remaining_obligations":remaining,"reference":reference,"authorization_status":"RULE_ALLOWED","status":status})
}

fn finalize(r: &Value) -> Result<Value> {
    let mode = r.get("mode").and_then(Value::as_str).unwrap_or("");
    match mode {
        "EXACT" => Ok(json!({
            "status": if r.get("has_applications").and_then(Value::as_bool).unwrap_or(false) {"TRANSFORMATION_APPLIED"} else {"EXACT_TRANSFORMATION_VERIFIED"},
            "relation":"EXACT_EQUAL", "diagnostics":[]
        })),
        "CONDITIONAL" => Ok(json!({
            "status":r.pointer("/application/status").cloned().unwrap_or(json!("TRANSFORMATION_OBLIGATION_REMAINING")),
            "relation":"EQUIVALENT_UNDER_ASSUMPTIONS", "diagnostics":[]
        })),
        "NO_SELECTION" => {
            let rejected = r
                .get("rejected")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let tied = r.pointer("/selection/status").and_then(Value::as_str)
                == Some("SELECTION_TIE_REQUIRES_USER");
            let not_allowed = rejected
                .iter()
                .any(|x| x.get("status").and_then(Value::as_str) == Some("RULE_NOT_ALLOWED"));
            let status = if tied {
                "TRANSFORMATION_OBLIGATION_REMAINING"
            } else if not_allowed || rejected.is_empty() {
                "TRANSFORMATION_NOT_ALLOWED"
            } else {
                "TRANSFORMATION_CONSTRAINT_FAILED"
            };
            let mapping = [
                ("spacing_resolved", "SPACING_UNRESOLVED"),
                ("boundary_stencil", "BOUNDARY_STENCIL_UNRESOLVED"),
                ("integration_partition", "INTEGRATION_PARTITION_UNRESOLVED"),
                ("interpolation_domain", "INTERPOLATION_DOMAIN_UNRESOLVED"),
                ("not_extrapolation", "EXTRAPOLATION_RECOGNIZED"),
            ];
            let failures = rejected
                .iter()
                .flat_map(|x| strings(x.get("failures")))
                .collect::<BTreeSet<_>>();
            let mut diagnostics = mapping
                .into_iter()
                .filter(|(source, _)| failures.contains(*source))
                .map(|(_, code)| json!({"code":code}))
                .collect::<Vec<_>>();
            diagnostics.push(json!({"code":status,"message":"no allowed feasible transformation reaches implementation"}));
            Ok(
                json!({"status":status,"relation":"NOT_COMPARABLE","diagnostics":diagnostics,"selection_obligation":tied}),
            )
        }
        "APPROXIMATION" => {
            let matched = r.get("matched").and_then(Value::as_bool).unwrap_or(false);
            if !matched {
                return Ok(
                    json!({"status":"TRANSFORMATION_OBLIGATION_REMAINING","relation":"INCONSISTENT_WITH","diagnostics":[{"code":"TRANSFORMED_THEORY_IMPLEMENTATION_MISMATCH","rule_id":r.pointer("/selected/id")}]}),
                );
            }
            let family = r
                .pointer("/application/reference/approximation_family")
                .cloned()
                .unwrap_or(Value::Null);
            let relation = r
                .pointer("/selected/relation")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .unwrap_or_else(|| {
                    if family.get("mathematical_operator").and_then(Value::as_str)
                        == Some("Derivative")
                    {
                        "DISCRETIZATION_OF".into()
                    } else {
                        "APPROXIMATION_OF".into()
                    }
                });
            let status = if r.pointer("/application/status").and_then(Value::as_str)
                == Some("APPROXIMATION_ERROR_NOT_YET_PROVEN")
            {
                "APPROXIMATION_ERROR_NOT_YET_PROVEN"
            } else {
                "APPROXIMATION_RECOGNIZED"
            };
            let recognized = match family.get("approximation_kind").and_then(Value::as_str) {
                Some("finite_difference") => Some("FINITE_DIFFERENCE_RECOGNIZED"),
                Some("quadrature") => Some("QUADRATURE_RECOGNIZED"),
                Some("interpolation") => Some("INTERPOLATION_RECOGNIZED"),
                _ => None,
            };
            let diagnostics = recognized
                .map(|code| {
                    vec![
                        json!({"code":code}),
                        json!({"code":"CONVERGENCE_ORDER_RECORDED"}),
                        json!({"code":"CONVERGENCE_PROOF_NOT_YET_ESTABLISHED"}),
                        json!({"code":"APPROXIMATION_ERROR_NOT_YET_PROVEN"}),
                    ]
                })
                .unwrap_or_default();
            Ok(json!({"status":status,"relation":relation,"diagnostics":diagnostics}))
        }
        _ => Err(invalid(format!(
            "UNSUPPORTED_TRANSFORMATION_FINALIZATION:{mode}"
        ))),
    }
}
fn strings(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}
fn mentions(v: &Value, name: &str) -> bool {
    match v {
        Value::Array(a) => a.iter().any(|x| mentions(x, name)),
        Value::Object(m) => {
            (m.get("op").and_then(Value::as_str) == Some("BoundVariable")
                && m.get("name").and_then(Value::as_str) == Some(name))
                || m.values().any(|x| mentions(x, name))
        }
        _ => false,
    }
}
fn rewrite_once(node: &Value, rule: &str, out: &mut Vec<Value>) {
    if let Value::Object(m) = node {
        let op = m.get("op").and_then(Value::as_str).unwrap_or("");
        let args = m
            .get("args")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        match rule {
            "factor_common_denominator" if op == "Add" && args.len() == 2 => {
                if args[0]["op"] == json!("Divide")
                    && args[1]["op"] == json!("Divide")
                    && args[0]["args"][1] == args[1]["args"][1]
                {
                    out.push(json!({"op":"Divide","args":[{"op":"Add","args":[args[0]["args"][0],args[1]["args"][0]]},args[0]["args"][1]]}))
                }
            }
            "distribute_multiplication" if op == "Multiply" && args.len() == 2 => {
                for (s, t) in [(&args[0], &args[1]), (&args[1], &args[0])] {
                    if t["op"] == json!("Add") {
                        out.push(json!({"op":"Add","args":t["args"].as_array().unwrap().iter().map(|x|json!({"op":"Multiply","args":[s,x]})).collect::<Vec<_>>()}))
                    }
                }
            }
            "factor_multiplication" if op == "Add" && args.len() == 2 => {
                if args[0]["op"] == json!("Multiply") && args[1]["op"] == json!("Multiply") {
                    if let (Some(a), Some(b)) =
                        (args[0]["args"].as_array(), args[1]["args"].as_array())
                    {
                        if let Some(common) = a.iter().find(|x| b.contains(x)) {
                            if let (Some(x), Some(y)) = (
                                a.iter().find(|x| *x != common),
                                b.iter().find(|x| *x != common),
                            ) {
                                out.push(json!({"op":"Multiply","args":[common,{"op":"Add","args":[x,y]}]}))
                            }
                        }
                    }
                }
            }
            "exp_log_cancel_positive"
                if op == "FunctionCall" && m.get("name").and_then(Value::as_str) == Some("exp") =>
            {
                if args
                    .first()
                    .is_some_and(|x| x["op"] == json!("FunctionCall") && x["name"] == json!("log"))
                {
                    out.push(args[0]["args"][0].clone())
                }
            }
            "euler_to_exponential" if op == "Add" && args.len() == 2 => {
                let cosine = args.iter().find(|x| {
                    x.get("op").and_then(Value::as_str) == Some("FunctionCall")
                        && x.get("name").and_then(Value::as_str) == Some("cos")
                });
                let imaginary = args
                    .iter()
                    .find(|x| x.get("op").and_then(Value::as_str) == Some("Multiply"));
                if let (Some(cosine), Some(imaginary)) = (cosine, imaginary) {
                    let coefficient =
                        imaginary
                            .get("args")
                            .and_then(Value::as_array)
                            .and_then(|a| {
                                a.iter().find(|x| {
                                    x.get("op").and_then(Value::as_str) == Some("Constant")
                                        && matches!(
                                            x.get("value").and_then(Value::as_str),
                                            Some("i" | "-i")
                                        )
                                })
                            });
                    let sine = imaginary
                        .get("args")
                        .and_then(Value::as_array)
                        .and_then(|a| {
                            a.iter().find(|x| {
                                x.get("op").and_then(Value::as_str) == Some("FunctionCall")
                                    && x.get("name").and_then(Value::as_str) == Some("sin")
                            })
                        });
                    if let (Some(coefficient), Some(sine)) = (coefficient, sine) {
                        if sine.get("args") == cosine.get("args") {
                            out.push(json!({"op":"FunctionCall","name":"exp","args":[{"op":"Multiply","args":[coefficient,cosine["args"][0]]}]}));
                        }
                    }
                }
            }
            "sum_constant_extraction" if op == "FiniteSum" => {
                if let Some(body) = m.get("body") {
                    if body["op"] == json!("Multiply") {
                        let bound = m.get("bound_index").and_then(Value::as_str).unwrap_or("");
                        if let Some(a) = body["args"].as_array() {
                            if let Some(c) = a.iter().find(|x| !mentions(x, bound)) {
                                if let Some(term) = a.iter().find(|x| *x != c) {
                                    let mut sum = node.clone();
                                    sum["body"] = term.clone();
                                    out.push(json!({"op":"Multiply","args":[c,sum]}))
                                }
                            }
                        }
                    }
                }
            }
            _ => {}
        }
        for (k, v) in m {
            let mut children = Vec::new();
            rewrite_once(v, rule, &mut children);
            for child in children {
                let mut clone = m.clone();
                clone.insert(k.clone(), child);
                out.push(Value::Object(clone))
            }
        }
    } else if let Value::Array(a) = node {
        for (i, v) in a.iter().enumerate() {
            let mut children = Vec::new();
            rewrite_once(v, rule, &mut children);
            for child in children {
                let mut clone = a.clone();
                clone[i] = child;
                out.push(Value::Array(clone))
            }
        }
    }
}
fn symbolic(
    a: &Value,
    b: &Value,
    l2r: &mut BTreeMap<String, String>,
    r2l: &mut BTreeMap<String, String>,
) -> bool {
    match (a, b) {
        (Value::Array(x), Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(a, b)| symbolic(a, b, l2r, r2l))
        }
        (Value::Object(x), Value::Object(y)) => {
            if x.get("op") != y.get("op") {
                return false;
            }
            if matches!(
                x.get("op").and_then(Value::as_str),
                Some("FreeVariable" | "BoundVariable")
            ) {
                let l = x.get("name").and_then(Value::as_str).unwrap_or("");
                let r = y.get("name").and_then(Value::as_str).unwrap_or("");
                if !l2r.get(l).is_none_or(|v| v == r) || !r2l.get(r).is_none_or(|v| v == l) {
                    return false;
                }
                l2r.insert(l.into(), r.into());
                r2l.insert(r.into(), l.into());
                return true;
            }
            x.iter()
                .filter(|(k, _)| {
                    !["source_spans", "source_node_ids", "expression_id"].contains(&k.as_str())
                })
                .all(|(k, v)| y.get(k).is_some_and(|w| symbolic(v, w, l2r, r2l)))
        }
        _ => a == b,
    }
}
fn pattern(p: &Value, v: &Value, b: &mut BTreeMap<String, Value>) -> bool {
    if p.get("op").and_then(Value::as_str) == Some("PatternVariable") {
        let n = p.get("name").and_then(Value::as_str).unwrap_or("");
        if let Some(old) = b.get(n) {
            old == v
        } else {
            b.insert(n.into(), v.clone());
            true
        }
    } else {
        match (p, v) {
            (Value::Array(a), Value::Array(c)) => {
                a.len() == c.len() && a.iter().zip(c).all(|(x, y)| pattern(x, y, b))
            }
            (Value::Object(a), Value::Object(c)) => a
                .iter()
                .all(|(k, x)| c.get(k).is_some_and(|y| pattern(x, y, b))),
            _ => p == v,
        }
    }
}
fn templ(v: &Value, b: &BTreeMap<String, Value>) -> Result<Value> {
    if v.get("op").and_then(Value::as_str) == Some("PatternVariable") {
        return b
            .get(v.get("name").and_then(Value::as_str).unwrap_or(""))
            .cloned()
            .ok_or_else(|| invalid("TRANSFORMATION_PATTERN_BINDING_MISSING"));
    }
    Ok(match v {
        Value::Array(a) => Value::Array(a.iter().map(|x| templ(x, b)).collect::<Result<Vec<_>>>()?),
        Value::Object(m) => {
            let mut result = m
                .iter()
                .map(|(k, x)| Ok((k.clone(), templ(x, b)?)))
                .collect::<Result<serde_json::Map<_, _>>>()?;
            let keys = if result.get("op").and_then(Value::as_str) == Some("Divide") {
                Some(("numerator", "denominator"))
            } else if result.get("op").and_then(Value::as_str) == Some("Power") {
                Some(("base", "exponent"))
            } else {
                None
            };
            if !result.contains_key("args") {
                if let Some((a, c)) = keys {
                    if result.contains_key(a) && result.contains_key(c) {
                        let left = result.remove(a).unwrap();
                        let right = result.remove(c).unwrap();
                        result.insert("args".into(), json!([left, right]));
                    }
                }
            }
            Value::Object(result)
        }
        _ => v.clone(),
    })
}
fn find_matches(
    p: &Value,
    v: &Value,
    path: Vec<Value>,
    out: &mut Vec<(Vec<Value>, BTreeMap<String, Value>)>,
) {
    let mut b = BTreeMap::new();
    if pattern(p, v, &mut b) {
        out.push((path.clone(), b))
    }
    match v {
        Value::Object(m) => {
            for (k, x) in m {
                let mut q = path.clone();
                q.push(json!(k));
                find_matches(p, x, q, out)
            }
        }
        Value::Array(a) => {
            for (i, x) in a.iter().enumerate() {
                let mut q = path.clone();
                q.push(json!(i));
                find_matches(p, x, q, out)
            }
        }
        _ => {}
    }
}
fn replace_path(v: &Value, path: &[Value], replacement: &Value) -> Value {
    if path.is_empty() {
        return replacement.clone();
    }
    let mut result = v.clone();
    let mut cursor = &mut result;
    for part in path {
        if let Some(k) = part.as_str() {
            cursor = &mut cursor[k]
        } else {
            cursor = &mut cursor[part.as_u64().unwrap() as usize]
        }
    }
    *cursor = replacement.clone();
    result
}
fn bounded(r: &Value) -> Result<Value> {
    let left = &r["left"];
    let right = &r["right"];
    let known = strings(r.get("assumptions"));
    let motifs = strings(r.get("relevant_motifs"));
    let allowed = strings(r.get("authorized_rule_ids"));
    let mut catalog = r["catalog"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|x| {
            allowed.contains(&x["rule_id"].as_str().unwrap_or("").to_owned())
                && (strings(x.get("motifs")).is_empty()
                    || strings(x.get("motifs")).iter().any(|v| motifs.contains(v)))
                && strings(x.get("assumptions"))
                    .iter()
                    .all(|v| known.contains(v))
        })
        .collect::<Vec<_>>();
    catalog.sort_by_key(|x| {
        (
            x["cost"].as_i64().unwrap_or(1),
            x["priority"].as_i64().unwrap_or(100),
            x["rule_id"].as_str().unwrap_or("").to_owned(),
        )
    });
    let state = |e: &Value, p: &str| json!({"expression":e,"applied_rule":null,"assumptions":[],"cost":0,"depth":0,"provenance":[p]});
    let initial = [state(left, "requested"), state(right, "provider")];
    let mut q = [
        VecDeque::from([initial[0].clone()]),
        VecDeque::from([initial[1].clone()]),
    ];
    let mut seen = [
        BTreeSet::from([serde_json::to_string(left)?]),
        BTreeSet::from([serde_json::to_string(right)?]),
    ];
    let mut visited = 2;
    let max_depth = r.get("max_depth").and_then(Value::as_u64).unwrap_or(4);
    let budget = r.get("state_budget").and_then(Value::as_u64).unwrap_or(30);
    while visited <= budget && (!q[0].is_empty() || !q[1].is_empty()) {
        for side in 0..2 {
            let Some(s) = q[side].pop_front() else {
                continue;
            };
            let mut l = BTreeMap::new();
            let mut rr = BTreeMap::new();
            if symbolic(
                &s["expression"],
                &initial[1 - side]["expression"],
                &mut l,
                &mut rr,
            ) {
                return Ok(
                    json!({"status":"REWRITE_PATH_FOUND","left_state":if side==0{&s}else{&initial[0]},"right_state":if side==0{&initial[1]}else{&s},"visited_states":visited,"diagnostics":[]}),
                );
            }
            if s["depth"].as_u64().unwrap_or(0) >= max_depth {
                continue;
            }
            for rule in &catalog {
                let mut results = Vec::new();
                rewrite_once(
                    &s["expression"],
                    rule["rule_id"].as_str().unwrap_or(""),
                    &mut results,
                );
                for e in results {
                    let marker = serde_json::to_string(&e)?;
                    if seen[side].insert(marker) {
                        visited += 1;
                        q[side].push_back(json!({"expression":e,"applied_rule":rule["rule_id"],"assumptions":rule["assumptions"],"cost":s["cost"].as_i64().unwrap_or(0)+rule["cost"].as_i64().unwrap_or(1),"depth":s["depth"].as_i64().unwrap_or(0)+1,"provenance":s["provenance"].as_array().cloned().unwrap_or_default().into_iter().chain([rule["rule_id"].clone()]).collect::<Vec<_>>()}));
                        if visited >= budget {
                            break;
                        }
                    }
                }
                if visited >= budget {
                    break;
                }
            }
        }
    }
    let d = if visited >= budget {
        "REWRITE_RETRIEVAL_MISS"
    } else {
        "NO_AUTHORIZED_REWRITE_PATH"
    };
    Ok(
        json!({"status":d,"left_state":null,"right_state":null,"visited_states":visited,"diagnostics":[d]}),
    )
}
pub fn legacy_transformations_operation(r: &Value) -> Result<Value> {
    match r.get("action").and_then(Value::as_str).unwrap_or("") {
        "BOUNDED_REWRITE" => bounded(r),
        "PATTERN_MATCH" => {
            let mut b = BTreeMap::new();
            Ok(json!({"match":pattern(&r["pattern"],&r["value"],&mut b),"bindings":b}))
        }
        "TEMPLATE" => {
            let b = r["bindings"]
                .as_object()
                .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
                .unwrap_or_default();
            templ(&r["value"], &b)
        }
        "FIND_MATCHES" => {
            let mut out = Vec::new();
            find_matches(&r["pattern"], &r["value"], vec![], &mut out);
            Ok(Value::Array(
                out.into_iter()
                    .map(|(p, b)| json!({"path":p,"bindings":b}))
                    .collect(),
            ))
        }
        "REPLACE_PATH" => Ok(replace_path(
            &r["value"],
            r["path"].as_array().map(Vec::as_slice).unwrap_or(&[]),
            &r["replacement"],
        )),
        "REWRITE_ONCE" => {
            let mut out = Vec::new();
            rewrite_once(&r["node"], r["rule_id"].as_str().unwrap_or(""), &mut out);
            out.sort_by_key(|v| serde_json::to_string(v).unwrap_or_default());
            out.dedup();
            Ok(Value::Array(out))
        }
        "APPLY_EXACT" => {
            let mut result = r["expression"].clone();
            result["outputs"] =
                apply_exact_node(&result["outputs"], r["rule_id"].as_str().unwrap_or(""), 0);
            result["expression_id"] = json!(stable_id("expression", &result["outputs"]));
            Ok(result)
        }
        "HARD_CONSTRAINTS" => Ok(hard_constraints(
            &r["rule"],
            &r["transformation_set"],
            &r["theory"],
            &r["context"],
        )),
        "APPLICATION" => Ok(application(
            &r["rule"],
            &r["source"],
            &r["target"],
            &r["checks"],
            &r["assumptions"],
            &r["provenance"],
        )),
        "FINALIZE" => finalize(r),
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_TRANSFORMATIONS_ACTION:{action}"
        ))),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn nonexact_never_rewrites() {
        let mut out = Vec::new();
        rewrite_once(
            &json!({"op":"Derivative"}),
            "finite_difference_first_derivative",
            &mut out,
        );
        assert!(out.is_empty());
    }
}
