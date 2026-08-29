use crate::{
    semantic_hash, to_tex, CanonicalPolicy, FormulaTracerError, FunctionType, NumericDomain,
    Result, Shape,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Number, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MathematicalFunction {
    pub schema_version: String,
    pub variables: Vec<String>,
    #[serde(default)]
    pub parameters: BTreeMap<String, Value>,
    pub expression: Value,
    pub function_type: FunctionType,
    #[serde(default)]
    pub dtype: Option<String>,
    #[serde(default)]
    pub shape: Option<Shape>,
    #[serde(default)]
    pub units: Vec<String>,
    #[serde(default)]
    pub assumptions: Vec<String>,
    #[serde(default)]
    pub evidence: Vec<Value>,
    #[serde(default)]
    pub provenance: Option<Value>,
}

impl MathematicalFunction {
    pub fn from_expression(
        expression: Value,
        assumptions: Vec<String>,
        evidence: Vec<Value>,
        provenance: Option<Value>,
    ) -> Self {
        Self {
            variables: free_variables(&expression).into_iter().collect(),
            expression,
            schema_version: "1.0".into(),
            parameters: BTreeMap::new(),
            function_type: FunctionType {
                domain: NumericDomain::Unknown,
                codomain: NumericDomain::Unknown,
                input_shape: None,
                output_shape: None,
                units: vec![],
            },
            dtype: None,
            shape: None,
            units: vec![],
            assumptions,
            evidence,
            provenance,
        }
    }
    pub fn substitute(&self, values: &BTreeMap<String, Value>) -> Self {
        let mut result = self.clone();
        result.expression = substitute_free_variables(&self.expression, values);
        result.parameters.extend(values.clone());
        result.variables = free_variables(&result.expression).into_iter().collect();
        result
    }
    pub fn inspect(&self) -> Result<Value> {
        Ok(json!({
        "semantic_hash": semantic_hash(&self.expression, CanonicalPolicy::default())?,
        "variables": self.variables, "parameters": self.parameters, "domain": self.function_type.domain,
        "codomain": self.function_type.codomain, "numeric_domain": self.function_type.codomain,
        "dtype": self.dtype, "shape": self.shape, "units": self.units, "assumptions": self.assumptions,
        "evidence": self.evidence, "provenance": self.provenance }))
    }
    pub fn to_tex(&self) -> String {
        to_tex(&self.expression)
    }
    pub fn to_schema(&self) -> Result<Value> {
        Ok(serde_json::to_value(self)?)
    }
    pub fn evaluate(&self, values: &BTreeMap<String, f64>) -> Result<f64> {
        let dynamic = values
            .iter()
            .map(|(k, v)| (k.clone(), number(*v)))
            .collect();
        self.evaluate_json(&dynamic)?
            .as_f64()
            .ok_or_else(|| invalid("evaluation result is not scalar"))
    }
    pub fn evaluate_json(&self, values: &BTreeMap<String, Value>) -> Result<Value> {
        let mut merged = self.parameters.clone();
        merged.extend(values.clone());
        if let Some(missing) = self
            .variables
            .iter()
            .find(|name| !merged.contains_key(*name))
        {
            return Err(FormulaTracerError::ConstraintUnresolved(format!(
                "variable value missing: {missing}"
            )));
        }
        evaluate_value(&self.expression, &merged)
    }
}

fn invalid(message: &str) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn free_variables(value: &Value) -> BTreeSet<String> {
    fn visit(value: &Value, bound: &mut Vec<String>, out: &mut BTreeSet<String>) {
        if let Some(object) = value.as_object() {
            let op = object.get("op").and_then(Value::as_str).unwrap_or("");
            let binder = object
                .get("bound_index")
                .or_else(|| {
                    object
                        .get("variable")
                        .filter(|_| matches!(op, "Integral" | "Lambda"))
                })
                .and_then(Value::as_str)
                .map(str::to_owned);
            if let Some(name) = &binder {
                bound.push(name.clone());
            }
            if op == "FreeVariable" {
                if let Some(name) = object.get("name").and_then(Value::as_str) {
                    if !bound.iter().any(|item| item == name) {
                        out.insert(name.into());
                    }
                }
            }
            for child in object.values() {
                visit(child, bound, out);
            }
            if binder.is_some() {
                bound.pop();
            }
        } else if let Some(items) = value.as_array() {
            for child in items {
                visit(child, bound, out);
            }
        }
    }
    let mut out = BTreeSet::new();
    visit(value, &mut vec![], &mut out);
    out
}
fn substitute_free_variables(value: &Value, mapping: &BTreeMap<String, Value>) -> Value {
    if value.get("op").and_then(Value::as_str) == Some("FreeVariable") {
        if let Some(item) = value
            .get("name")
            .and_then(Value::as_str)
            .and_then(|name| mapping.get(name))
        {
            return item.clone();
        }
    }
    match value {
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(k, v)| (k.clone(), substitute_free_variables(v, mapping)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|v| substitute_free_variables(v, mapping))
                .collect(),
        ),
        _ => value.clone(),
    }
}
fn number(value: f64) -> Value {
    Number::from_f64(value)
        .map(Value::Number)
        .unwrap_or(Value::Null)
}
fn unary(value: Value, operation: impl Fn(f64) -> Result<f64> + Copy) -> Result<Value> {
    match value {
        Value::Array(items) => items
            .into_iter()
            .map(|v| unary(v, operation))
            .collect::<Result<Vec<_>>>()
            .map(Value::Array),
        scalar => operation(
            scalar
                .as_f64()
                .ok_or_else(|| invalid("numeric operand required"))?,
        )
        .map(number),
    }
}
fn binary(
    left: Value,
    right: Value,
    operation: impl Fn(f64, f64) -> Result<f64> + Copy,
) -> Result<Value> {
    match (left, right) {
        (Value::Array(a), Value::Array(b)) => {
            if a.len() != b.len() {
                return Err(FormulaTracerError::ConstraintUnresolved(
                    "shape mismatch".into(),
                ));
            }
            a.into_iter()
                .zip(b)
                .map(|(x, y)| binary(x, y, operation))
                .collect::<Result<Vec<_>>>()
                .map(Value::Array)
        }
        (Value::Array(a), b) => a
            .into_iter()
            .map(|x| binary(x, b.clone(), operation))
            .collect::<Result<Vec<_>>>()
            .map(Value::Array),
        (a, Value::Array(b)) => b
            .into_iter()
            .map(|y| binary(a.clone(), y, operation))
            .collect::<Result<Vec<_>>>()
            .map(Value::Array),
        (a, b) => operation(
            a.as_f64()
                .ok_or_else(|| invalid("numeric operand required"))?,
            b.as_f64()
                .ok_or_else(|| invalid("numeric operand required"))?,
        )
        .map(number),
    }
}
fn args(value: &Value, count: usize) -> Result<&[Value]> {
    let result = value
        .get("args")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid("operator arguments missing"))?;
    if result.len() == count {
        Ok(result)
    } else {
        Err(invalid("wrong argument count"))
    }
}
fn evaluate_value(value: &Value, variables: &BTreeMap<String, Value>) -> Result<Value> {
    // Substitution parameters and binding inputs are already semantic values.  Accept
    // only JSON numeric/boolean leaves (and recursively shaped arrays); objects must
    // still pass through the explicit IR operator allow-list below.
    if value.is_number() || value.is_boolean() {
        return Ok(value.clone());
    }
    if let Some(items) = value.as_array() {
        return items
            .iter()
            .map(|item| evaluate_value(item, variables))
            .collect::<Result<Vec<_>>>()
            .map(Value::Array);
    }
    let op = value.get("op").and_then(Value::as_str).unwrap_or("");
    match op {
        "Constant" => value
            .get("value")
            .cloned()
            .ok_or_else(|| invalid("constant value missing")),
        "FreeVariable" => value
            .get("name")
            .and_then(Value::as_str)
            .and_then(|n| variables.get(n))
            .cloned()
            .ok_or_else(|| {
                FormulaTracerError::ConstraintUnresolved("variable value missing".into())
            }),
        "Negate" => unary(evaluate_value(&args(value, 1)?[0], variables)?, |x| Ok(-x)),
        "Add" | "Subtract" | "Multiply" | "Divide" | "Power" | "Minimum" | "Maximum" => {
            let a = args(value, 2)?;
            let left = evaluate_value(&a[0], variables)?;
            let right = evaluate_value(&a[1], variables)?;
            binary(left, right, |x, y| match op {
                "Add" => Ok(x + y),
                "Subtract" => Ok(x - y),
                "Multiply" => Ok(x * y),
                "Divide" if y != 0.0 => Ok(x / y),
                "Divide" => Err(FormulaTracerError::ConstraintUnresolved(
                    "division by zero".into(),
                )),
                "Power" => {
                    let z = x.powf(y);
                    if z.is_finite() {
                        Ok(z)
                    } else {
                        Err(FormulaTracerError::ConstraintUnresolved(
                            "power outside real domain".into(),
                        ))
                    }
                }
                "Minimum" => Ok(x.min(y)),
                "Maximum" => Ok(x.max(y)),
                _ => unreachable!(),
            })
        }
        "Abs" | "Sqrt" | "Log" | "Exp" | "Sin" | "Cos" | "Tan" | "Sinh" | "Cosh" | "Tanh"
        | "Floor" | "Ceil" => {
            let argument = value
                .get("args")
                .and_then(Value::as_array)
                .and_then(|x| x.first())
                .or_else(|| value.get("argument"))
                .ok_or_else(|| invalid("function argument missing"))?;
            unary(evaluate_value(argument, variables)?, |x| match op {
                "Abs" => Ok(x.abs()),
                "Sqrt" if x >= 0.0 => Ok(x.sqrt()),
                "Sqrt" => Err(FormulaTracerError::ConstraintUnresolved(
                    "sqrt outside real domain".into(),
                )),
                "Log" if x > 0.0 => Ok(x.ln()),
                "Log" => Err(FormulaTracerError::ConstraintUnresolved(
                    "log outside real domain".into(),
                )),
                "Exp" => Ok(x.exp()),
                "Sin" => Ok(x.sin()),
                "Cos" => Ok(x.cos()),
                "Tan" => Ok(x.tan()),
                "Sinh" => Ok(x.sinh()),
                "Cosh" => Ok(x.cosh()),
                "Tanh" => Ok(x.tanh()),
                "Floor" => Ok(x.floor()),
                "Ceil" => Ok(x.ceil()),
                _ => unreachable!(),
            })
        }
        "FunctionCall" => {
            let mapped = match value.get("name").and_then(Value::as_str).unwrap_or("") {
                "abs" => "Abs",
                "sqrt" => "Sqrt",
                "log" => "Log",
                "exp" => "Exp",
                "sin" => "Sin",
                "cos" => "Cos",
                "tan" => "Tan",
                "sinh" => "Sinh",
                "cosh" => "Cosh",
                "tanh" => "Tanh",
                "floor" => "Floor",
                "ceil" => "Ceil",
                _ => {
                    return Err(FormulaTracerError::NativeComponentIncomplete(
                        "function evaluator operator",
                    ))
                }
            };
            let mut lowered = value.clone();
            lowered["op"] = Value::String(mapped.into());
            evaluate_value(&lowered, variables)
        }
        "Compare" => {
            let a = args(value, 2)?;
            let x = evaluate_value(&a[0], variables)?
                .as_f64()
                .ok_or_else(|| invalid("scalar comparison required"))?;
            let y = evaluate_value(&a[1], variables)?
                .as_f64()
                .ok_or_else(|| invalid("scalar comparison required"))?;
            Ok(Value::Bool(
                match value
                    .get("comparison")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                {
                    "Equal" => x == y,
                    "NotEqual" => x != y,
                    "LessThan" => x < y,
                    "LessEqual" => x <= y,
                    "GreaterThan" => x > y,
                    "GreaterEqual" => x >= y,
                    _ => return Err(invalid("unknown comparison")),
                },
            ))
        }
        "Select" | "IfThenElse" => {
            let condition = value
                .get("condition")
                .ok_or_else(|| invalid("condition missing"))?;
            let condition = condition.get("expression").unwrap_or(condition);
            let predicate = evaluate_value(condition, variables)?
                .as_bool()
                .ok_or_else(|| invalid("boolean condition required"))?;
            let branch = if predicate {
                value.get("then")
            } else {
                value.get("else")
            }
            .ok_or_else(|| invalid("branch missing"))?;
            evaluate_value(branch, variables)
        }
        _ => Err(FormulaTracerError::NativeComponentIncomplete(
            "function evaluator operator",
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scalar_array_substitution_and_domain_fail_closed() {
        let function = MathematicalFunction::from_expression(
            json!({"op":"Add","args":[{"op":"Power","args":[{"op":"FreeVariable","name":"x"},{"op":"Constant","value":2}]},{"op":"FreeVariable","name":"a"}]}),
            vec![],
            vec![],
            None,
        );
        let substituted = function.substitute(&BTreeMap::from([("a".into(), json!(2.0))]));
        assert_eq!(
            substituted
                .evaluate_json(&BTreeMap::from([("x".into(), json!([1.0, 2.0]))]))
                .unwrap(),
            json!([3.0, 6.0])
        );
        let log = MathematicalFunction::from_expression(
            json!({"op":"Log","args":[{"op":"FreeVariable","name":"x"}]}),
            vec![],
            vec![],
            None,
        );
        assert!(log
            .evaluate_json(&BTreeMap::from([("x".into(), json!(-1.0))]))
            .is_err());
    }
}
