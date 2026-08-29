//! Logic, selection, and piecewise semantics owned by the native core.

use serde_json::{json, Map, Value};

use crate::{FormulaTracerError, Result};

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

fn required<'a>(request: &'a Value, key: &str) -> Result<&'a Value> {
    request
        .get(key)
        .ok_or_else(|| invalid(format!("LOGIC_FIELD_REQUIRED:{key}")))
}

fn predicate(expression: &Value, domain: Option<&str>) -> Value {
    json!({"op":"Predicate","expression":expression,"codomain":domain.unwrap_or("Boolean")})
}

fn canonicalize(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(canonicalize).collect()),
        Value::Object(object) => {
            let mapped: Map<String, Value> = object
                .iter()
                .map(|(key, item)| (key.clone(), canonicalize(item)))
                .collect();
            if mapped.get("op").and_then(Value::as_str) == Some("IfThenElse") {
                return json!({
                    "op":"Select",
                    "condition":predicate(mapped.get("condition").unwrap_or(&Value::Null), None),
                    "then":mapped.get("then").cloned().unwrap_or(Value::Null),
                    "else":mapped.get("else").cloned().unwrap_or(Value::Null),
                    "branch_facts":[
                        {"branch":"then","assumption":mapped.get("condition").cloned().unwrap_or(Value::Null)},
                        {"branch":"else","assumption":{"op":"LogicalNot","args":[mapped.get("condition").cloned().unwrap_or(Value::Null)]}}
                    ],
                    "source_form":"IfThenElse"
                });
            }
            if mapped.get("op").and_then(Value::as_str) == Some("FunctionCall") {
                if let Some(name @ ("and" | "or")) = mapped.get("name").and_then(Value::as_str) {
                    return json!({
                        "op":if name == "and" {"LogicalAnd"} else {"LogicalOr"},
                        "args":mapped.get("args").cloned().unwrap_or_else(||json!([])),
                        "evaluation":mapped.get("evaluation").cloned().unwrap_or_else(||json!("mathematical"))
                    });
                }
            }
            Value::Object(mapped)
        }
        scalar => scalar.clone(),
    }
}

fn bool_values(request: &Value) -> Result<Vec<bool>> {
    required(request, "values")?
        .as_array()
        .ok_or_else(|| invalid("LOGIC_VALUES_MUST_BE_ARRAY"))?
        .iter()
        .map(|value| {
            value
                .as_bool()
                .ok_or_else(|| invalid("LOGIC_VALUE_MUST_BE_BOOLEAN"))
        })
        .collect()
}

/// Execute one versioned logic action.
pub fn logic_operation(request: &Value) -> Result<Value> {
    let action = required(request, "action")?.as_str().unwrap_or("");
    match action {
        "PREDICATE" => Ok(predicate(
            required(request, "expression")?,
            request.get("domain").and_then(Value::as_str),
        )),
        "SELECT" => {
            let condition = required(request, "condition")?;
            let mut result = json!({
                "op":"Select",
                "condition":predicate(condition, None),
                "then":required(request, "then")?,
                "else":required(request, "otherwise")?,
                "branch_facts":[
                    {"branch":"then","assumption":condition},
                    {"branch":"else","assumption":{"op":"LogicalNot","args":[condition]}}
                ]
            });
            if let Some(source) = request.get("source_form").and_then(Value::as_str) {
                result["source_form"] = json!(source);
            }
            Ok(result)
        }
        "PIECEWISE" => {
            let cases = required(request, "cases")?
                .as_array()
                .ok_or_else(|| invalid("PIECEWISE_CASES_MUST_BE_ARRAY"))?;
            if cases.is_empty() {
                return Err(invalid("PIECEWISE_REQUIRES_CASE"));
            }
            let values: Result<Vec<Value>> = cases
                .iter()
                .map(|case| {
                    Ok(json!({
                        "predicate":predicate(required(case, "condition")?, None),
                        "expression":required(case, "expression")?
                    }))
                })
                .collect();
            let mut result = json!({"op":"Piecewise","cases":values?});
            if let Some(otherwise) = request.get("otherwise") {
                if !otherwise.is_null() {
                    result["otherwise"] = otherwise.clone();
                }
            }
            Ok(result)
        }
        "INDICATOR" => Ok(json!({
            "op":"Indicator",
            "predicate":predicate(required(request, "condition")?, None),
            "true_value":request.get("true_value").cloned().unwrap_or_else(||json!(1)),
            "false_value":request.get("false_value").cloned().unwrap_or_else(||json!(0))
        })),
        "CANONICALIZE" => Ok(canonicalize(required(request, "node")?)),
        "ANALYZE_DOMAINS" => {
            let node = canonicalize(required(request, "node")?);
            let mut branches = Vec::new();
            match node.get("op").and_then(Value::as_str) {
                Some("Select") => {
                    let condition = node
                        .pointer("/condition/expression")
                        .cloned()
                        .unwrap_or(Value::Null);
                    branches.push(json!({"branch":"then","assumptions":[condition.clone()],"expression":node.get("then").cloned().unwrap_or(Value::Null)}));
                    branches.push(json!({"branch":"else","assumptions":[{"op":"LogicalNot","args":[condition]}],"expression":node.get("else").cloned().unwrap_or(Value::Null)}));
                }
                Some("Piecewise") => {
                    let cases = node
                        .get("cases")
                        .and_then(Value::as_array)
                        .cloned()
                        .unwrap_or_default();
                    for (index, case) in cases.iter().enumerate() {
                        branches.push(json!({
                            "branch":format!("case_{index}"),
                            "assumptions":[case.pointer("/predicate/expression").cloned().unwrap_or(Value::Null)],
                            "expression":case.get("expression").cloned().unwrap_or(Value::Null)
                        }));
                    }
                    if let Some(otherwise) = node.get("otherwise") {
                        let assumptions: Vec<Value> = cases.iter().map(|case| json!({
                            "op":"LogicalNot","args":[case.pointer("/predicate/expression").cloned().unwrap_or(Value::Null)]
                        })).collect();
                        branches.push(json!({"branch":"otherwise","assumptions":assumptions,"expression":otherwise}));
                    }
                }
                _ => {
                    return Ok(
                        json!({"branches":[],"global_assumptions":[],"status":"NOT_PIECEWISE"}),
                    )
                }
            }
            Ok(
                json!({"branches":branches,"global_assumptions":[],"status":"BRANCH_DOMAINS_PRESERVED"}),
            )
        }
        "EVALUATE_BOOLEAN" => {
            let operator = required(request, "operator")?.as_str().unwrap_or("");
            let values = bool_values(request)?;
            let value = match operator {
                "Predicate" => *values
                    .first()
                    .ok_or_else(|| invalid("PREDICATE_VALUE_REQUIRED"))?,
                "LogicalAnd" => values.iter().all(|value| *value),
                "LogicalOr" => values.iter().any(|value| *value),
                "LogicalNot" if values.len() == 1 => !values[0],
                "LogicalXor" if values.len() == 2 => values[0] != values[1],
                "Implies" if values.len() == 2 => !values[0] || values[1],
                "Equivalent" if values.len() == 2 => values[0] == values[1],
                _ => return Err(invalid(format!("UNSUPPORTED_LOGIC_OPERATION:{operator}"))),
            };
            Ok(json!({"value":value}))
        }
        "SELECT_BRANCH" => Ok(json!({
            "branch":if required(request, "condition")?.as_bool()
                .ok_or_else(||invalid("LOGIC_CONDITION_MUST_BE_BOOLEAN"))? {"then"} else {"else"}
        })),
        _ => Err(invalid(format!("UNSUPPORTED_LOGIC_ACTION:{action}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_piecewise_and_truth_tables_are_native() {
        let value = logic_operation(&json!({"action":"CANONICALIZE","node":{
            "op":"IfThenElse","condition":{"op":"Compare"},"then":1,"else":0
        }}))
        .unwrap();
        assert_eq!(value["op"], "Select");
        let domains = logic_operation(&json!({"action":"ANALYZE_DOMAINS","node":value})).unwrap();
        assert_eq!(domains["branches"].as_array().unwrap().len(), 2);
        let implies = logic_operation(
            &json!({"action":"EVALUATE_BOOLEAN","operator":"Implies","values":[true,false]}),
        )
        .unwrap();
        assert_eq!(implies["value"], false);
    }
}
