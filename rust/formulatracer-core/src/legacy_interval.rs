//! Sound legacy interval semantics. Unknown domains fail closed.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn number(v: &Value) -> Option<f64> {
    v.as_f64()
}
fn down(x: f64) -> f64 {
    if x.is_nan() || x == f64::NEG_INFINITY {
        x
    } else if x == 0.0 {
        -f64::from_bits(1)
    } else {
        let bits = x.to_bits();
        f64::from_bits(if x > 0.0 { bits - 1 } else { bits + 1 })
    }
}
fn up(x: f64) -> f64 {
    if x.is_nan() || x == f64::INFINITY {
        x
    } else if x == 0.0 {
        f64::from_bits(1)
    } else {
        let bits = x.to_bits();
        f64::from_bits(if x > 0.0 { bits + 1 } else { bits - 1 })
    }
}
fn resolved(v: &Value) -> bool {
    !matches!(
        v.get("status").and_then(Value::as_str),
        Some("INTERVAL_UNRESOLVED" | "INTERVAL_INVALID" | "NUMERICALLY_OBSERVED_ONLY")
    )
}
fn unresolved(code: &str, expression: Value) -> Value {
    json!({"lower":null,"upper":null,"lower_closed":true,"upper_closed":true,"numeric_domain":"MATHEMATICAL_RANGE","proof_status":"INTERVAL_UNRESOLVED","provenance":{"diagnostic":code,"expression":expression},"status":"INTERVAL_UNRESOLVED","assumptions":[],"dimensions":[]})
}
fn singleton(v: Value, provenance: Value) -> Value {
    json!({"lower":v,"upper":v,"lower_closed":true,"upper_closed":true,"numeric_domain":"MATHEMATICAL_RANGE","proof_status":"INTERVAL_PROPAGATION_KERNEL_VERIFIED","provenance":provenance,"status":"EXACT_SINGLETON","assumptions":[],"dimensions":[]})
}
fn expr(op: &str, a: Value, b: Value) -> Value {
    json!({"op":op,"args":[a,b]})
}
fn combine(
    lower: Value,
    upper: Value,
    rule: &str,
    inputs: &[Value],
    closed: (bool, bool),
) -> Value {
    let symbolic = number(&lower).is_none() || number(&upper).is_none();
    let mut assumptions = inputs
        .iter()
        .flat_map(|v| {
            v.get("assumptions")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::to_owned)
        })
        .collect::<Vec<_>>();
    assumptions.sort();
    assumptions.dedup();
    let mut dimensions = Vec::new();
    for name in inputs.iter().flat_map(|v| {
        v.get("dimensions")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
    }) {
        if !dimensions.contains(&name.to_owned()) {
            dimensions.push(name.to_owned())
        }
    }
    let theorem = matches!(
        rule,
        "interval_add"
            | "interval_neg"
            | "interval_mul"
            | "interval_abs"
            | "interval_sum"
            | "interval_square"
            | "interval_div_positive_denominator"
    )
    .then(|| format!("CppAudit.Interval.{rule}"));
    let mut provenance = json!({"rule":rule,"input_intervals":inputs.iter().filter_map(|x|x.get("interval_id")).collect::<Vec<_>>()});
    if let Some(t) = theorem {
        provenance["theorem"] = json!(t)
    }
    json!({"lower":lower,"upper":upper,"lower_closed":closed.0,"upper_closed":closed.1,"numeric_domain":"MATHEMATICAL_RANGE","proof_status":"INTERVAL_PROPAGATION_SYMBOLIC","provenance":provenance,"status":if symbolic{"SYMBOLIC_INTERVAL"}else{"INTERVAL_ARITHMETIC_VERIFIED"},"assumptions":assumptions,"dimensions":dimensions})
}
fn endpoint(op: &str, a: &Value, b: &Value, upper: bool) -> Value {
    if let (Some(x), Some(y)) = (a.as_i64(), b.as_i64()) {
        let exact = match op {
            "Add" => x.checked_add(y),
            "Subtract" => x.checked_sub(y),
            "Multiply" => x.checked_mul(y),
            _ => None,
        };
        if let Some(z) = exact {
            return json!(z);
        }
    }
    if let (Some(x), Some(y)) = (number(a), number(b)) {
        let z = match op {
            "Add" => x + y,
            "Subtract" => x - y,
            "Multiply" => x * y,
            "Divide" => x / y,
            _ => f64::NAN,
        };
        json!(if upper { up(z) } else { down(z) })
    } else {
        expr(op, a.clone(), b.clone())
    }
}
fn contains_zero(v: &Value) -> bool {
    match (number(&v["lower"]), number(&v["upper"])) {
        (Some(a), Some(b)) => a <= 0.0 && b >= 0.0,
        _ => true,
    }
}
fn add(a: &Value, b: &Value) -> Value {
    if !resolved(a) || !resolved(b) {
        return unresolved("INTERVAL_INPUT_UNRESOLVED", Value::Null);
    }
    combine(
        endpoint("Add", &a["lower"], &b["lower"], false),
        endpoint("Add", &a["upper"], &b["upper"], true),
        "interval_add",
        &[a.clone(), b.clone()],
        (
            a["lower_closed"].as_bool().unwrap_or(true)
                && b["lower_closed"].as_bool().unwrap_or(true),
            a["upper_closed"].as_bool().unwrap_or(true)
                && b["upper_closed"].as_bool().unwrap_or(true),
        ),
    )
}
fn neg(v: &Value) -> Value {
    if !resolved(v) {
        return unresolved("INTERVAL_INPUT_UNRESOLVED", Value::Null);
    }
    let lo = v["upper"]
        .as_i64()
        .and_then(i64::checked_neg)
        .map(|x| json!(x))
        .or_else(|| number(&v["upper"]).map(|x| json!(-x)))
        .unwrap_or_else(|| json!({"op":"Negate","args":[v["upper"]]}));
    let hi = v["lower"]
        .as_i64()
        .and_then(i64::checked_neg)
        .map(|x| json!(x))
        .or_else(|| number(&v["lower"]).map(|x| json!(-x)))
        .unwrap_or_else(|| json!({"op":"Negate","args":[v["lower"]]}));
    combine(
        lo,
        hi,
        "interval_neg",
        std::slice::from_ref(v),
        (
            v["upper_closed"].as_bool().unwrap_or(true),
            v["lower_closed"].as_bool().unwrap_or(true),
        ),
    )
}
fn mul(a: &Value, b: &Value) -> Value {
    if !resolved(a) || !resolved(b) {
        return unresolved("INTERVAL_INPUT_UNRESOLVED", Value::Null);
    }
    if let (Some(al), Some(au), Some(bl), Some(bu)) = (
        a["lower"].as_i64(),
        a["upper"].as_i64(),
        b["lower"].as_i64(),
        b["upper"].as_i64(),
    ) {
        let raw = [
            al.checked_mul(bl),
            al.checked_mul(bu),
            au.checked_mul(bl),
            au.checked_mul(bu),
        ];
        if raw.iter().all(Option::is_some) {
            let values = raw.into_iter().flatten().collect::<Vec<_>>();
            return combine(
                json!(*values.iter().min().unwrap()),
                json!(*values.iter().max().unwrap()),
                "interval_mul",
                &[a.clone(), b.clone()],
                (true, true),
            );
        }
    }
    if let (Some(al), Some(au), Some(bl), Some(bu)) = (
        number(&a["lower"]),
        number(&a["upper"]),
        number(&b["lower"]),
        number(&b["upper"]),
    ) {
        let raw = [al * bl, al * bu, au * bl, au * bu];
        return combine(
            json!(down(raw.into_iter().fold(f64::INFINITY, f64::min))),
            json!(up(raw.into_iter().fold(f64::NEG_INFINITY, f64::max))),
            "interval_mul",
            &[a.clone(), b.clone()],
            (
                [a, b].iter().all(|v| {
                    v["lower_closed"].as_bool().unwrap_or(true)
                        && v["upper_closed"].as_bool().unwrap_or(true)
                }),
                [a, b].iter().all(|v| {
                    v["lower_closed"].as_bool().unwrap_or(true)
                        && v["upper_closed"].as_bool().unwrap_or(true)
                }),
            ),
        );
    }
    let products = [
        (&a["lower"], &b["lower"]),
        (&a["lower"], &b["upper"]),
        (&a["upper"], &b["lower"]),
        (&a["upper"], &b["upper"]),
    ]
    .into_iter()
    .map(|(x, y)| expr("Multiply", x.clone(), y.clone()))
    .collect::<Vec<_>>();
    combine(
        json!({"op":"Min","args":products}),
        json!({"op":"Max","args":products}),
        "interval_mul",
        &[a.clone(), b.clone()],
        (true, true),
    )
}
fn divide(a: &Value, b: &Value) -> Value {
    if !resolved(a) || !resolved(b) {
        return unresolved("INTERVAL_INPUT_UNRESOLVED", Value::Null);
    }
    if contains_zero(b) {
        return unresolved("DIVISION_INTERVAL_CROSSES_ZERO", b.clone());
    }
    if let (Some(lo), Some(hi)) = (number(&b["lower"]), number(&b["upper"])) {
        let reciprocal = json!({"lower":down(1.0/hi),"upper":up(1.0/lo),"lower_closed":b["upper_closed"],"upper_closed":b["lower_closed"],"numeric_domain":"MATHEMATICAL_RANGE","proof_status":"INTERVAL_PROPAGATION_SYMBOLIC","provenance":{"rule":"interval_div_positive_denominator"},"status":"INTERVAL_ARITHMETIC_VERIFIED","assumptions":[],"dimensions":[]});
        mul(a, &reciprocal)
    } else {
        let reciprocal = combine(
            expr("Divide", json!(1), b["upper"].clone()),
            expr("Divide", json!(1), b["lower"].clone()),
            "interval_div_positive_denominator",
            std::slice::from_ref(b),
            (true, true),
        );
        mul(a, &reciprocal)
    }
}
fn absolute(v: &Value) -> Value {
    if !resolved(v) {
        return unresolved("INTERVAL_INPUT_UNRESOLVED", Value::Null);
    }
    if let (Some(lo), Some(hi)) = (v["lower"].as_i64(), v["upper"].as_i64()) {
        let lower = if lo <= 0 && hi >= 0 {
            0
        } else {
            lo.saturating_abs().min(hi.saturating_abs())
        };
        let upper = lo.saturating_abs().max(hi.saturating_abs());
        return combine(
            json!(lower),
            json!(upper),
            "interval_abs",
            std::slice::from_ref(v),
            (true, true),
        );
    }
    if let (Some(lo), Some(hi)) = (number(&v["lower"]), number(&v["upper"])) {
        return combine(
            json!(if lo <= 0.0 && hi >= 0.0 {
                0.0
            } else {
                lo.abs().min(hi.abs())
            }),
            json!(lo.abs().max(hi.abs())),
            "interval_abs",
            std::slice::from_ref(v),
            (true, true),
        );
    }
    combine(
        json!(0),
        json!({"op":"Max","args":[{"op":"Abs","args":[v["lower"]]},{"op":"Abs","args":[v["upper"]]}]}),
        "interval_abs",
        std::slice::from_ref(v),
        (true, true),
    )
}
fn power(v: &Value, n: i64) -> Value {
    if !resolved(v) {
        return unresolved("POWER_DOMAIN_UNRESOLVED", Value::Null);
    }
    if n < 0 {
        return divide(
            &singleton(json!(1), json!({"rule":"interval_power_reciprocal"})),
            &power(v, -n),
        );
    }
    if n == 0 {
        return singleton(json!(1), json!({"rule":"interval_power_zero"}));
    }
    if let (Some(lo), Some(hi)) = (v["lower"].as_i64(), v["upper"].as_i64()) {
        if let Ok(exponent) = u32::try_from(n) {
            if let (Some(lp), Some(hp)) = (lo.checked_pow(exponent), hi.checked_pow(exponent)) {
                let (a, b) = if n % 2 == 0 {
                    (if lo <= 0 && hi >= 0 { 0 } else { lp.min(hp) }, lp.max(hp))
                } else {
                    (lp, hp)
                };
                return combine(
                    json!(a),
                    json!(b),
                    if n == 2 {
                        "interval_square"
                    } else {
                        "interval_integer_power"
                    },
                    std::slice::from_ref(v),
                    (true, true),
                );
            }
        }
    }
    if let (Some(lo), Some(hi)) = (number(&v["lower"]), number(&v["upper"])) {
        let (a, b) = if n % 2 == 0 {
            (
                if lo <= 0.0 && hi >= 0.0 {
                    0.0
                } else {
                    lo.powi(n as i32).min(hi.powi(n as i32))
                },
                lo.powi(n as i32).max(hi.powi(n as i32)),
            )
        } else {
            (lo.powi(n as i32), hi.powi(n as i32))
        };
        return combine(
            json!(down(a)),
            json!(up(b)),
            if n == 2 {
                "interval_square"
            } else {
                "interval_integer_power"
            },
            std::slice::from_ref(v),
            (true, true),
        );
    }
    combine(
        json!({"op":"MinPower","base":v["lower"],"exponent":n}),
        json!({"op":"MaxPower","base":v["upper"],"exponent":n}),
        "interval_integer_power",
        std::slice::from_ref(v),
        (true, true),
    )
}
fn elementary(op: &str, v: &Value, node: &Value) -> Value {
    if op.eq_ignore_ascii_case("abs") {
        return absolute(v);
    }
    if !resolved(v) || number(&v["lower"]).is_none() || number(&v["upper"]).is_none() {
        return unresolved("ELEMENTARY_FUNCTION_RANGE_UNRESOLVED", node.clone());
    }
    let (lo, hi) = (number(&v["lower"]).unwrap(), number(&v["upper"]).unwrap());
    match op.to_ascii_lowercase().as_str() {
        "sqrt" => {
            if lo < 0.0 {
                unresolved("SQRT_NEGATIVE_DOMAIN", node.clone())
            } else {
                combine(
                    json!(if lo == 0.0 { 0.0 } else { down(lo.sqrt()) }),
                    json!(up(hi.sqrt())),
                    "sqrt_monotone",
                    std::slice::from_ref(v),
                    (true, true),
                )
            }
        }
        "log" | "ln" => {
            if lo <= 0.0 {
                unresolved("LOG_NONPOSITIVE_DOMAIN", node.clone())
            } else {
                combine(
                    json!(down(lo.ln())),
                    json!(up(hi.ln())),
                    "log_monotone",
                    std::slice::from_ref(v),
                    (true, true),
                )
            }
        }
        "exp" => {
            let a = lo.exp();
            let b = hi.exp();
            if !a.is_finite() || !b.is_finite() {
                unresolved("EXP_RANGE_OVERFLOW", node.clone())
            } else {
                combine(
                    json!(down(a)),
                    json!(up(b)),
                    "exp_monotone",
                    std::slice::from_ref(v),
                    (true, true),
                )
            }
        }
        "sin" | "cos" => {
            let f = if op.eq_ignore_ascii_case("sin") {
                f64::sin
            } else {
                f64::cos
            };
            let (mut a, mut b) = (-1.0, 1.0);
            if hi - lo < std::f64::consts::TAU {
                let offset = if op.eq_ignore_ascii_case("sin") {
                    std::f64::consts::FRAC_PI_2
                } else {
                    0.0
                };
                let start = ((lo - offset) / std::f64::consts::PI).ceil() as i64;
                let end = ((hi - offset) / std::f64::consts::PI).floor() as i64;
                let mut values = vec![f(lo), f(hi)];
                for k in start..=end {
                    values.push(f(offset + k as f64 * std::f64::consts::PI));
                }
                a = values.iter().copied().fold(f64::INFINITY, f64::min);
                b = values.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            }
            combine(
                json!(if a <= -1.0 { -1.0 } else { down(a) }),
                json!(if b >= 1.0 { 1.0 } else { up(b) }),
                &format!("{}_critical_points", op.to_ascii_lowercase()),
                std::slice::from_ref(v),
                (true, true),
            )
        }
        _ => unresolved("ELEMENTARY_FUNCTION_RANGE_UNRESOLVED", node.clone()),
    }
}

fn simplify(node: &Value) -> Value {
    let Some(object) = node.as_object() else {
        return node.clone();
    };
    let mut value = object
        .iter()
        .map(|(key, item)| {
            (
                key.clone(),
                if item.is_array() {
                    Value::Array(item.as_array().unwrap().iter().map(simplify).collect())
                } else if item.is_object() {
                    simplify(item)
                } else {
                    item.clone()
                },
            )
        })
        .collect::<serde_json::Map<_, _>>();
    let op = value.get("op").and_then(Value::as_str).unwrap_or("");
    let args = value
        .get("args")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    match (op, args.as_slice()) {
        ("Subtract", [a, b]) if a == b => {
            json!({"op":"Constant","value":0,"simplification":"sub_self"})
        }
        ("Add", [a, b])
            if a.get("op").and_then(Value::as_str) == Some("Constant")
                && a.get("value") == Some(&json!(0)) =>
        {
            b.clone()
        }
        ("Add", [a, b])
            if b.get("op").and_then(Value::as_str) == Some("Constant")
                && b.get("value") == Some(&json!(0)) =>
        {
            a.clone()
        }
        ("Multiply", [a, b])
            if [a, b].iter().any(|x| {
                x.get("op").and_then(Value::as_str) == Some("Constant")
                    && x.get("value") == Some(&json!(0))
            }) =>
        {
            json!({"op":"Constant","value":0})
        }
        ("Multiply", [a, b])
            if a.get("op").and_then(Value::as_str) == Some("Constant")
                && a.get("value") == Some(&json!(1)) =>
        {
            b.clone()
        }
        ("Multiply", [a, b])
            if b.get("op").and_then(Value::as_str) == Some("Constant")
                && b.get("value") == Some(&json!(1)) =>
        {
            a.clone()
        }
        _ => Value::Object(std::mem::take(&mut value)),
    }
}

fn condition(r: &Value) -> Value {
    let left = &r["left"];
    let right = &r["right"];
    let operator = r["operator"].as_str().unwrap_or("");
    let refinement = if r["left_node"].get("op").and_then(Value::as_str) == Some("FreeVariable")
        && resolved(right)
        && right["lower"] == right["upper"]
        && number(&right["lower"]).is_some()
    {
        json!([r["left_node"]["name"], operator, right["lower"]])
    } else {
        Value::Null
    };
    let Some((ll, lu, rl, ru)) = number(&left["lower"])
        .zip(number(&left["upper"]))
        .zip(number(&right["lower"]).zip(number(&right["upper"])))
        .map(|((ll, lu), (rl, ru))| (ll, lu, rl, ru))
    else {
        return json!({"status":"BRANCH_FEASIBILITY_UNRESOLVED","refinement":refinement});
    };
    if !resolved(left) || !resolved(right) {
        return json!({"status":"BRANCH_FEASIBILITY_UNRESOLVED","refinement":refinement});
    }
    let (proven_true, proven_false) = match operator {
        "Gt" | ">" => (ll > ru, lu <= rl),
        "GtE" | ">=" => (ll >= ru, lu < rl),
        "Lt" | "<" => (lu < rl, ll >= ru),
        "LtE" | "<=" => (lu <= rl, ll > ru),
        "Eq" | "==" => (
            left["lower"] == left["upper"]
                && right["lower"] == right["upper"]
                && left["lower"] == right["lower"],
            lu < rl || ru < ll,
        ),
        _ => return json!({"status":"BRANCH_FEASIBILITY_UNRESOLVED","refinement":refinement}),
    };
    json!({"status":if proven_true {"BRANCH_PROVEN_TRUE"} else if proven_false {"BRANCH_PROVEN_FALSE"} else {"BRANCH_INTERVAL_SPLIT"},"refinement":refinement})
}

fn refine(r: &Value) -> Value {
    let current = &r["value"];
    let operator = r["operator"].as_str().unwrap_or("");
    let truth = r["truth"].as_bool().unwrap_or(false);
    let cutoff = number(&r["cutoff"]);
    let Some(cutoff) = cutoff else {
        return current.clone();
    };
    let lower_side = match operator {
        "Gt" | ">" | "GtE" | ">=" => truth,
        "Lt" | "<" | "LtE" | "<=" => !truth,
        _ => return current.clone(),
    };
    let mut out = current.clone();
    if lower_side {
        out["lower"] = json!(number(&current["lower"]).map_or(cutoff, |x| x.max(cutoff)));
        out["lower_closed"] = json!(
            current["lower_closed"].as_bool().unwrap_or(true)
                && if truth {
                    matches!(operator, "GtE" | ">=")
                } else {
                    matches!(operator, "Lt" | "<")
                }
        );
    } else {
        out["upper"] = json!(number(&current["upper"]).map_or(cutoff, |x| x.min(cutoff)));
        out["upper_closed"] = json!(
            current["upper_closed"].as_bool().unwrap_or(true)
                && if truth {
                    matches!(operator, "LtE" | "<=")
                } else {
                    matches!(operator, "Gt" | ">")
                }
        );
    }
    out["provenance"]["path_refinement"] = json!([r["name"], operator, cutoff]);
    out
}

pub fn legacy_interval_operation(r: &Value) -> Result<Value> {
    match r.get("action").and_then(Value::as_str).unwrap_or("") {
        "META" => {
            let status = r["interval"]
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("");
            let valid = !matches!(
                status,
                "INTERVAL_UNRESOLVED" | "INTERVAL_INVALID" | "NUMERICALLY_OBSERVED_ONLY"
            );
            Ok(
                json!({"resolved":valid,"singleton":valid&&r["interval"].get("lower_closed").and_then(Value::as_bool).unwrap_or(true)&&r["interval"].get("upper_closed").and_then(Value::as_bool).unwrap_or(true)&&r["interval"]["lower"]==r["interval"]["upper"],"invalid_order":matches!((number(&r["interval"]["lower"]),number(&r["interval"]["upper"])),(Some(a),Some(b)) if a>b)}),
            )
        }
        "UNRESOLVED" => Ok(unresolved(
            r["code"].as_str().unwrap_or("INTERVAL_UNRESOLVED"),
            r.get("expression").cloned().unwrap_or(Value::Null),
        )),
        "SINGLETON" => Ok(singleton(
            r["value"].clone(),
            r.get("provenance")
                .cloned()
                .unwrap_or(json!({"kind":"EXACT_CONSTANT"})),
        )),
        "ADD" => Ok(add(&r["left"], &r["right"])),
        "NEG" => Ok(neg(&r["value"])),
        "SUB" => Ok(add(&r["left"], &neg(&r["right"]))),
        "MUL" => Ok(mul(&r["left"], &r["right"])),
        "DIV" => Ok(divide(&r["left"], &r["right"])),
        "ABS" => Ok(absolute(&r["value"])),
        "POWER" => Ok(r
            .get("exponent")
            .and_then(Value::as_i64)
            .map(|n| power(&r["value"], n))
            .unwrap_or_else(|| unresolved("POWER_DOMAIN_UNRESOLVED", Value::Null))),
        "HULL" => {
            let values = r
                .get("values")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter(resolved)
                .collect::<Vec<_>>();
            if values.is_empty() {
                return Ok(unresolved("INTERVAL_HULL_EMPTY", Value::Null));
            }
            if values
                .iter()
                .all(|v| number(&v["lower"]).is_some() && number(&v["upper"]).is_some())
            {
                Ok(combine(
                    json!(values
                        .iter()
                        .filter_map(|v| number(&v["lower"]))
                        .fold(f64::INFINITY, f64::min)),
                    json!(values
                        .iter()
                        .filter_map(|v| number(&v["upper"]))
                        .fold(f64::NEG_INFINITY, f64::max)),
                    r.get("rule")
                        .and_then(Value::as_str)
                        .unwrap_or("interval_hull"),
                    &values,
                    (true, true),
                ))
            } else {
                Ok(combine(
                    json!({"op":"Min","args":values.iter().map(|v|v["lower"].clone()).collect::<Vec<_>>() }),
                    json!({"op":"Max","args":values.iter().map(|v|v["upper"].clone()).collect::<Vec<_>>() }),
                    r.get("rule")
                        .and_then(Value::as_str)
                        .unwrap_or("interval_hull"),
                    &values,
                    (true, true),
                ))
            }
        }
        "CONTAINS_ZERO" => Ok(json!({"contains_zero":contains_zero(&r["value"])})),
        "ELEMENTARY" => Ok(elementary(
            r["function"].as_str().unwrap_or(""),
            &r["value"],
            &r["node"],
        )),
        "SIMPLIFY" => Ok(simplify(&r["node"])),
        "CONDITION" => Ok(condition(r)),
        "REFINE" => Ok(refine(r)),
        "COMBINE" => Ok(combine(
            r["lower"].clone(),
            r["upper"].clone(),
            r["rule"].as_str().unwrap_or("interval_rule"),
            r["inputs"].as_array().map(Vec::as_slice).unwrap_or(&[]),
            (
                r["lower_closed"].as_bool().unwrap_or(true),
                r["upper_closed"].as_bool().unwrap_or(true),
            ),
        )),
        "INPUT_RANGE" => {
            let mut out = combine(
                r["lower"].clone(),
                r["upper"].clone(),
                "user_input_range",
                &[],
                (
                    r["lower_closed"].as_bool().unwrap_or(true),
                    r["upper_closed"].as_bool().unwrap_or(true),
                ),
            );
            let exact = r["lower"] == r["upper"]
                && r["status"].as_str() != Some("NUMERICALLY_OBSERVED_ONLY");
            out["status"] = if exact {
                json!("EXACT_SINGLETON")
            } else {
                r["status"].clone()
            };
            out["proof_status"] = json!(if exact {
                "INTERVAL_PROPAGATION_KERNEL_VERIFIED"
            } else {
                "INTERVAL_PROPAGATION_SYMBOLIC"
            });
            out["provenance"] = r["provenance"].clone();
            out["assumptions"] = r["assumptions"].clone();
            out["dimensions"] = r["dimensions"].clone();
            Ok(out)
        }
        "CONSTRAINT_STATUS" => {
            let interval = &r["interval"];
            let values = (
                number(&interval["lower"]),
                number(&interval["upper"]),
                number(&r["lower"]),
                number(&r["upper"]),
            );
            let status = match values {
                (Some(il), Some(iu), Some(cl), Some(cu))
                    if resolved(interval) && il >= cl && iu <= cu =>
                {
                    "OUTPUT_RANGE_CONSTRAINT_PROVEN"
                }
                (Some(il), Some(iu), Some(cl), Some(cu))
                    if resolved(interval) && (iu < cl || il > cu) =>
                {
                    "OUTPUT_RANGE_CONSTRAINT_VIOLATED"
                }
                _ => "OUTPUT_RANGE_CONSTRAINT_NOT_PROVEN",
            };
            Ok(json!({"status":status}))
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_INTERVAL_ACTION:{action}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn division_zero_crossing_never_returns_finite() {
        let a = singleton(json!(1), json!({}));
        let b = json!({"lower":-1,"upper":1,"status":"USER_PROVIDED_INTERVAL"});
        let r = divide(&a, &b);
        assert_eq!(r["status"], json!("INTERVAL_UNRESOLVED"));
    }
    #[test]
    fn periodic_extrema_are_not_endpoint_only() {
        let v = json!({"lower":0.0,"upper":std::f64::consts::PI,"status":"USER_PROVIDED_INTERVAL"});
        let r = elementary("sin", &v, &json!({}));
        assert!(r["upper"].as_f64().unwrap() >= 1.0);
    }
}
