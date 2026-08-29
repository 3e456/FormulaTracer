use crate::{canonicalize, CanonicalPolicy};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TypedSubstitution {
    #[serde(default)]
    pub symbols: BTreeMap<String, Value>,
    #[serde(default)]
    pub obligations: Vec<String>,
    pub capture_avoiding: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UnificationResult {
    pub status: String,
    pub substitution: TypedSubstitution,
}

fn unify_inner(
    pattern: &Value,
    candidate: &Value,
    substitution: &mut BTreeMap<String, Value>,
    obligations: &mut Vec<String>,
) -> bool {
    if let Some(object) = pattern.as_object() {
        if object.get("op").and_then(Value::as_str) == Some("PatternVariable") {
            let Some(name) = object.get("name").and_then(Value::as_str) else {
                return false;
            };
            if let Some(required_op) = object.get("required_op").and_then(Value::as_str) {
                if candidate.get("op").and_then(Value::as_str) != Some(required_op) {
                    return false;
                }
            }
            if let Some(required_rank) = object.get("required_rank").and_then(Value::as_u64) {
                if candidate
                    .get("indices")
                    .and_then(Value::as_array)
                    .map(|indices| indices.len() as u64)
                    != Some(required_rank)
                {
                    return false;
                }
            }
            if let Some(required_dimensions) = object
                .get("required_named_dimensions")
                .and_then(Value::as_array)
            {
                match candidate.get("named_dimensions").and_then(Value::as_array) {
                    Some(actual) if actual == required_dimensions => {}
                    _ => obligations.push("named_dimension_evidence_missing_or_mismatched".into()),
                }
            }
            if let Some(existing) = substitution.get(name) {
                return existing == candidate;
            }
            substitution.insert(name.to_owned(), candidate.clone());
            return true;
        }
        let Some(candidate_object) = candidate.as_object() else {
            return false;
        };
        for (key, value) in object {
            if matches!(
                key.as_str(),
                "source" | "provenance" | "radix" | "original_text"
            ) {
                continue;
            }
            let Some(other) = candidate_object.get(key) else {
                return false;
            };
            if !unify_inner(value, other, substitution, obligations) {
                return false;
            }
        }
        if object.get("shape").is_some() && candidate_object.get("shape").is_none() {
            obligations.push("shape_evidence_missing".into());
        }
        true
    } else if let Some(items) = pattern.as_array() {
        let Some(other) = candidate.as_array() else {
            return false;
        };
        items.len() == other.len()
            && items
                .iter()
                .zip(other)
                .all(|(a, b)| unify_inner(a, b, substitution, obligations))
    } else {
        pattern == candidate
    }
}

pub fn typed_unify(pattern: &Value, candidate: &Value) -> UnificationResult {
    let pattern = canonicalize(pattern, CanonicalPolicy::default());
    let candidate = canonicalize(candidate, CanonicalPolicy::default());
    let mut symbols = BTreeMap::new();
    let mut obligations = vec![];
    let matched = unify_inner(&pattern, &candidate, &mut symbols, &mut obligations);
    UnificationResult {
        status: if matched && obligations.is_empty() {
            "MATCH"
        } else if matched {
            "MATCH_WITH_OBLIGATIONS"
        } else {
            "NO_MATCH"
        }
        .into(),
        substitution: TypedSubstitution {
            symbols,
            obligations,
            capture_avoiding: true,
        },
    }
}

pub fn substitute(value: &Value, mapping: &BTreeMap<String, Value>) -> Value {
    match value {
        Value::Object(object)
            if object.get("op").and_then(Value::as_str) == Some("PatternVariable") =>
        {
            object
                .get("name")
                .and_then(Value::as_str)
                .and_then(|name| mapping.get(name))
                .cloned()
                .unwrap_or_else(|| value.clone())
        }
        Value::Object(object)
            if object.get("op").and_then(Value::as_str) == Some("IndexedValue") =>
        {
            let mut result = object
                .iter()
                .map(|(key, item)| (key.clone(), substitute(item, mapping)))
                .collect::<serde_json::Map<_, _>>();
            if let Some(name) = object.get("name").and_then(Value::as_str) {
                if let Some(replacement) = mapping.get(name) {
                    if let Some(replacement_name) = replacement.get("name").and_then(Value::as_str)
                    {
                        result.insert("name".into(), Value::String(replacement_name.into()));
                    }
                }
            }
            Value::Object(result)
        }
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(k, v)| (k.clone(), substitute(v, mapping)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(|v| substitute(v, mapping)).collect()),
        _ => value.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn typed_index_patterns_enforce_rank_and_substitution_preserves_indices() {
        let pattern = json!({"op":"PatternVariable","name":"$v0","required_op":"IndexedValue","required_rank":2});
        assert_eq!(
            typed_unify(&pattern, &json!({"op":"IndexedValue","name":"A","indices":[{"op":"BoundVariable","name":"i"},{"op":"BoundVariable","name":"j"}]})).status,
            "MATCH"
        );
        assert_eq!(
            typed_unify(&pattern, &json!({"op":"IndexedValue","name":"x","indices":[{"op":"BoundVariable","name":"i"}]})).status,
            "NO_MATCH"
        );
        let mapping =
            BTreeMap::from([("$v0".into(), json!({"op":"FreeVariable","name":"quantity"}))]);
        assert_eq!(
            substitute(
                &json!({"op":"IndexedValue","name":"$v0","indices":[{"op":"BoundVariable","name":"i"}]}),
                &mapping
            ),
            json!({"op":"IndexedValue","name":"quantity","indices":[{"op":"BoundVariable","name":"i"}]})
        );
    }
}
