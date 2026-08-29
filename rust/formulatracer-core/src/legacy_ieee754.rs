//! IEEE-754 execution contracts, deliberately separate from mathematical equality.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Map, Value};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn format(dtype: &str) -> Option<Value> {
    match dtype {
        "float16" => Some(json!({"radix":2,"precision_bits":11,"exponent_bits":5})),
        "float32" => Some(json!({"radix":2,"precision_bits":24,"exponent_bits":8})),
        "float64" | "python.float" => {
            Some(json!({"radix":2,"precision_bits":53,"exponent_bits":11}))
        }
        "complex64" => Some(json!({"component_dtype":"float32"})),
        "complex128" => Some(json!({"component_dtype":"float64"})),
        "python.complex" => Some(json!({"component_dtype":"python.float"})),
        _ => None,
    }
}
fn risk(risks: &[Value], code: &str) -> bool {
    risks
        .iter()
        .any(|x| x.get("code").and_then(Value::as_str) == Some(code))
}
pub fn legacy_ieee754_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "ANALYZE" => {
            let mut formats = Map::new();
            for (prefix, key) in [("", "input_dtypes"), ("output:", "output_dtypes")] {
                for (name, dtype) in request
                    .get(key)
                    .and_then(Value::as_object)
                    .into_iter()
                    .flatten()
                {
                    if let Some(mut metadata) = dtype.as_str().and_then(format) {
                        metadata["dtype"] = dtype.clone();
                        for flag in [
                            "nan",
                            "positive_infinity",
                            "negative_infinity",
                            "signed_zero",
                            "subnormal",
                        ] {
                            metadata[flag] = json!(true);
                        }
                        formats.insert(format!("{prefix}{name}"), metadata);
                    }
                }
            }
            let floating = !formats.is_empty();
            let operations = request
                .get("operations")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let mut risks = request
                .get("risks")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let implementation = &request["implementation_shape"];
            let theory = &request["theory_shape"];
            let mathematical_match = request
                .get("mathematical_match")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let reassociated = mathematical_match
                && !implementation.is_null()
                && !theory.is_null()
                && implementation != theory;
            if reassociated {
                risks.push(json!({"code":"REAL_EQUIVALENT_FLOAT_REASSOCIATION","implementation_shape":implementation,"theory_shape":theory,"message":"real-algebra equivalence does not establish floating execution equivalence"}));
            }
            let mathematical = if mathematical_match {
                "ESTABLISHED"
            } else {
                "NOT_ESTABLISHED"
            };
            let numerical = if !floating {
                "NOT_APPLICABLE"
            } else if reassociated || risk(&risks, "FLOAT_REDUCTION_REORDERING") {
                "NOT_ESTABLISHED"
            } else if implementation == theory && !implementation.is_null() {
                "ESTABLISHED_UNDER_CONTRACT"
            } else {
                "NOT_ESTABLISHED"
            };
            let mode = request
                .get("rounding_mode")
                .and_then(Value::as_str)
                .unwrap_or("UNKNOWN");
            let diagnostics = if floating && mode == "UNKNOWN" {
                vec![
                    json!({"code":"ROUNDING_MODE_UNRESOLVED","message":"floating rounding mode is not constrained"}),
                ]
            } else {
                vec![]
            };
            let status = if diagnostics.is_empty() {
                "IEEE754_CONTRACT_RESOLVED"
            } else {
                "IEEE754_CONTRACT_UNRESOLVED"
            };
            Ok(
                json!({"status":status,"formats":formats,"operations":operations,"evaluation_order":"PYTHON_EXPRESSION_LEFT_TO_RIGHT; LIBRARY_REDUCTIONS_CONTRACT_BOUND","rounding_contract":{"mode":mode,"provenance":"caller/default execution contract","kernel_model":"ABSTRACT_ROUNDING_ONLY"},"special_value_observations":request.get("special_value_observations").cloned().unwrap_or(json!([])),"non_associativity_risks":risks,"fma_contract":"EXPLICIT_FMA_RECORDED; BACKEND_CONTRACTION_UNRESOLVED","equivalence":{"MATHEMATICAL_EQUIVALENCE":{"status":mathematical,"basis":"Mathematical Expression IR comparison"},"NUMERIC_EXECUTION_EQUIVALENCE":{"status":numerical,"basis":"operation grouping, dtype, rounding, evaluation-order, and FMA contracts"},"BITWISE_EQUIVALENCE":{"status":"NOT_APPLICABLE","basis":"theory formula is abstract and has no executable bit pattern"}},"diagnostics":diagnostics}),
            )
        }
        "CLASSIFY_VALUE" => {
            let kind = request["kind"].as_str().unwrap_or("");
            let status = match kind {
                "NaN" => "FLOATING_NAN",
                "+Inf" | "-Inf" => "FLOATING_INFINITY",
                "SIGNED_NEGATIVE_ZERO" | "SIGNED_POSITIVE_ZERO" => {
                    "FLOATING_EXECUTION_EXACT_FOR_REPRESENTED_INPUT"
                }
                "SUBNORMAL_BINARY64" => "FLOATING_UNDERFLOW",
                _ => "FLOATING_SEMANTICS_UNRESOLVED",
            };
            Ok(
                json!({"status":status,"ordinary_real":false,"mathematical_infinity":false,"signed_zero_preserved":kind.contains("ZERO")}),
            )
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_IEEE754_ACTION:{action}"
        ))),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn specials_never_become_reals() {
        for kind in ["NaN", "+Inf", "-Inf"] {
            let r =
                legacy_ieee754_operation(&json!({"action":"CLASSIFY_VALUE","kind":kind})).unwrap();
            assert_eq!(r["ordinary_real"], json!(false));
            assert_eq!(r["mathematical_infinity"], json!(false));
        }
    }
}
