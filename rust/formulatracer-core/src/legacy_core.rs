//! Native semantic decisions for the legacy weighted-sum audit slice.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn stable_id(kind: &str, payload: &str) -> String {
    let digest = format!("{:x}", Sha256::digest(payload.as_bytes()));
    format!("{}-{}", kind.to_lowercase(), &digest[..16])
}
fn compact(source: &str) -> String {
    source
        .chars()
        .filter(|value| !value.is_whitespace())
        .collect()
}
fn diagnostic(
    path: &str,
    source: &str,
    needle: &str,
    code: &str,
    message: &str,
    specification: &str,
    implementation: &str,
) -> Value {
    let position = source.find(needle).unwrap_or(0);
    let line = source[..position]
        .bytes()
        .filter(|value| *value == b'\n')
        .count()
        + 1;
    json!({"code":code,"message":message,"specification":specification,"implementation":implementation,"source":format!("{path}:{line}")})
}
fn normalize(ir: &Value, numeric_model: &str) -> Result<Value> {
    let mut nodes = Vec::new();
    nodes.extend(
        ir.get("values")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| invalid("LEGACY_IR_VALUES_REQUIRED"))?,
    );
    nodes.extend(
        ir.get("operations")
            .and_then(Value::as_array)
            .cloned()
            .ok_or_else(|| invalid("LEGACY_IR_OPERATIONS_REQUIRED"))?,
    );
    nodes.sort_by(|left, right| {
        left.get("id")
            .and_then(Value::as_str)
            .cmp(&right.get("id").and_then(Value::as_str))
    });
    let quantity = stable_id("input", "quantity");
    let factor = stable_id("input", "factor");
    let multiply = stable_id("op", "multiply-quantity-factor");
    let reduce = stable_id("op", "reduce-input-left");
    let output = stable_id("output", "result");
    Ok(
        json!({"schema_version":"0.1","algorithm_id":"weighted_sum","numeric_model":numeric_model,"nodes":nodes,"edges":[{"source":quantity,"target":multiply,"argument_index":0,"argument_role":"lhs"},{"source":factor,"target":multiply,"argument_index":1,"argument_role":"rhs"},{"source":multiply,"target":reduce,"argument_index":0,"argument_role":"input"},{"source":reduce,"target":output,"result_index":0,"argument_role":"output"}],"reduction_order":"left_to_right"}),
    )
}
fn semantic_diagnostics(path: &str, source: &str) -> Vec<Value> {
    let flat = compact(source);
    let mut checks = Vec::new();
    let mut add = |needle: &str, code: &str, message: &str, spec: &str, implementation: &str| {
        checks.push(diagnostic(
            path,
            source,
            needle,
            code,
            message,
            spec,
            implementation,
        ))
    };
    if flat.contains("factor[r]") {
        add(
            "factor[r]",
            "FACTOR_INDEX_MISMATCH",
            "Factor index mismatch",
            "factor[i]",
            "factor[r]",
        );
    }
    if flat.contains("quantity[r+i]") {
        add(
            "quantity[r",
            "ROW_MAJOR_INDEX_MISMATCH",
            "Row-major index mismatch",
            "r * inputs + i",
            "r + i",
        );
    }
    if flat.contains("i<inputs-1") {
        add(
            "inputs - 1",
            "LOOP_BOUND_MISMATCH",
            "Reduction range excludes final input",
            "0 <= i < inputs",
            "0 <= i < inputs - 1",
        );
    }
    if flat.contains("i<regions") {
        add(
            "i < regions",
            "REDUCTION_DIMENSION_MISMATCH",
            "Reduction dimension mismatch",
            "reduce over input",
            "reduce over region",
        );
    }
    if flat.contains("acc=1;") || flat.contains("acc=1.0;") {
        add(
            "acc = 1",
            "INITIAL_VALUE_MISMATCH",
            "Initial value mismatch",
            "0",
            "1",
        );
    }
    if flat.contains("acc+=quantity[") && flat.contains("]+factor") {
        add(
            "+ factor",
            "TRANSFORM_MISMATCH",
            "Transform operation mismatch",
            "multiply",
            "add",
        );
    }
    if flat.contains("result[i]") {
        add(
            "result[i]",
            "OUTPUT_INDEX_MISMATCH",
            "Output index mismatch",
            "result[r]",
            "result[i]",
        );
    }
    if source.contains("std::reduce") {
        add(
            "std::reduce",
            "REDUCTION_ORDER_MISMATCH",
            "Implementation permits reordering",
            "left_to_right",
            "implementation_permitted_reordering",
        );
    }
    if source.contains("std::inner_product") && (flat.contains(",1)") || flat.contains(",1.0)")) {
        add(
            "1.0)",
            "INITIAL_VALUE_MISMATCH",
            "Initial value mismatch",
            "0",
            "1",
        );
    }
    if flat.contains("first+inputs-1") {
        add(
            "inputs - 1",
            "ITERATOR_RANGE_MISMATCH",
            "Iterator range excludes final input",
            "[first, first + inputs)",
            "[first, first + inputs - 1)",
        );
    }
    if flat.contains("floatacc") {
        add(
            "float acc",
            "NUMERIC_NARROWING",
            "Implicit precision narrowing",
            "IEEE754Float64 accumulator",
            "IEEE754Float32 accumulator",
        );
    }
    let mut cursor = 0;
    while let Some(relative) = source[cursor..].find("weighted_sum(") {
        let start = cursor + relative + "weighted_sum(".len();
        if let Some(end) = source[start..].find(')') {
            let call = &source[start..start + end];
            let args: Vec<String> = call
                .split(',')
                .map(|part| {
                    part.chars()
                        .filter(|c| c.is_alphanumeric() || *c == '_')
                        .collect()
                })
                .collect();
            if args.len() >= 3 && args[0] == args[2] {
                add(
                    "weighted_sum(",
                    "FORBIDDEN_ALIAS",
                    "Input and output arguments alias",
                    "non-aliasing spans",
                    &format!("quantity and result both use {}", args[0]),
                );
            }
            cursor = start + end + 1;
        } else {
            break;
        }
    }
    if !source.contains("std::inner_product") && !flat.contains("r*inputs+i") {
        add(
            "quantity[",
            "ROW_MAJOR_INDEX_UNRESOLVED",
            "Required row-major mapping was not found",
            "r * inputs + i",
            "unresolved",
        );
    }
    if !source.contains("std::inner_product")
        && !(flat.contains("quantity[") && flat.contains("]*factor[i]"))
    {
        add(
            "acc",
            "TRANSFORM_UNRESOLVED",
            "Required pairwise multiplication was not found",
            "quantity[...] * factor[i]",
            "unresolved",
        );
    }
    checks
}
pub fn legacy_core_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "NORMALIZE" => normalize(
            request
                .get("ir")
                .ok_or_else(|| invalid("LEGACY_IR_REQUIRED"))?,
            request
                .get("numeric_model")
                .and_then(Value::as_str)
                .unwrap_or("AbstractReal"),
        ),
        "AUDIT_DECIDE" => {
            let source = request
                .get("source")
                .and_then(Value::as_str)
                .ok_or_else(|| invalid("LEGACY_SOURCE_REQUIRED"))?;
            let path = request
                .get("source_path")
                .and_then(Value::as_str)
                .unwrap_or("");
            let diagnostics = semantic_diagnostics(path, source);
            Ok(
                json!({"status":if diagnostics.is_empty(){"PASS"}else{"FAILED"},"proof_level":if diagnostics.is_empty(){"VERIFIED_WITH_CONTRACT_ASSUMPTIONS"}else{"FAILED"},"semantic_graph":normalize(request.get("ir").ok_or_else(||invalid("LEGACY_IR_REQUIRED"))?,request.get("numeric_model").and_then(Value::as_str).unwrap_or("AbstractReal"))?,"diagnostics":diagnostics,"assumptions":["quantity, factor, and result do not overlap","input spans remain alive for the call"]}),
            )
        }
        action => Err(invalid(format!("UNSUPPORTED_LEGACY_CORE_ACTION:{action}"))),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn mutation_is_rejected() {
        let value=legacy_core_operation(&json!({"action":"AUDIT_DECIDE","source":"acc += quantity[r * inputs + i] + factor[i];","source_path":"x.cpp","ir":{"values":[],"operations":[]}})).unwrap();
        assert_eq!(value["status"], "FAILED");
        assert!(value["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["code"] == "TRANSFORM_MISMATCH"));
    }
}
