//! Exact physical-dimension and affine unit-conversion semantics.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

#[derive(Clone, Copy)]
struct Rational {
    numerator: i128,
    denominator: i128,
}

impl Rational {
    fn new(numerator: i128, denominator: i128) -> Result<Self> {
        if denominator == 0 {
            return Err(invalid("UNIT_RATIONAL_ZERO_DENOMINATOR"));
        }
        let sign = if denominator < 0 { -1 } else { 1 };
        let mut numerator = numerator * sign;
        let mut denominator = denominator.abs();
        let divisor = gcd(numerator.unsigned_abs(), denominator as u128) as i128;
        numerator /= divisor;
        denominator /= divisor;
        Ok(Self {
            numerator,
            denominator,
        })
    }
    fn add(self, other: Self) -> Result<Self> {
        Self::new(
            self.numerator * other.denominator + other.numerator * self.denominator,
            self.denominator * other.denominator,
        )
    }
    fn sub(self, other: Self) -> Result<Self> {
        Self::new(
            self.numerator * other.denominator - other.numerator * self.denominator,
            self.denominator * other.denominator,
        )
    }
    fn mul(self, other: Self) -> Result<Self> {
        Self::new(
            self.numerator * other.numerator,
            self.denominator * other.denominator,
        )
    }
    fn div(self, other: Self) -> Result<Self> {
        Self::new(
            self.numerator * other.denominator,
            self.denominator * other.numerator,
        )
    }
    fn json(self) -> Value {
        json!({"numerator":self.numerator.to_string(),"denominator":self.denominator.to_string()})
    }
}

fn gcd(mut left: u128, mut right: u128) -> u128 {
    while right != 0 {
        let remainder = left % right;
        left = right;
        right = remainder;
    }
    left.max(1)
}

fn rational(value: &Value) -> Result<Rational> {
    let parse = |key: &str| -> Result<i128> {
        let item = value
            .get(key)
            .ok_or_else(|| invalid(format!("UNIT_RATIONAL_FIELD_REQUIRED:{key}")))?;
        if let Some(text) = item.as_str() {
            return text.parse().map_err(|_| invalid("UNIT_RATIONAL_INVALID"));
        }
        item.as_i64()
            .map(i128::from)
            .ok_or_else(|| invalid("UNIT_RATIONAL_INVALID"))
    };
    Rational::new(parse("numerator")?, parse("denominator")?)
}

fn dimension(value: &Value) -> Result<BTreeMap<String, i64>> {
    let items = value
        .as_array()
        .ok_or_else(|| invalid("UNIT_DIMENSION_MUST_BE_ARRAY"))?;
    let mut result = BTreeMap::new();
    for item in items {
        let pair = item
            .as_array()
            .ok_or_else(|| invalid("UNIT_DIMENSION_ENTRY_INVALID"))?;
        if pair.len() != 2 {
            return Err(invalid("UNIT_DIMENSION_ENTRY_INVALID"));
        }
        let name = pair[0]
            .as_str()
            .ok_or_else(|| invalid("UNIT_DIMENSION_NAME_INVALID"))?;
        let exponent = pair[1]
            .as_i64()
            .ok_or_else(|| invalid("UNIT_DIMENSION_EXPONENT_INVALID"))?;
        if exponent != 0 {
            result.insert(name.into(), exponent);
        }
    }
    Ok(result)
}

fn dimension_json(values: BTreeMap<String, i64>) -> Value {
    Value::Array(
        values
            .into_iter()
            .filter(|(_, exponent)| *exponent != 0)
            .map(|(name, exponent)| json!([name, exponent]))
            .collect(),
    )
}

fn unit(value: &Value) -> Result<(&Value, Rational, Rational)> {
    Ok((
        value
            .get("dimension")
            .ok_or_else(|| invalid("UNIT_DIMENSION_REQUIRED"))?,
        rational(
            value
                .get("scale")
                .ok_or_else(|| invalid("UNIT_SCALE_REQUIRED"))?,
        )?,
        rational(
            value
                .get("offset")
                .ok_or_else(|| invalid("UNIT_OFFSET_REQUIRED"))?,
        )?,
    ))
}

pub fn unit_operation(request: &Value) -> Result<Value> {
    match request.get("action").and_then(Value::as_str).unwrap_or("") {
        "DIMENSION_FROM_MAPPING" => {
            let mapping = request
                .get("values")
                .and_then(Value::as_object)
                .ok_or_else(|| invalid("UNIT_DIMENSION_MAPPING_REQUIRED"))?;
            let mut values = BTreeMap::new();
            for (name, exponent) in mapping {
                let exponent = exponent
                    .as_i64()
                    .ok_or_else(|| invalid("UNIT_DIMENSION_EXPONENT_INVALID"))?;
                if exponent != 0 {
                    values.insert(name.clone(), exponent);
                }
            }
            Ok(json!({"exponents":dimension_json(values)}))
        }
        action @ ("DIMENSION_MULTIPLY" | "DIMENSION_DIVIDE") => {
            let mut values = dimension(
                request
                    .get("left")
                    .ok_or_else(|| invalid("UNIT_LEFT_REQUIRED"))?,
            )?;
            let sign = if action == "DIMENSION_MULTIPLY" {
                1
            } else {
                -1
            };
            for (name, exponent) in dimension(
                request
                    .get("right")
                    .ok_or_else(|| invalid("UNIT_RIGHT_REQUIRED"))?,
            )? {
                *values.entry(name).or_default() += sign * exponent;
            }
            Ok(json!({"exponents":dimension_json(values)}))
        }
        action @ ("DIMENSION_DERIVATIVE" | "DIMENSION_GRADIENT" | "DIMENSION_DIVERGENCE") => {
            let mut values = dimension(
                request
                    .get("function_dimension")
                    .ok_or_else(|| invalid("UNIT_FUNCTION_DIMENSION_REQUIRED"))?,
            )?;
            for (name, exponent) in dimension(
                request
                    .get("variable_dimension")
                    .ok_or_else(|| invalid("UNIT_VARIABLE_DIMENSION_REQUIRED"))?,
            )? {
                *values.entry(name).or_default() -= exponent;
            }
            Ok(json!({"operator":action,"exponents":dimension_json(values)}))
        }
        "DIMENSION_LAPLACIAN" => {
            let mut values = dimension(
                request
                    .get("function_dimension")
                    .ok_or_else(|| invalid("UNIT_FUNCTION_DIMENSION_REQUIRED"))?,
            )?;
            for (name, exponent) in dimension(
                request
                    .get("variable_dimension")
                    .ok_or_else(|| invalid("UNIT_VARIABLE_DIMENSION_REQUIRED"))?,
            )? {
                *values.entry(name).or_default() -= 2 * exponent;
            }
            Ok(json!({"operator":"DIMENSION_LAPLACIAN","exponents":dimension_json(values)}))
        }
        "DIMENSION_INTEGRAL" => {
            let mut values = dimension(
                request
                    .get("integrand_dimension")
                    .ok_or_else(|| invalid("UNIT_INTEGRAND_DIMENSION_REQUIRED"))?,
            )?;
            for (name, exponent) in dimension(
                request
                    .get("measure_dimension")
                    .ok_or_else(|| invalid("UNIT_MEASURE_DIMENSION_REQUIRED"))?,
            )? {
                *values.entry(name).or_default() += exponent;
            }
            Ok(json!({"operator":"DIMENSION_INTEGRAL","exponents":dimension_json(values)}))
        }
        "CONVERT" => {
            let value = rational(
                request
                    .get("value")
                    .ok_or_else(|| invalid("UNIT_VALUE_REQUIRED"))?,
            )?;
            let source = request
                .get("source")
                .ok_or_else(|| invalid("UNIT_SOURCE_REQUIRED"))?;
            let target = request
                .get("target")
                .ok_or_else(|| invalid("UNIT_TARGET_REQUIRED"))?;
            let (source_dimension, source_scale, source_offset) = unit(source)?;
            let (target_dimension, target_scale, target_offset) = unit(target)?;
            if dimension(source_dimension)? != dimension(target_dimension)? {
                return Err(invalid("UNIT_DIMENSION_MISMATCH"));
            }
            let converted = value
                .mul(source_scale)?
                .add(source_offset)?
                .sub(target_offset)?
                .div(target_scale)?;
            Ok(json!({"value":converted.json()}))
        }
        "ADD" => {
            let converted = unit_operation(
                &json!({"action":"CONVERT","value":request.get("right_value"),
                "source":request.get("right_unit"),"target":request.get("left_unit")}),
            )?;
            let left = rational(
                request
                    .get("left_value")
                    .ok_or_else(|| invalid("UNIT_LEFT_VALUE_REQUIRED"))?,
            )?;
            let right = rational(converted.get("value").unwrap_or(&Value::Null))?;
            Ok(json!({"value":left.add(right)?.json()}))
        }
        action => Err(invalid(format!("UNSUPPORTED_UNIT_ACTION:{action}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn affine_conversion_is_exact() {
        let celsius = json!({"dimension":[["Theta",1]],"scale":{"numerator":"1","denominator":"1"},"offset":{"numerator":"27315","denominator":"100"}});
        let kelvin = json!({"dimension":[["Theta",1]],"scale":{"numerator":"1","denominator":"1"},"offset":{"numerator":"0","denominator":"1"}});
        let result = unit_operation(&json!({"action":"CONVERT","value":{"numerator":"20","denominator":"1"},"source":celsius,"target":kelvin})).unwrap();
        assert_eq!(result.pointer("/value/numerator").unwrap(), "5863");
        assert_eq!(result.pointer("/value/denominator").unwrap(), "20");
    }

    #[test]
    fn calculus_dimensions_compose_without_a_second_unit_system() {
        let acceleration = unit_operation(&json!({"action":"DIMENSION_DERIVATIVE",
            "function_dimension":[["L",1],["T",-1]],"variable_dimension":[["T",1]]}))
        .unwrap();
        assert_eq!(acceleration["exponents"], json!([["L", 1], ["T", -2]]));
        let laplacian = unit_operation(&json!({"action":"DIMENSION_LAPLACIAN",
            "function_dimension":[["Theta",1]],"variable_dimension":[["L",1]]}))
        .unwrap();
        assert_eq!(laplacian["exponents"], json!([["L", -2], ["Theta", 1]]));
    }
}
