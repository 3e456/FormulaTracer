//! Native execution-dtype decisions for the Python numeric frontend.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn canonical(dtype: &str) -> &str {
    match dtype {
        "int" => "python.int",
        "float" => "python.float",
        "complex" => "python.complex",
        "boolean" => "bool",
        "double" => "float64",
        "single" => "float32",
        "np.bool_" | "numpy.bool_" => "bool",
        value if value.starts_with("np.") || value.starts_with("numpy.") => {
            value.rsplit('.').next().unwrap_or("unknown")
        }
        value => value,
    }
}
fn execution_type(
    dtype: &str,
    container: &str,
    shape: Value,
    dimensions: Value,
    provenance: &str,
) -> Value {
    let dtype = canonical(dtype);
    let (name, kind, bits, signed, domain, overflow, underflow) = match dtype {
        "bool" => (
            dtype,
            "bool",
            json!(1),
            Value::Null,
            "Boolean",
            "NOT_APPLICABLE",
            "NOT_APPLICABLE",
        ),
        "int8" | "int16" | "int32" | "int64" => (
            dtype,
            "integer",
            json!(dtype[3..].parse::<u64>().unwrap()),
            json!(true),
            "Integer",
            "MODULAR_WRAP",
            "NOT_APPLICABLE",
        ),
        "uint8" | "uint16" | "uint32" | "uint64" => (
            dtype,
            "integer",
            json!(dtype[4..].parse::<u64>().unwrap()),
            json!(false),
            "Natural",
            "MODULAR_WRAP",
            "NOT_APPLICABLE",
        ),
        "float16" | "float32" | "float64" => (
            dtype,
            "float",
            json!(dtype[5..].parse::<u64>().unwrap()),
            json!(true),
            "Real",
            "IEEE_INFINITY",
            "GRADUAL_SUBNORMAL",
        ),
        "complex64" | "complex128" => (
            dtype,
            "complex",
            json!(dtype[7..].parse::<u64>().unwrap()),
            json!(true),
            "Complex",
            "IEEE_INFINITY",
            "GRADUAL_SUBNORMAL",
        ),
        "python.int" => (
            dtype,
            "integer",
            Value::Null,
            json!(true),
            "Integer",
            "UNBOUNDED_INTEGER",
            "NOT_APPLICABLE",
        ),
        "python.float" => (
            dtype,
            "float",
            json!(64),
            json!(true),
            "Real",
            "IEEE_INFINITY",
            "GRADUAL_SUBNORMAL",
        ),
        "python.complex" => (
            dtype,
            "complex",
            json!(128),
            json!(true),
            "Complex",
            "IEEE_INFINITY",
            "GRADUAL_SUBNORMAL",
        ),
        _ => (
            "unknown",
            "unknown",
            Value::Null,
            Value::Null,
            "Unknown",
            "UNRESOLVED",
            "UNRESOLVED",
        ),
    };
    json!({"dtype":name,"kind":kind,"bits":bits,"signed":signed,"mathematical_domain":domain,"container":container,
        "shape":shape,"dimensions":dimensions,"overflow":overflow,"underflow":underflow,"provenance":provenance})
}
fn dtype(v: &Value) -> &str {
    v.get("dtype").and_then(Value::as_str).unwrap_or("unknown")
}
fn kind(v: &Value) -> &str {
    v.get("kind").and_then(Value::as_str).unwrap_or("unknown")
}
fn bits(v: &Value) -> u64 {
    v.get("bits").and_then(Value::as_u64).unwrap_or(0)
}
fn signed(v: &Value) -> Option<bool> {
    v.get("signed").and_then(Value::as_bool)
}
fn result_type(dtype: &str, left: &Value, right: &Value, provenance: &str) -> Value {
    let lc = left
        .get("container")
        .and_then(Value::as_str)
        .unwrap_or("python.scalar");
    let container = if lc != "python.scalar" {
        lc
    } else {
        right
            .get("container")
            .and_then(Value::as_str)
            .unwrap_or("python.scalar")
    };
    let shape = left
        .get("shape")
        .filter(|v| !v.is_null())
        .or_else(|| right.get("shape"))
        .cloned()
        .unwrap_or(Value::Null);
    let dimensions = left
        .get("dimensions")
        .filter(|v| !v.is_null())
        .or_else(|| right.get("dimensions"))
        .cloned()
        .unwrap_or(Value::Null);
    execution_type(dtype, container, shape, dimensions, provenance)
}
fn promote(left: &Value, right: &Value) -> Value {
    let resolved: Option<(String, &str)> = if dtype(left) == "unknown" || dtype(right) == "unknown"
    {
        None
    } else if dtype(left).starts_with("python.") && dtype(right).starts_with("python.") {
        let rank = |v: &str| match v {
            "python.int" => 0,
            "python.float" => 1,
            "python.complex" => 2,
            _ => -1,
        };
        Some((
            (if rank(dtype(left)) >= rank(dtype(right)) {
                dtype(left)
            } else {
                dtype(right)
            })
            .into(),
            "PYTHON_NUMERIC_TOWER",
        ))
    } else if dtype(left).starts_with("python.") != dtype(right).starts_with("python.") {
        let (scalar, concrete) = if dtype(left).starts_with("python.") {
            (left, right)
        } else {
            (right, left)
        };
        let rank = |v: &str| match v {
            "bool" => 0,
            "integer" => 1,
            "float" => 2,
            "complex" => 3,
            _ => -1,
        };
        if rank(kind(scalar)) <= rank(kind(concrete)) {
            Some((
                dtype(concrete).into(),
                "WEAK_PYTHON_SCALAR_REQUIRES_REPRESENTABILITY",
            ))
        } else if kind(scalar) == "float" {
            Some(("float64".into(), "PYTHON_SCALAR_KIND_WIDENING"))
        } else if kind(scalar) == "complex" {
            Some((
                (if bits(concrete) <= 32 {
                    "complex64"
                } else {
                    "complex128"
                })
                .into(),
                "PYTHON_SCALAR_KIND_WIDENING",
            ))
        } else {
            Some((
                dtype(concrete).into(),
                "WEAK_PYTHON_SCALAR_REQUIRES_REPRESENTABILITY",
            ))
        }
    } else if dtype(left) == "bool" {
        Some((dtype(right).into(), "BOOL_PROMOTION"))
    } else if dtype(right) == "bool" {
        Some((dtype(left).into(), "BOOL_PROMOTION"))
    } else if kind(left) == "complex" || kind(right) == "complex" {
        let width = [left, right]
            .iter()
            .map(|v| {
                if kind(v) == "complex" {
                    bits(v)
                } else {
                    2 * bits(v)
                }
            })
            .max()
            .unwrap_or(0);
        Some((
            (if width > 64 {
                "complex128"
            } else {
                "complex64"
            })
            .into(),
            "COMPLEX_WIDENING",
        ))
    } else if kind(left) == "float" || kind(right) == "float" {
        let width = bits(left).max(bits(right));
        Some((
            (if width > 32 {
                "float64"
            } else if width > 16 {
                "float32"
            } else {
                "float16"
            })
            .into(),
            "FLOAT_WIDENING",
        ))
    } else if kind(left) == "integer" && kind(right) == "integer" {
        if signed(left) == signed(right) {
            Some((
                format!(
                    "{}{}",
                    if signed(left) == Some(true) {
                        "int"
                    } else {
                        "uint"
                    },
                    bits(left).max(bits(right))
                ),
                "INTEGER_WIDENING",
            ))
        } else {
            let (s, u) = if signed(left) == Some(true) {
                (left, right)
            } else {
                (right, left)
            };
            if bits(s) > bits(u) {
                Some((dtype(s).into(), "SIGNED_UNSIGNED_SAFE_WIDENING"))
            } else if let Some(w) = [16, 32, 64].into_iter().find(|w| *w > bits(u)) {
                Some((format!("int{w}"), "SIGNED_UNSIGNED_SAFE_WIDENING"))
            } else {
                Some(("float64".into(), "SIGNED_UNSIGNED_NO_INTEGER_SUPERTYPE"))
            }
        }
    } else {
        None
    };
    match resolved {
        Some((name, rule)) => {
            json!({"status":"RESOLVED","rule":rule,"type":result_type(&name,left,right,"promotion rule")})
        }
        None => {
            json!({"status":"UNRESOLVED","code":"PROMOTION_UNRESOLVED","message":format!("no rule for {} and {}",dtype(left),dtype(right)),"type":execution_type("unknown","python.scalar",Value::Null,Value::Null,"PROMOTION_UNRESOLVED")})
        }
    }
}
fn call_result(request: &Value) -> Value {
    let short = request.get("short").and_then(Value::as_str).unwrap_or("");
    let name = request.get("name").and_then(Value::as_str).unwrap_or(short);
    let args = request
        .get("args")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let receiver = request.get("receiver").filter(|v| !v.is_null()).cloned();
    let mut operands = Vec::new();
    if let Some(v) = receiver.clone() {
        operands.push(v)
    }
    operands.extend(args.clone());
    let casts = [
        "bool",
        "int",
        "float",
        "complex",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "float16",
        "float32",
        "float64",
        "complex64",
        "complex128",
    ];
    if casts.contains(&short) && !args.is_empty() {
        let source = &args[0];
        let target = execution_type(
            short,
            source["container"].as_str().unwrap_or("python.scalar"),
            source["shape"].clone(),
            source["dimensions"].clone(),
            "explicit constructor cast",
        );
        return json!({"status":"RESOLVED","type":target,"cast":{"source":dtype(source),"target":target["dtype"],"explicit":true,"exact":if kind(&target)=="integer"{"EXACT_IF_IN_RANGE"}else{"ROUNDING_OR_RANGE_CONDITIONS_REQUIRED"}}});
    }
    if let ("astype", Some(source)) = (short, receiver) {
        let requested = request
            .get("dtype")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let target = execution_type(
            requested,
            source["container"].as_str().unwrap_or("python.scalar"),
            source["shape"].clone(),
            source["dimensions"].clone(),
            "explicit astype cast",
        );
        return json!({"status":"RESOLVED","type":target,"cast":{"source":dtype(&source),"target":target["dtype"],"explicit":true,"exact":"ROUNDING_OR_RANGE_CONDITIONS_REQUIRED"}});
    }
    if ["array", "asarray", "DataArray", "from_array"].contains(&short) && !args.is_empty() {
        let source = &args[0];
        let container = if short == "DataArray" {
            "xarray.DataArray"
        } else if short == "from_array" {
            "dask.array.Array"
        } else {
            "numpy.ndarray"
        };
        let requested = request.get("dtype").and_then(Value::as_str);
        let target = if let Some(d) = requested {
            execution_type(
                d,
                container,
                source["shape"].clone(),
                request.get("dimensions").cloned().unwrap_or(Value::Null),
                "array constructor dtype",
            )
        } else {
            let mut v = source.clone();
            v["container"] = json!(container);
            v["dimensions"] = request.get("dimensions").cloned().unwrap_or(Value::Null);
            v
        };
        let cast = if requested.is_some() && dtype(&target) != dtype(source) {
            json!({"source":dtype(source),"target":dtype(&target),"explicit":true,"exact":"ROUNDING_OR_RANGE_CONDITIONS_REQUIRED"})
        } else {
            Value::Null
        };
        return json!({"status":"RESOLVED","type":target,"cast":cast});
    }
    if ["zeros", "ones", "empty", "full"].contains(&short) {
        let requested = request
            .get("dtype")
            .and_then(Value::as_str)
            .unwrap_or("float64");
        let container = if name.starts_with("da.") || name.starts_with("dask.array.") {
            "dask.array.Array"
        } else {
            "numpy.ndarray"
        };
        return json!({"status":"RESOLVED","type":execution_type(requested,container,request.get("literal_shape").cloned().unwrap_or(Value::Null),Value::Null,"array creation rule")});
    }
    if [
        "sum",
        "prod",
        "dot",
        "matmul",
        "einsum",
        "where",
        "clip",
        "abs",
        "sqrt",
        "log",
        "exp",
        "power",
        "reshape",
        "transpose",
        "diff",
        "gradient",
        "sel",
        "isel",
        "rename",
        "broadcast",
    ]
    .contains(&short)
        && !operands.is_empty()
    {
        if short == "where" && operands.len() >= 3 {
            return promote(&operands[operands.len() - 2], &operands[operands.len() - 1]);
        }
        return json!({"status":"RESOLVED","type":operands[0]});
    }
    if short == "mean" && !operands.is_empty() {
        let source = &operands[0];
        let value = if ["float", "complex"].contains(&kind(source)) {
            source.clone()
        } else {
            execution_type(
                "float64",
                source["container"].as_str().unwrap_or("python.scalar"),
                source["shape"].clone(),
                source["dimensions"].clone(),
                "mean accumulator/result rule",
            )
        };
        return json!({"status":"RESOLVED","type":value});
    }
    json!({"status":"UNRESOLVED","code":"CALL_DTYPE_UNRESOLVED","message":format!("dtype contract unavailable for {name}"),"type":execution_type("unknown","python.scalar",Value::Null,Value::Null,"CALL_DTYPE_UNRESOLVED")})
}
pub fn legacy_numeric_types_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "EXECUTION_TYPE" => Ok(execution_type(
            request
                .get("dtype")
                .and_then(Value::as_str)
                .unwrap_or("unknown"),
            request
                .get("container")
                .and_then(Value::as_str)
                .unwrap_or("python.scalar"),
            request.get("shape").cloned().unwrap_or(Value::Null),
            request.get("dimensions").cloned().unwrap_or(Value::Null),
            request
                .get("provenance")
                .and_then(Value::as_str)
                .unwrap_or("declared"),
        )),
        "INFER_VALUE" => {
            let p = request
                .get("profile")
                .ok_or_else(|| invalid("VALUE_PROFILE_REQUIRED"))?;
            let d = if p["has_complex"] == json!(true) {
                "python.complex"
            } else if p["has_float"] == json!(true) {
                "python.float"
            } else if p["all_bool"] == json!(true) {
                "bool"
            } else if p["all_int"] == json!(true) {
                "python.int"
            } else {
                "unknown"
            };
            Ok(execution_type(
                d,
                p["container"].as_str().unwrap_or("python.scalar"),
                p["shape"].clone(),
                Value::Null,
                "runtime value inference",
            ))
        }
        "PROMOTE" => Ok(promote(
            request
                .get("left")
                .ok_or_else(|| invalid("LEFT_TYPE_REQUIRED"))?,
            request
                .get("right")
                .ok_or_else(|| invalid("RIGHT_TYPE_REQUIRED"))?,
        )),
        "BINARY_RESULT" => {
            let left = request
                .get("left")
                .ok_or_else(|| invalid("LEFT_TYPE_REQUIRED"))?;
            let right = request
                .get("right")
                .ok_or_else(|| invalid("RIGHT_TYPE_REQUIRED"))?;
            let mut decision = promote(left, right);
            decision["promotion_type"] = decision["type"].clone();
            if decision["status"] == json!("RESOLVED")
                && request.get("operator").and_then(Value::as_str) == Some("Div")
                && decision["type"]["kind"] == json!("integer")
            {
                let value = &decision["type"];
                decision["type"] = execution_type(
                    if value["container"]
                        .as_str()
                        .unwrap_or("")
                        .starts_with("python")
                    {
                        "python.float"
                    } else {
                        "float64"
                    },
                    value["container"].as_str().unwrap_or("python.scalar"),
                    value["shape"].clone(),
                    value["dimensions"].clone(),
                    "true division",
                );
            }
            Ok(decision)
        }
        "BOOLEAN_RESULT" => {
            let container = if request
                .get("vectorized")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                "numpy.ndarray"
            } else {
                "python.scalar"
            };
            Ok(execution_type(
                "bool",
                container,
                Value::Null,
                Value::Null,
                "boolean operation",
            ))
        }
        "ANALYSIS_SUMMARY" => {
            let outputs = request
                .get("outputs")
                .and_then(Value::as_object)
                .map(|v| !v.is_empty())
                .unwrap_or(false);
            let diagnostics = request
                .get("diagnostics")
                .and_then(Value::as_array)
                .map(|v| !v.is_empty())
                .unwrap_or(true);
            let mut domains = request
                .get("domains")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            domains.retain(|v| v.as_str() != Some("Unknown"));
            domains.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
            domains.dedup();
            Ok(
                json!({"status":if outputs&&!diagnostics{"TYPE_RESOLVED"}else{"TYPE_UNRESOLVED"},"mathematical_domain":{"category":"symbolic_numeric","domains":domains,"separation":"execution dtype is metadata and does not replace Mathematical Expression IR"}}),
            )
        }
        "CALL_RESULT" => Ok(call_result(request)),
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_NUMERIC_TYPES_ACTION:{action}"
        ))),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn signed_unsigned_widens() {
        let a = execution_type("int16", "python.scalar", Value::Null, Value::Null, "x");
        let b = execution_type("uint16", "python.scalar", Value::Null, Value::Null, "x");
        assert_eq!(promote(&a, &b)["type"]["dtype"], "int32");
    }
}
