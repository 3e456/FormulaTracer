//! Probability contract semantics. Statistical evidence is never promoted to exact proof.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn stable_id(prefix: &str, value: &Value) -> String {
    let digest = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(value).unwrap_or_default())
    );
    format!("{prefix}:{}", &digest[..16])
}
fn classify(api: &str, parameters: &Value) -> Value {
    let (kind, support) = match api {
        "numpy.random.normal"
        | "numpy.random.Generator.normal"
        | "scipy.stats.norm.rvs"
        | "jax.random.normal"
        | "torch.normal" => ("Normal", json!(["-inf", "inf"])),
        "numpy.random.uniform" | "jax.random.uniform" | "cupy.random.uniform" => {
            ("Uniform", json!("parameterized_interval"))
        }
        "torch.rand" => ("Uniform", json!([0.0, 1.0])),
        "numpy.random.randint" | "numpy.random.Generator.integers" => {
            ("DiscreteUniform", json!("parameterized_integers"))
        }
        "numpy.random.choice" => ("Categorical", json!("finite_categories")),
        "random.sample" => ("FinitePopulationSample", json!("finite_population")),
        "numpy.random.permutation" => ("RandomPermutation", json!("finite_population")),
        _ => return Value::Null,
    };
    json!({"distribution_id":stable_id("distribution",&json!([api,parameters])),"kind":kind,"api":api,"parameters":parameters,"support":support,"contract_status":"REFERENCE_CONTRACT"})
}
fn estimator(expression: &Value, target: &Value) -> Value {
    let op = expression.get("op").and_then(Value::as_str).unwrap_or("");
    let reduction = expression
        .get("reduction")
        .and_then(Value::as_str)
        .unwrap_or("");
    let args = expression.get("args").and_then(Value::as_array);
    let divide_sum = op == "Divide"
        && args
            .and_then(|a| a.first())
            .and_then(|x| x.get("op"))
            .and_then(Value::as_str)
            .is_some_and(|x| matches!(x, "FiniteSum" | "Reduce"));
    let kind = if op == "Mean" || (op == "Reduce" && reduction == "Mean") || divide_sum {
        "SAMPLE_MEAN"
    } else {
        "UNKNOWN_ESTIMATOR"
    };
    let sample_size = if divide_sum {
        args.and_then(|a| a.get(1)).cloned().unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let has_target = !target.is_null();
    json!({"estimator_id":stable_id("estimator",expression),"expression":expression,"kind":kind,"sample_size":sample_size,"target":target,"status":if kind=="SAMPLE_MEAN"&&has_target{"ESTIMATOR_TARGET_IDENTIFIED"}else{"ESTIMATOR_TARGET_UNRESOLVED"}})
}
fn monte_carlo(r: &Value) -> Result<Value> {
    let values = r["samples"]
        .as_array()
        .ok_or_else(|| invalid("MONTE_CARLO_SAMPLES_REQUIRED"))?
        .iter()
        .map(|v| {
            v.as_f64()
                .ok_or_else(|| invalid("MONTE_CARLO_FINITE_SAMPLE_REQUIRED"))
        })
        .collect::<Result<Vec<_>>>()?;
    if values.is_empty() {
        return Err(invalid("MONTE_CARLO_NONEMPTY_SAMPLE_REQUIRED"));
    }
    let n = values.len();
    let estimate = values.iter().sum::<f64>() / n as f64;
    let variance = if n > 1 {
        Some(values.iter().map(|x| (x - estimate).powi(2)).sum::<f64>() / n as f64)
    } else {
        None
    };
    let target = r.get("target").cloned().unwrap_or(Value::Null);
    let expression = json!({"op":"Mean","input":{"op":"SampleSequence"}});
    let est = estimator(&expression, &target);
    let alpha = r["alpha"].as_f64().unwrap_or(0.05);
    let support = r["support"]
        .as_array()
        .and_then(|s| Some((s.first()?.as_f64()?, s.get(1)?.as_f64()?)));
    let valid = support.is_some_and(|(a, b)| a.is_finite() && b.is_finite() && a < b)
        && alpha > 0.0
        && alpha < 1.0;
    let (error, enclosure, status) = if valid {
        let (a, b) = support.unwrap();
        let epsilon = (b - a) * (2.0 / alpha).ln().sqrt() / (2.0 * n as f64).sqrt();
        (
            json!({"epsilon":epsilon,"alpha":alpha,"method":"HOEFFDING_REFERENCE_THEOREM","assumptions":["IID","bounded support","sample mean"],"status":"REFERENCE_THEOREM_BOUND"}),
            json!({"lower":estimate-epsilon,"upper":estimate+epsilon,"coverage_probability":1.0-alpha,"claim":format!("P(|estimate - target| <= {epsilon:.12}) >= {:.12}",1.0-alpha),"proof_authority":"REFERENCE_THEOREM"}),
            "MONTE_CARLO_PROBABILISTIC_ENCLOSURE_UNDER_ASSUMPTIONS",
        )
    } else {
        (
            json!({"epsilon":"inf","alpha":alpha,"method":"UNRESOLVED","assumptions":["bounded support and IID required"],"status":"SAMPLING_ERROR_UNRESOLVED"}),
            Value::Null,
            "MONTE_CARLO_ENCLOSURE_UNRESOLVED",
        )
    };
    Ok(
        json!({"empirical":{"estimator":est,"estimate":estimate,"sample_size":n,"observed_variance":variance,"evidence_level":"NUMERICALLY_CHECKED"},"monte_carlo":{"estimate":estimate,"target":target,"sample_size":n,"sampling_error":error,"enclosure":enclosure,"status":status}}),
    )
}
pub fn legacy_probability_operation(r: &Value) -> Result<Value> {
    match r["action"].as_str().unwrap_or("") {
        "CLASSIFY_SOURCE" => Ok(classify(
            r["api"].as_str().unwrap_or(""),
            r.get("parameters").unwrap_or(&Value::Null),
        )),
        "EXTRACT_ESTIMATOR" => Ok(estimator(
            &r["expression"],
            r.get("target").unwrap_or(&Value::Null),
        )),
        "MONTE_CARLO" => monte_carlo(r),
        "AUDIT_STATUS" => {
            let status = if r["empirical_status"].as_str()
                == Some("DISTRIBUTION_EMPIRICALLY_INCONSISTENT")
            {
                "PROBABILITY_AUDIT_FAILED"
            } else if r["empirical_status"].as_str() == Some("DISTRIBUTION_EMPIRICALLY_SUPPORTED") {
                "PROBABILITY_AUDIT_EMPIRICALLY_SUPPORTED"
            } else if r["known_distribution"].as_bool().unwrap_or(false) {
                "PROBABILITY_AUDIT_REFERENCE_CONTRACT"
            } else {
                "PROBABILITY_AUDIT_UNRESOLVED"
            };
            Ok(json!({"status":status}))
        }
        other => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_PROBABILITY_ACTION:{other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unknown_dependence_never_certifies_monte_carlo_exactly() {
        let r = monte_carlo(
            &json!({"samples":[1.0,2.0],"support":[0.0,3.0],"alpha":0.05,"target":null}),
        )
        .unwrap();
        assert_eq!(
            r["monte_carlo"]["status"],
            "MONTE_CARLO_PROBABILISTIC_ENCLOSURE_UNDER_ASSUMPTIONS"
        );
        assert_ne!(
            r["monte_carlo"]["sampling_error"]["status"],
            "KERNEL_VERIFIED"
        );
    }
}
