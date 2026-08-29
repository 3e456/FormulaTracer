use crate::{FormulaTracerError, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Signedness {
    Signed,
    Unsigned,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Overflow {
    Wrap,
    Checked,
    Saturate,
    Unbounded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct BitRepresentation {
    pub width: u8,
    pub signedness: Signedness,
    pub twos_complement: bool,
    pub overflow: Overflow,
}

impl BitRepresentation {
    pub fn mask(self) -> Result<u128> {
        match self.width {
            0 => Err(FormulaTracerError::InvalidBitVector(
                "width must be positive".into(),
            )),
            128 => Ok(u128::MAX),
            1..=127 => Ok((1u128 << self.width) - 1),
            _ => Err(FormulaTracerError::InvalidBitVector("width > 128".into())),
        }
    }
    pub fn encode(self, value: i128) -> Result<u128> {
        Ok((value as u128) & self.mask()?)
    }
    pub fn decode(self, bits: u128) -> Result<i128> {
        let value = bits & self.mask()?;
        if self.signedness == Signedness::Signed
            && self.twos_complement
            && self.width < 128
            && value & (1u128 << (self.width - 1)) != 0
        {
            Ok((value | !self.mask()?) as i128)
        } else {
            Ok(value as i128)
        }
    }
}

pub fn bit_and(rep: BitRepresentation, a: i128, b: i128) -> Result<i128> {
    rep.decode(rep.encode(a)? & rep.encode(b)?)
}
pub fn bit_or(rep: BitRepresentation, a: i128, b: i128) -> Result<i128> {
    rep.decode(rep.encode(a)? | rep.encode(b)?)
}
pub fn bit_xor(rep: BitRepresentation, a: i128, b: i128) -> Result<i128> {
    rep.decode(rep.encode(a)? ^ rep.encode(b)?)
}
pub fn bit_not(rep: BitRepresentation, a: i128) -> Result<i128> {
    rep.decode(!rep.encode(a)? & rep.mask()?)
}

fn python_representation(request: &Value) -> Result<(Option<u32>, &str, &str)> {
    let representation = request.get("representation").ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument("representation required".into())
    })?;
    let width = representation
        .get("width")
        .filter(|value| !value.is_null())
        .map(|value| {
            value.as_u64().map(|number| number as u32).ok_or_else(|| {
                FormulaTracerError::InvalidSemanticDocument("bit width must be an integer".into())
            })
        })
        .transpose()?;
    let signedness = representation
        .get("signedness")
        .and_then(Value::as_str)
        .unwrap_or("UNRESOLVED");
    let overflow = representation
        .get("overflow")
        .and_then(Value::as_str)
        .unwrap_or("LANGUAGE_UNRESOLVED");
    if width.is_some_and(|value| value == 0 || value > 127) {
        return Err(FormulaTracerError::InvalidBitVector(
            "width must be in 1..=127".into(),
        ));
    }
    Ok((width, signedness, overflow))
}

fn request_integer(request: &Value, key: &str) -> Result<i128> {
    request
        .get(key)
        .and_then(Value::as_i64)
        .map(i128::from)
        .ok_or_else(|| {
            FormulaTracerError::InvalidSemanticDocument(format!("{key} must be an integer"))
        })
}

fn finite_mask(width: u32) -> i128 {
    (1_i128 << width) - 1
}

fn encode_python(value: i128, width: u32, signedness: &str, overflow: &str) -> Result<i128> {
    if signedness == "UNSIGNED" && value < 0 {
        return Err(FormulaTracerError::InvalidBitVector(
            "NEGATIVE_VALUE_CANNOT_ENCODE_AS_UNSIGNED_WITHOUT_CAST".into(),
        ));
    }
    let modulus = 1_i128 << width;
    if overflow == "CHECKED" {
        let (lower, upper) = if signedness == "SIGNED" {
            (-(1_i128 << (width - 1)), (1_i128 << (width - 1)) - 1)
        } else {
            (0, modulus - 1)
        };
        if !(lower..=upper).contains(&value) {
            return Err(FormulaTracerError::InvalidBitVector(
                "BIT_ENCODING_OUT_OF_RANGE".into(),
            ));
        }
    }
    Ok(value.rem_euclid(modulus))
}

fn decode_python(bits: i128, width: u32, signedness: &str) -> i128 {
    let modulus = 1_i128 << width;
    let encoded = bits.rem_euclid(modulus);
    if signedness == "SIGNED" && encoded >= (1_i128 << (width - 1)) {
        encoded - modulus
    } else {
        encoded
    }
}

/// Python-compatible public BitVector semantics.  The Python module performs
/// object conversion only; all value decisions happen here.
pub fn bitvector_operation(request: &Value) -> Result<Value> {
    let action = request
        .get("action")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            FormulaTracerError::InvalidSemanticDocument("bitvector action required".into())
        })?;
    if action == "RECOGNIZE_FIELD_EXTRACT" {
        let node = request.get("node").ok_or_else(|| {
            FormulaTracerError::InvalidSemanticDocument("bitvector node required".into())
        })?;
        let recognized = node.get("args").and_then(Value::as_array).and_then(|args| {
            if node.get("op").and_then(Value::as_str) != Some("BitAnd") || args.len() != 2 {
                return None;
            }
            let shifted = &args[0];
            let mask_node = &args[1];
            if shifted.get("op").and_then(Value::as_str) != Some("ShiftRight")
                || mask_node.get("op").and_then(Value::as_str) != Some("Constant")
            {
                return None;
            }
            let mask = mask_node.get("value").and_then(Value::as_i64)?;
            if mask <= 0 || (mask & (mask + 1)) != 0 {
                return None;
            }
            let shifted_args = shifted.get("args").and_then(Value::as_array)?;
            if shifted_args.len() != 2
                || shifted_args[1].get("op").and_then(Value::as_str) != Some("Constant")
            {
                return None;
            }
            let offset = shifted_args[1].get("value").and_then(Value::as_i64)?;
            let representation = node
                .get("bit_representation")
                .or_else(|| shifted.get("bit_representation"))?;
            let field_width = (mask as u64).count_ones();
            Some(json!({
                "op":"BitFieldExtract", "value":shifted_args[0], "offset":offset,
                "width":field_width, "bit_representation":representation,
                "result_representation":{
                    "width":field_width,"signedness":"UNSIGNED","encoding":"UNSIGNED_BINARY",
                    "overflow":"MODULAR_WRAP","language":"mathematical","dtype":Value::Null,
                    "evidence":"TYPE_CONTRACT"
                }, "recognized_from":"shift-and-mask"
            }))
        });
        return Ok(json!({"value":recognized}));
    }
    if action == "REPRESENTATION_FOR_DTYPE" {
        let dtype = request
            .get("dtype")
            .and_then(Value::as_str)
            .ok_or_else(|| FormulaTracerError::InvalidSemanticDocument("dtype required".into()))?;
        let language = request
            .get("language")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let normalized = dtype
            .to_ascii_lowercase()
            .replace("std::", "")
            .replace("numpy.", "");
        let parsed = ["uint", "u"]
            .iter()
            .find_map(|prefix| {
                normalized
                    .strip_prefix(prefix)
                    .and_then(|suffix| suffix.parse::<u32>().ok())
                    .map(|width| (width, false))
            })
            .or_else(|| {
                ["int", "i"].iter().find_map(|prefix| {
                    normalized
                        .strip_prefix(prefix)
                        .and_then(|suffix| suffix.parse::<u32>().ok())
                        .map(|width| (width, true))
                })
            })
            .or(match normalized.as_str() {
                "byte" | "char" => Some((8, true)),
                "ubyte" | "uchar" => Some((8, false)),
                "short" => Some((16, true)),
                "ushort" => Some((16, false)),
                "int" => Some((32, true)),
                "uint" => Some((32, false)),
                "long" => Some((64, true)),
                "ulong" => Some((64, false)),
                _ => None,
            });
        let value = if matches!(normalized.as_str(), "python.int" | "pyint") {
            Some(json!({"width":Value::Null,"signedness":"UNBOUNDED",
                "encoding":"PYTHON_INFINITE_TWOS_COMPLEMENT","overflow":"UNBOUNDED",
                "language":language,"dtype":"python.int","evidence":"LANGUAGE_SPEC"}))
        } else {
            parsed.map(|(width, signed)| {
                json!({"width":width,
                "signedness":if signed {"SIGNED"} else {"UNSIGNED"},
                "encoding":if signed {"TWOS_COMPLEMENT"} else {"UNSIGNED_BINARY"},
                "overflow":if signed {"LANGUAGE_UNRESOLVED"} else {"MODULAR_WRAP"},
                "language":language,"dtype":dtype,"evidence":"TYPE_CONTRACT"})
            })
        };
        return Ok(json!({"value":value}));
    }
    let (width, signedness, overflow) = python_representation(request)?;
    if signedness == "UNRESOLVED" {
        return Err(FormulaTracerError::InvalidBitVector(
            "BIT_REPRESENTATION_UNRESOLVED".into(),
        ));
    }
    match action {
        "MASK" => {
            let width = width.ok_or_else(|| {
                FormulaTracerError::InvalidBitVector("UNBOUNDED_INTEGER_HAS_NO_FINITE_MASK".into())
            })?;
            Ok(json!({"value":finite_mask(width).to_string()}))
        }
        "ENCODE" => {
            let width = width.ok_or_else(|| {
                FormulaTracerError::InvalidBitVector(
                    "UNBOUNDED_INTEGER_HAS_NO_FINITE_BITVECTOR_ENCODING".into(),
                )
            })?;
            Ok(
                json!({"value":encode_python(request_integer(request, "value")?, width, signedness, overflow)?.to_string()}),
            )
        }
        "DECODE" => {
            let width = width.ok_or_else(|| {
                FormulaTracerError::InvalidBitVector(
                    "UNBOUNDED_INTEGER_HAS_NO_FINITE_BITVECTOR_DECODING".into(),
                )
            })?;
            Ok(
                json!({"value":decode_python(request_integer(request, "value")?, width, signedness).to_string()}),
            )
        }
        "EVALUATE" => {
            let op = request.get("op").and_then(Value::as_str).unwrap_or("");
            let args: Vec<i128> = request
                .get("values")
                .and_then(Value::as_array)
                .ok_or_else(|| {
                    FormulaTracerError::InvalidSemanticDocument("values required".into())
                })?
                .iter()
                .map(|value| {
                    value.as_i64().map(i128::from).ok_or_else(|| {
                        FormulaTracerError::InvalidSemanticDocument(
                            "bit value must be integer".into(),
                        )
                    })
                })
                .collect::<Result<_>>()?;
            let expected = if op == "BitNot" { 1 } else { 2 };
            if args.len() != expected {
                return Err(FormulaTracerError::InvalidBitVector(
                    "BIT_OPERATION_ARITY".into(),
                ));
            }
            if matches!(
                op,
                "ShiftLeft" | "ShiftRight" | "RotateLeft" | "RotateRight"
            ) && args[1] < 0
            {
                return Err(FormulaTracerError::InvalidBitVector(
                    "NEGATIVE_SHIFT_COUNT".into(),
                ));
            }
            if width.is_none() {
                let value = match op {
                    "BitAnd" => args[0] & args[1],
                    "BitOr" => args[0] | args[1],
                    "BitXor" => args[0] ^ args[1],
                    "BitNot" => !args[0],
                    "ShiftLeft" => args[0] << args[1],
                    "ShiftRight" => args[0] >> args[1],
                    _ => {
                        return Err(FormulaTracerError::InvalidBitVector(
                            "ROTATE_REQUIRES_FIXED_BIT_WIDTH".into(),
                        ))
                    }
                };
                return Ok(json!({"value":value.to_string()}));
            }
            let width = width.unwrap();
            if matches!(op, "ShiftLeft" | "ShiftRight") && args[1] >= i128::from(width) {
                return Err(FormulaTracerError::InvalidBitVector(
                    "SHIFT_COUNT_OUT_OF_RANGE".into(),
                ));
            }
            let encoded: Vec<i128> = args
                .iter()
                .map(|value| encode_python(*value, width, signedness, overflow))
                .collect::<Result<_>>()?;
            let mask = finite_mask(width);
            let value = match op {
                "BitAnd" => encoded[0] & encoded[1],
                "BitOr" => encoded[0] | encoded[1],
                "BitXor" => encoded[0] ^ encoded[1],
                "BitNot" => (!encoded[0]) & mask,
                "ShiftLeft" => (encoded[0] << encoded[1]) & mask,
                "ShiftRight" => {
                    let kind = request
                        .get("shift_semantics")
                        .and_then(Value::as_str)
                        .unwrap_or(if signedness == "SIGNED" {
                            "ARITHMETIC_RIGHT"
                        } else {
                            "LOGICAL_RIGHT"
                        });
                    match kind {
                        "ARITHMETIC_RIGHT" => encode_python(
                            decode_python(encoded[0], width, signedness) >> encoded[1],
                            width,
                            signedness,
                            overflow,
                        )?,
                        "LOGICAL_RIGHT" => encoded[0] >> encoded[1],
                        _ => {
                            return Err(FormulaTracerError::InvalidBitVector(
                                "INVALID_RIGHT_SHIFT_SEMANTICS".into(),
                            ))
                        }
                    }
                }
                "RotateLeft" | "RotateRight" => {
                    let amount = (encoded[1] as u32) % width;
                    if amount == 0 {
                        encoded[0]
                    } else if op == "RotateLeft" {
                        ((encoded[0] << amount) | (encoded[0] >> (width - amount))) & mask
                    } else {
                        ((encoded[0] >> amount) | (encoded[0] << (width - amount))) & mask
                    }
                }
                _ => {
                    return Err(FormulaTracerError::InvalidBitVector(format!(
                        "UNSUPPORTED_BIT_OPERATION:{op}"
                    )))
                }
            };
            Ok(json!({"value":decode_python(value, width, signedness).to_string()}))
        }
        _ => Err(FormulaTracerError::InvalidBitVector(format!(
            "UNSUPPORTED_BITVECTOR_ACTION:{action}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exhaustive_unsigned_eight_bit_matches_finite_bit_sequences() {
        let rep = BitRepresentation {
            width: 8,
            signedness: Signedness::Unsigned,
            twos_complement: true,
            overflow: Overflow::Wrap,
        };
        let mut cases = 0usize;
        for a in 0i128..=255 {
            assert_eq!(bit_not(rep, a).unwrap(), (!a) & 255);
            cases += 1;
            for b in 0i128..=255 {
                assert_eq!(bit_and(rep, a, b).unwrap(), a & b);
                assert_eq!(bit_or(rep, a, b).unwrap(), a | b);
                assert_eq!(bit_xor(rep, a, b).unwrap(), a ^ b);
                cases += 3;
            }
        }
        assert_eq!(cases, 196_864);
    }
}
