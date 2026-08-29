//! Native owner for foundational mathematical-function and infinite-process decisions.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
fn invalid(m: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(m.into())
}
fn domain(description: &str, constraints: Vec<&str>) -> Value {
    json!({"description":description,"constraints":constraints})
}
fn properties(name: &str) -> Value {
    match name.to_lowercase().rsplit('.').next().unwrap_or("") {
        "exp" => {
            json!({"name":"exp","domain":domain("Real",vec![]),"codomain":domain("PositiveReal",vec![]),"certified_range":{"lower":0,"upper":"+inf","evidence":"CONTRACT_VERIFIED","proof_reference":null},"properties":{"positive":true,"strictly_monotone":true},"periods":[],"evidence":{"positive":"CONTRACT_VERIFIED"}})
        }
        "log" => {
            json!({"name":"log","domain":domain("PositiveReal",vec!["x > 0"]),"codomain":domain("Real",vec![]),"certified_range":null,"properties":{"strictly_monotone":true},"periods":[],"evidence":{"domain":"CONTRACT_VERIFIED"}})
        }
        "sin" => trig("sin", "odd"),
        "cos" => trig("cos", "even"),
        "sqrt" => {
            json!({"name":"sqrt","domain":domain("NonnegativeReal",vec!["x >= 0"]),"codomain":domain("NonnegativeReal",vec![]),"certified_range":{"lower":0,"upper":"+inf","evidence":"CONTRACT_VERIFIED","proof_reference":null},"properties":{"nonnegative":true,"monotone":true},"periods":[],"evidence":{"domain":"CONTRACT_VERIFIED"}})
        }
        "abs" => {
            json!({"name":"abs","domain":domain("Real",vec![]),"codomain":domain("NonnegativeReal",vec![]),"certified_range":{"lower":0,"upper":"+inf","evidence":"CONTRACT_VERIFIED","proof_reference":null},"properties":{"nonnegative":true},"periods":[],"evidence":{"range":"CONTRACT_VERIFIED"}})
        }
        _ => {
            json!({"name":name,"domain":null,"codomain":null,"certified_range":null,"properties":{},"periods":[],"evidence":{"contract":"UNRESOLVED"}})
        }
    }
}
fn trig(name: &str, parity: &str) -> Value {
    let mut properties = serde_json::Map::new();
    properties.insert(parity.into(), json!(true));
    json!({"name":name,"domain":domain("Real",vec![]),"codomain":domain("Real",vec![]),"certified_range":{"lower":-1,"upper":1,"evidence":"CONTRACT_VERIFIED","proof_reference":null},"properties":properties,"periods":["2*pi"],"evidence":{"range":"CONTRACT_VERIFIED","period":"CONTRACT_VERIFIED"}})
}
fn propagate(expr: &Value) -> Value {
    match expr.get("op").and_then(Value::as_str).unwrap_or("") {
        "FunctionCall" => properties(expr.get("name").and_then(Value::as_str).unwrap_or("")),
        "Power"
            if expr
                .get("args")
                .and_then(Value::as_array)
                .and_then(|v| v.get(1))
                .and_then(|v| v.get("value"))
                .and_then(Value::as_i64)
                == Some(2) =>
        {
            json!({"name":"square","domain":domain("Real",vec![]),"codomain":domain("NonnegativeReal",vec![]),"certified_range":{"lower":0,"upper":"+inf","evidence":"DERIVED","proof_reference":null},"properties":{"nonnegative":true},"periods":[],"evidence":{"range":"DERIVED"}})
        }
        "Add" => {
            let parts = expr
                .get("args")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .map(propagate)
                .collect::<Vec<_>>();
            let ranges = parts
                .iter()
                .filter_map(|p| p.get("certified_range"))
                .collect::<Vec<_>>();
            if !parts.is_empty()
                && ranges.len() == parts.len()
                && ranges
                    .iter()
                    .all(|r| r["lower"].is_number() && r["upper"].is_number())
            {
                let lower: f64 = ranges.iter().map(|r| r["lower"].as_f64().unwrap()).sum();
                let upper: f64 = ranges.iter().map(|r| r["upper"].as_f64().unwrap()).sum();
                json!({"name":"sum","domain":null,"codomain":null,"certified_range":{"lower":lower,"upper":upper,"evidence":"DERIVED","proof_reference":null},"properties":{},"periods":[],"evidence":{"range":"DERIVED"}})
            } else {
                unresolved("Add")
            }
        }
        op => unresolved(op),
    }
}
fn unresolved(name: &str) -> Value {
    json!({"name":name,"domain":null,"codomain":null,"certified_range":null,"properties":{},"periods":[],"evidence":{"propagation":"UNRESOLVED"}})
}
fn partial(process: &Value, stop: Value, symmetric: Option<i64>) -> Result<Value> {
    let kind = process["kind"].as_str().unwrap_or("");
    let seq = &process["sequence"];
    if let Some(radius) = symmetric {
        if kind != "BilateralInfiniteSeries" {
            return Err(invalid("NOT_A_BILATERAL_SERIES"));
        }
        return Ok(
            json!({"op":"FiniteSum","bound_index":seq["index"],"index_domain":{"lower":{"op":"Constant","value":-radius},"upper_exclusive":{"op":"Constant","value":radius+1}},"body":seq["term"],"lowered_from":kind,"truncation_convention":"symmetric_frequency_window"}),
        );
    }
    if kind == "BilateralInfiniteSeries" {
        return Err(invalid(
            "BILATERAL_SERIES_REQUIRES_EXPLICIT_LOWER_AND_UPPER_TRUNCATION",
        ));
    }
    Ok(
        json!({"op":if kind=="InfiniteProduct"{"FiniteProduct"}else{"FiniteSum"},"bound_index":seq["index"],"index_domain":{"lower":{"op":"Constant","value":seq["lower"]},"upper_exclusive":stop},"body":seq["term"],"lowered_from":kind}),
    )
}
fn power_term(v: &Value) -> Value {
    json!({"op":"Multiply","args":[v["coefficient"],{"op":"Power","args":[{"op":"Subtract","args":[{"op":"FreeVariable","name":v["variable"]},{"op":"Constant","value":v["center"]}]},{"op":"BoundVariable","name":v["index"]}]}]})
}
fn taylor(v: &Value) -> Value {
    let derivative = json!({"op":"Derivative","function":v["function"],"variable":v["variable"],"order":{"op":"BoundVariable","name":v["index"]},"at":{"op":"Constant","value":v["center"]}});
    let coefficient = json!({"op":"Divide","args":[derivative,{"op":"Factorial","args":[{"op":"BoundVariable","name":v["index"]}]}]});
    json!({"kind":"InfiniteSeries","sequence":{"index":v["index"],"term":power_term(&json!({"coefficient":coefficient,"variable":v["variable"],"center":v["center"],"index":v["index"]})),"lower":0},"convergence":null,"rate":null,"origins":{"origins":[]}})
}
fn fourier(v: &Value) -> Value {
    let n = "n";
    let coefficient =
        json!({"op":"IndexedValue","name":"c","indices":[{"op":"BoundVariable","name":n}]});
    let kernel = json!({"op":"FunctionCall","name":"exp","args":[{"op":"Multiply","args":[{"op":"Constant","value":"i"},{"op":"Multiply","args":[{"op":"BoundVariable","name":n},{"op":"FreeVariable","name":v["variable"]}]}]}]});
    json!({"kind":"BilateralInfiniteSeries","sequence":{"index":n,"term":{"op":"Multiply","args":[coefficient,kernel]},"lower":"-inf"},"convergence":{"kind":"REPRESENTS_UNDER_FOURIER_CONDITIONS","left":{"op":"FourierSeries"},"right":{"op":"FunctionSymbol","name":v["function"]},"conditions":["periodic","Fourier convergence conditions"],"evidence":"DECLARED"},"rate":null,"origins":{"origins":[]}})
}
fn convergence(process: &Value, assumptions: &Value) -> Value {
    let term = &process["sequence"]["term"];
    let known = assumptions.as_array().cloned().unwrap_or_default();
    let has = |s: &str| known.iter().any(|v| v.as_str() == Some(s));
    match term.get("family_id").and_then(Value::as_str) {
        Some("geometric") => {
            let ratio = term
                .get("ratio")
                .cloned()
                .unwrap_or(json!({"op":"FreeVariable","name":"r"}));
            if has("abs(r) < 1") {
                json!({"status":"CONVERGENCE_CERTIFIED","test":"GEOMETRIC_SERIES","conditions":["abs(r) < 1"],"evidence":"CONTRACT_VERIFIED","tail_bound":{"op":"Divide","args":[{"op":"Power","args":[ratio,{"op":"FreeVariable","name":"N"}]},{"op":"Subtract","args":[{"op":"Constant","value":1},{"op":"FunctionCall","name":"abs","args":[term.get("ratio").cloned().unwrap_or(json!({"op":"FreeVariable","name":"r"}))]}]}]}})
            } else if has("abs(r) >= 1") {
                json!({"status":"DIVERGENCE_CERTIFIED","test":"GEOMETRIC_TERM_TEST","conditions":["abs(r) >= 1"],"evidence":"CONTRACT_VERIFIED","tail_bound":null})
            } else {
                json!({"status":"CONVERGENCE_UNRESOLVED","test":"GEOMETRIC_SERIES","conditions":["abs(r) < 1"],"evidence":"UNRESOLVED","tail_bound":null})
            }
        }
        Some("p_series") => {
            if has("p <= 1") {
                json!({"status":"DIVERGENCE_CERTIFIED","test":"P_SERIES","conditions":["p <= 1"],"evidence":"CONTRACT_VERIFIED","tail_bound":null})
            } else {
                json!({"status":if has("p > 1"){"CONVERGENCE_CERTIFIED"}else{"CONVERGENCE_UNRESOLVED"},"test":"P_SERIES","conditions":["p > 1"],"evidence":if has("p > 1"){"CONTRACT_VERIFIED"}else{"UNRESOLVED"},"tail_bound":if has("p > 1"){json!({"op":"Divide","args":[{"op":"Power","args":[{"op":"FreeVariable","name":"N"},{"op":"Subtract","args":[{"op":"Constant","value":1},{"op":"FreeVariable","name":"p"}]}]},{"op":"Subtract","args":[{"op":"FreeVariable","name":"p"},{"op":"Constant","value":1}]}]})}else{Value::Null}})
            }
        }
        Some("alternating") if has("terms_nonincreasing") && has("terms_tend_to_zero") => {
            json!({"status":"CONVERGENCE_CERTIFIED","test":"LEIBNIZ","conditions":["terms_nonincreasing","terms_tend_to_zero"],"evidence":"CONTRACT_VERIFIED","tail_bound":{"op":"NextTermMagnitude","index":"N"}})
        }
        _ if term.get("op").and_then(Value::as_str) == Some("Constant")
            && term.get("value") != Some(&json!(0))
            && term.get("value") != Some(&json!(0.0)) =>
        {
            json!({"status":"DIVERGENCE_CERTIFIED","test":"TERM_TEST","conditions":["term does not tend to zero"],"evidence":"DERIVED","tail_bound":null})
        }
        _ => {
            json!({"status":"CONVERGENCE_UNRESOLVED","test":"NO_APPLICABLE_SAFE_TEST","conditions":[],"evidence":"UNRESOLVED","tail_bound":null})
        }
    }
}
fn transform(name: &str, function: &Value) -> Value {
    match name.to_lowercase().as_str() {
        "fourier" => {
            json!({"op":"FourierTransform","function":function,"kernel":{"op":"FunctionCall","name":"exp","args":[{"op":"Multiply","args":[{"op":"Constant","value":"-i"},{"op":"Multiply","args":[{"op":"FreeVariable","name":"omega"},{"op":"FreeVariable","name":"t"}]}]}]},"variable":"t","frequency":"omega","domain":{"description":"IntegrableFunctions","constraints":[]},"region_of_convergence":[],"inverse":"InverseFourierTransform","status":"TRANSFORM_CONTRACT_RESOLVED"})
        }
        "laplace" => {
            json!({"op":"LaplaceTransform","function":function,"kernel":{"op":"FunctionCall","name":"exp","args":[{"op":"Negate","args":[{"op":"Multiply","args":[{"op":"FreeVariable","name":"s"},{"op":"FreeVariable","name":"t"}]}]}]},"variable":"t","frequency":"s","domain":{"description":"ExponentialOrderFunctions","constraints":[]},"region_of_convergence":["Re(s) > growth_bound"],"inverse":"InverseLaplaceTransform","status":"TRANSFORM_CONTRACT_RESOLVED"})
        }
        _ => {
            json!({"op":"IntegralTransform","name":name,"function":function,"status":"TRANSFORM_SEMANTICS_UNRESOLVED"})
        }
    }
}
pub fn legacy_math_semantics_operation(r: &Value) -> Result<Value> {
    match r.get("action").and_then(Value::as_str).unwrap_or("") {
        "ORIGIN_MERGE" => {
            let mut values = Vec::new();
            for item in r["groups"]
                .as_array()
                .into_iter()
                .flatten()
                .flat_map(|v| v.as_array().into_iter().flatten())
            {
                if !values.contains(item) {
                    values.push(item.clone())
                }
            }
            Ok(json!(values))
        }
        "LOCALIZE" => {
            let origins = r["origins"].as_array().cloned().unwrap_or_default();
            let spans = origins
                .iter()
                .filter_map(|v| v.get("span"))
                .filter(|v| !v.is_null())
                .cloned()
                .collect::<Vec<_>>();
            let path = r["path"].as_array().cloned().unwrap_or_default();
            Ok(
                json!({"status":if spans.len()==1{"EXACT_SOURCE_SPAN"}else if !spans.is_empty(){"SOURCE_SPAN_SET"}else if !path.is_empty(){"CORRECT_SEMANTIC_NODE_SOURCE_UNRESOLVED"}else{"LOCALIZATION_UNRESOLVED"},"semantic_path":path,"source_spans":spans,"origins":origins}),
            )
        }
        "USABLE_PROPERTIES" => Ok(json!(r["evidence"]
            .as_object()
            .into_iter()
            .flat_map(|v| v.values())
            .all(|v| !matches!(v.as_str(), Some("DECLARED" | "UNRESOLVED"))))),
        "FUNCTION_PROPERTIES" => Ok(properties(r["name"].as_str().unwrap_or(""))),
        "PROPAGATE" => Ok(propagate(&r["expression"])),
        "RANGE_STATUS" => {
            let c = &r["condition"];
            if c["op"] != json!("Compare") || c["args"].as_array().map(|v| v.len()) != Some(2) {
                return Ok(json!("RANGE_BRANCH_UNRESOLVED"));
            }
            let p = propagate(&c["args"][0]);
            let range = &p["certified_range"];
            let allowed = ["DERIVED", "CONTRACT_VERIFIED", "KERNEL_VERIFIED"];
            if range.is_null() || !allowed.contains(&range["evidence"].as_str().unwrap_or("")) {
                return Ok(json!("RANGE_BRANCH_UNRESOLVED"));
            }
            let Some(value) = c["args"][1]["value"].as_f64() else {
                return Ok(json!("RANGE_BRANCH_UNRESOLVED"));
            };
            let Some(lower) = range["lower"].as_f64() else {
                return Ok(json!("RANGE_BRANCH_UNRESOLVED"));
            };
            Ok(json!(
                if c["comparison"] == json!("LessThan") && lower >= value {
                    "THEN_BRANCH_PROVABLY_UNREACHABLE"
                } else if c["comparison"] == json!("GreaterEqual") && lower >= value {
                    "ELSE_BRANCH_PROVABLY_UNREACHABLE"
                } else {
                    "RANGE_BRANCH_UNRESOLVED"
                }
            ))
        }
        "PARTIAL" => partial(&r["process"], r["stop"].clone(), None),
        "PARTIAL_SYMMETRIC" => partial(
            &r["process"],
            Value::Null,
            Some(r["radius"].as_i64().unwrap_or(0)),
        ),
        "TAIL" => Ok(
            json!({"op":"Tail","process":r["process"]["kind"],"start":r["start"],"bound_index":r["process"]["sequence"]["index"],"body":r["process"]["sequence"]["term"]}),
        ),
        "POWER_TERM" => Ok(power_term(&r["series"])),
        "TAYLOR_PROCESS" => Ok(taylor(&r["series"])),
        "FOURIER_PROCESS" => Ok(fourier(&r["series"])),
        "SERIES_CANDIDATES" => {
            let p = &r["process"];
            let direct = if p["kind"] == json!("BilateralInfiniteSeries") {
                partial(p, Value::Null, Some(5))?
            } else {
                partial(p, json!({"op":"FreeVariable","name":"N"}), None)?
            };
            Ok(
                json!([{"strategy":"DIRECT_TERM","algorithm":direct,"status":"CANDIDATE_NOT_VERIFIED"},{"strategy":"RECURRENCE","algorithm":{"op":"RecurrencePartialSum","term":p["sequence"]["term"]},"required_relation":"RECURRENCE_GENERATES_SAME_TERMS","status":"CANDIDATE_NOT_VERIFIED"}]),
            )
        }
        "ANALYZE_CONVERGENCE" => Ok(convergence(&r["process"], &r["assumptions"])),
        "SOLVE_TRUNCATION" => {
            let c = &r["convergence"];
            let req = &r["requirement"];
            let tolerance = req["tolerance"].as_f64().unwrap_or(0.0);
            if tolerance <= 0.0 {
                return Ok(
                    json!({"status":"TRUNCATION_UNRESOLVED","minimum_terms":null,"remainder_bound":"tolerance must be positive","distinction":"CERTIFIED_REMAINDER_NOT_TERM_MAGNITUDE"}),
                );
            }
            if c["evidence"] == json!("UNRESOLVED") {
                return Ok(
                    json!({"status":"TRUNCATION_UNRESOLVED","minimum_terms":null,"remainder_bound":null,"distinction":"CERTIFIED_REMAINDER_NOT_TERM_MAGNITUDE"}),
                );
            }
            if c["test"] == json!("GEOMETRIC_SERIES") {
                let ratio = if let Some(values) = req["uniform_domain"].as_array() {
                    values
                        .iter()
                        .filter_map(Value::as_f64)
                        .map(f64::abs)
                        .fold(0.0, f64::max)
                } else {
                    r["parameters"]
                        .get("r")
                        .and_then(Value::as_f64)
                        .unwrap_or(2.0)
                        .abs()
                };
                if ratio > 0.0 && ratio < 1.0 {
                    let n = (tolerance * (1.0 - ratio)).log(ratio).ceil().max(0.0) as i64;
                    return Ok(
                        json!({"status":"TRUNCATION_CERTIFIED","minimum_terms":n,"remainder_bound":format!("|r|^N/(1-|r|) <= {tolerance}"),"distinction":"CERTIFIED_REMAINDER_NOT_TERM_MAGNITUDE"}),
                    );
                }
            }
            Ok(
                json!({"status":"TRUNCATION_REQUIRES_SYMBOLIC_SOLVER","minimum_terms":null,"remainder_bound":c["tail_bound"].to_string(),"distinction":"CERTIFIED_REMAINDER_NOT_TERM_MAGNITUDE"}),
            )
        }
        "INTEGRAL_TRANSFORM" => Ok(transform(r["name"].as_str().unwrap_or(""), &r["function"])),
        "INVERSE_MAPPING" => {
            let t = &r["transform"];
            let required = t["region_of_convergence"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            let known = r["assumptions"].as_array().cloned().unwrap_or_default();
            if t.get("inverse").is_none() || t["inverse"].is_null() {
                return Ok(
                    json!({"kind":"INVERSE_UNRESOLVED","left":t,"right":null,"conditions":[],"evidence":"UNRESOLVED"}),
                );
            }
            let verified = required.iter().all(|v| known.contains(v));
            Ok(
                json!({"kind":if verified{"INVERSE_OF"}else{"INVERSE_CONDITIONS_UNRESOLVED"},"left":{"op":t["inverse"]},"right":t,"conditions":required,"evidence":if verified{"CONTRACT_VERIFIED"}else{"UNRESOLVED"}}),
            )
        }
        "CONVOLUTION" => Ok(
            json!({"op":"Convolution","left":r["left"],"right":r["right"],"domain":r["domain"],"transform_relation":{"kind":"TRANSFORM_OF_CONVOLUTION_IS_PRODUCT","conditions":["transform exists"],"evidence":"DECLARED"}}),
        ),
        "DISCRETE_LAYERS" => {
            let fft = r["kind"]
                .as_str()
                .unwrap_or("dft")
                .eq_ignore_ascii_case("fft");
            Ok(
                json!({"mathematics":{"op":"DiscreteFourierTransform"},"algorithm":{"op":if fft{"FFT"}else{"DIRECT_DFT"},"exact_relation":"COMPUTES_DFT"},"execution":{"rounding":"IEEE754","reordering":fft},"error":{"status":"REQUIRES_NUMERIC_TYPE_AND_LENGTH"}}),
            )
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_MATH_SEMANTICS_ACTION:{action}"
        ))),
    }
}
