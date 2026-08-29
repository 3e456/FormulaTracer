//! Fail-closed representation decisions shared by scientific domains.
//!
//! This module does not introduce a second tensor/rotation algebra.  It checks
//! whether metadata and evidence authorize relations between existing IR
//! expressions.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

fn required_strings(request: &Value, names: &[&str]) -> Vec<String> {
    names
        .iter()
        .filter(|name| request.get(**name).and_then(Value::as_str).is_none())
        .map(|name| (*name).to_owned())
        .collect()
}

pub fn representation_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "FRAME_ADD" => {
            let left = request.get("left_frame").and_then(Value::as_str);
            let right = request.get("right_frame").and_then(Value::as_str);
            Ok(if left.is_some() && left == right {
                json!({"status":"FRAME_COMPATIBLE","frame":left})
            } else {
                json!({"status":"FRAME_MISMATCH","left_frame":left,"right_frame":right,
                    "operation_authorized":false})
            })
        }
        "FRAME_TRANSFORM" => {
            let source = request.get("source_frame").and_then(Value::as_str);
            let target = request.get("target_frame").and_then(Value::as_str);
            let verified = request.get("rotation_verified").and_then(Value::as_bool) == Some(true);
            Ok(
                if source.is_none() || target.is_none() || (!verified && source != target) {
                    json!({"status":"FRAME_TRANSFORM_UNRESOLVED","source_frame":source,
                    "target_frame":target,"remaining_obligations":["rotation_or_identity_evidence"]})
                } else {
                    json!({"status":"FRAME_TRANSFORM_AUTHORIZED","source_frame":source,
                    "target_frame":target,"relation":"EXACT_UNDER_ASSUMPTIONS"})
                },
            )
        }
        "CHECK_EULER_CONVENTION" => {
            let missing =
                required_strings(request, &["axis_order", "mode", "handedness", "angle_unit"]);
            let singular = request.get("gimbal_lock").and_then(Value::as_bool) == Some(true);
            Ok(if !missing.is_empty() {
                json!({"status":"EULER_CONVENTION_UNRESOLVED","missing":missing,
                    "equivalence_authorized":false})
            } else if singular {
                json!({"status":"EULER_REPRESENTATION_SINGULAR","reason":"GIMBAL_LOCK",
                    "equivalence_authorized":false})
            } else {
                json!({"status":"EULER_CONVENTION_RESOLVED","equivalence_authorized":true})
            })
        }
        "CHECK_ROTATION_MATRIX" => {
            let orthogonal = request
                .get("orthogonality_verified")
                .and_then(Value::as_bool)
                == Some(true);
            let determinant = request
                .get("determinant_one_verified")
                .and_then(Value::as_bool)
                == Some(true);
            Ok(if orthogonal && determinant {
                json!({"status":"SO3_ELIGIBLE","relation":"REPRESENTS_ROTATION"})
            } else {
                json!({"status":"SO3_ELIGIBILITY_UNRESOLVED","remaining_obligations":
                    [if orthogonal {Value::Null}else{json!("R^T R = I")},
                     if determinant {Value::Null}else{json!("det R = 1")}],
                    "equivalence_authorized":false})
            })
        }
        "QUATERNION_DOUBLE_COVER" => {
            let unit = request.get("unit_norm_verified").and_then(Value::as_bool) == Some(true);
            let antipodal =
                request.get("antipodal_verified").and_then(Value::as_bool) == Some(true);
            Ok(if unit && antipodal {
                json!({"status":"SAME_SO3_ROTATION","relation":"EXACT_UNDER_ASSUMPTIONS",
                    "quaternions_equal":false})
            } else {
                json!({"status":"QUATERNION_ROTATION_EQUIVALENCE_UNRESOLVED",
                    "remaining_obligations":["unit_norm","antipodal_relation"],
                    "equivalence_authorized":false})
            })
        }
        "QUATERNION_RENORMALIZATION" => {
            let nonzero = request.get("norm_nonzero").and_then(Value::as_bool) == Some(true);
            Ok(if nonzero {
                json!({"status":"RENORMALIZATION_ADMISSIBLE","relation":"ALGORITHMICALLY_REALIZED_BY",
                    "identity":false,"error_status":"ROUNDOFF_BOUND_REQUIRED"})
            } else {
                json!({"status":"RENORMALIZATION_UNRESOLVED","reason":"ZERO_NORM_POSSIBLE",
                    "operation_authorized":false})
            })
        }
        "LAPLACE_FOURIER_RESTRICTION" => {
            let convention =
                request.get("convention_resolved").and_then(Value::as_bool) == Some(true);
            let imaginary_axis = request
                .get("imaginary_axis_in_roc")
                .and_then(Value::as_bool)
                == Some(true);
            Ok(if convention && imaginary_axis {
                json!({"status":"TRANSFORM_RESTRICTION_APPLICABLE",
                    "relation":"EXACT_UNDER_ASSUMPTIONS"})
            } else {
                json!({"status":"TRANSFORM_RESTRICTION_UNRESOLVED",
                    "remaining_obligations":["transform_convention","imaginary_axis_in_region_of_convergence"],
                    "rewrite_authorized":false})
            })
        }
        "INVARIANT_STATUS" => {
            let model = request.get("model_conserved").and_then(Value::as_bool) == Some(true);
            let exact = request.get("numeric_exact").and_then(Value::as_bool) == Some(true);
            let bounded = request
                .get("numeric_bound_verified")
                .and_then(Value::as_bool)
                == Some(true);
            let observed = request.get("drift_observed").and_then(Value::as_bool) == Some(true);
            let status = if !model {
                "NOT_ESTABLISHED"
            } else if exact {
                "NUMERICALLY_PRESERVED_EXACTLY"
            } else if bounded {
                "NUMERICALLY_PRESERVED_WITH_BOUND"
            } else if observed {
                "NUMERICAL_DRIFT_OBSERVED"
            } else {
                "MODEL_CONSERVED"
            };
            Ok(json!({"status":status}))
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_REPRESENTATION_ACTION:{action}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ambiguous_euler_and_frame_mismatch_fail_closed() {
        let euler = representation_operation(&json!({"action":"CHECK_EULER_CONVENTION",
            "axis_order":"ZYX"}))
        .unwrap();
        assert_eq!(euler["status"], "EULER_CONVENTION_UNRESOLVED");
        let frame = representation_operation(&json!({"action":"FRAME_ADD",
            "left_frame":"World","right_frame":"Body"}))
        .unwrap();
        assert_eq!(frame["operation_authorized"], false);
    }
    #[test]
    fn transform_and_quaternion_require_evidence() {
        let transform = representation_operation(&json!({"action":"LAPLACE_FOURIER_RESTRICTION",
            "convention_resolved":true,"imaginary_axis_in_roc":false}))
        .unwrap();
        assert_eq!(transform["rewrite_authorized"], false);
        let zero = representation_operation(&json!({"action":"QUATERNION_RENORMALIZATION",
            "norm_nonzero":false}))
        .unwrap();
        assert_eq!(zero["operation_authorized"], false);
    }
}
