use std::collections::{BTreeMap, HashMap};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::{Result, SemanticDocument};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CanonicalPolicy {
    pub ignore_source_provenance: bool,
    pub ignore_numeral_presentation: bool,
    pub alpha_normalize: bool,
    pub sort_commutative_arguments: bool,
}

impl Default for CanonicalPolicy {
    fn default() -> Self {
        Self {
            ignore_source_provenance: true,
            ignore_numeral_presentation: true,
            alpha_normalize: true,
            sort_commutative_arguments: true,
        }
    }
}

fn ignored_key(key: &str, policy: CanonicalPolicy) -> bool {
    (policy.ignore_source_provenance
        && matches!(
            key,
            "source"
                | "source_span"
                | "source_spans"
                | "source_node_ids"
                | "operator_span"
                | "callable_span"
                | "argument_spans"
                | "keyword_spans"
                | "condition_span"
                | "source_origin"
                | "source_correspondence"
                | "origin"
                | "origins"
                | "provenance"
                | "location"
                | "line"
                | "column"
        ))
        || (policy.ignore_numeral_presentation
            && matches!(
                key,
                "radix"
                    | "original_text"
                    | "literal_text"
                    | "numeral_representation"
                    | "mathematical_semantic"
                    | "shape_constraints"
                    | "alignment_constraints"
                    | "resolution_trace"
                    | "reduction_order"
                    | "lowered_from"
            ))
}

fn canonicalize_inner(
    value: &Value,
    policy: CanonicalPolicy,
    binders: &mut HashMap<String, String>,
    free_symbols: &mut HashMap<String, String>,
    next_binder: &mut usize,
    next_free_symbol: &mut usize,
) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| {
                    canonicalize_inner(
                        item,
                        policy,
                        binders,
                        free_symbols,
                        next_binder,
                        next_free_symbol,
                    )
                })
                .collect(),
        ),
        Value::Object(object) => {
            let mut local_binders = binders.clone();
            let op = object.get("op").and_then(Value::as_str).unwrap_or("");
            let binder_key = if object.contains_key("bound_index") {
                Some("bound_index")
            } else if matches!(op, "Integral" | "Derivative" | "Lambda")
                && object.contains_key("variable")
            {
                Some("variable")
            } else {
                None
            };
            let binder_replacement = if policy.alpha_normalize {
                binder_key
                    .and_then(|key| object.get(key).and_then(Value::as_str))
                    .map(|name| {
                        let canonical_name = format!("_b{}", *next_binder);
                        *next_binder += 1;
                        local_binders.insert(name.to_owned(), canonical_name.clone());
                        canonical_name
                    })
            } else {
                None
            };
            let mut canonical = BTreeMap::<String, Value>::new();
            for (key, raw) in object {
                if ignored_key(key, policy) {
                    continue;
                }
                let mut item = raw.clone();
                if policy.alpha_normalize {
                    if Some(key.as_str()) == binder_key {
                        if let Some(canonical_name) = &binder_replacement {
                            item = Value::String(canonical_name.clone());
                        }
                    } else if key == "name" && matches!(op, "BoundVariable") {
                        if let Some(name) = raw.as_str() {
                            if let Some(replacement) = binders.get(name) {
                                item = Value::String(replacement.clone());
                            }
                        }
                    } else if key == "name" && matches!(op, "FreeVariable" | "IndexedValue") {
                        if let Some(name) = raw.as_str() {
                            let replacement =
                                free_symbols.entry(name.to_owned()).or_insert_with(|| {
                                    let canonical_name = format!("_v{}", *next_free_symbol);
                                    *next_free_symbol += 1;
                                    canonical_name
                                });
                            item = Value::String(replacement.clone());
                        }
                    }
                }
                canonical.insert(
                    key.clone(),
                    canonicalize_inner(
                        &item,
                        policy,
                        &mut local_binders,
                        free_symbols,
                        next_binder,
                        next_free_symbol,
                    ),
                );
            }
            if policy.sort_commutative_arguments
                && matches!(
                    op,
                    "Add" | "Multiply" | "LogicalAnd" | "LogicalOr" | "BitAnd" | "BitOr" | "BitXor"
                )
            {
                if let Some(Value::Array(args)) = canonical.get_mut("args") {
                    args.sort_by_key(|item| serde_json::to_string(item).unwrap_or_default());
                }
            }
            Value::Object(Map::from_iter(canonical))
        }
        Value::Number(number) => {
            // Python's numeric equality treats integral floats and integers as
            // the same mathematical numeral. Preserve that semantic identity
            // without rounding non-integral values.
            if let Some(float) = number.as_f64() {
                if float.is_finite()
                    && float.fract() == 0.0
                    && float >= i64::MIN as f64
                    && float <= i64::MAX as f64
                {
                    return Value::Number(serde_json::Number::from(float as i64));
                }
            }
            value.clone()
        }
        _ => value.clone(),
    }
}

pub fn canonicalize(value: &Value, policy: CanonicalPolicy) -> Value {
    canonicalize_inner(
        value,
        policy,
        &mut HashMap::new(),
        &mut HashMap::new(),
        &mut 0,
        &mut 0,
    )
}

pub fn canonical_json(value: &Value, policy: CanonicalPolicy) -> Result<String> {
    Ok(serde_json::to_string(&canonicalize(value, policy))?)
}

pub fn semantic_hash(value: &Value, policy: CanonicalPolicy) -> Result<String> {
    let bytes = canonical_json(value, policy)?;
    Ok(format!("{:x}", Sha256::digest(bytes.as_bytes())))
}

pub fn document_semantic_hash(document: &SemanticDocument) -> Result<String> {
    semantic_hash(&document.payload, CanonicalPolicy::default())
}

pub fn semantic_equal(left: &Value, right: &Value) -> bool {
    canonicalize(left, CanonicalPolicy::default())
        == canonicalize(right, CanonicalPolicy::default())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn numeral_presentation_is_not_value_semantics() {
        assert!(semantic_equal(
            &json!({"op":"Constant","value":42,"radix":16,"original_text":"0x2a"}),
            &json!({"op":"Constant","value":42,"radix":10})
        ));
        assert!(semantic_equal(
            &json!({"op":"Constant","value":2}),
            &json!({"op":"Constant","value":2.0,"numeral_representation":{"radix":10}})
        ));
    }

    #[test]
    fn alpha_and_commutative_normalization_are_stable() {
        let a = json!({"op":"FiniteSum","bound_index":"i","body":{"op":"Add","args":[
            {"op":"BoundVariable","name":"i"},{"op":"FreeVariable","name":"x"}]}});
        let b = json!({"op":"FiniteSum","bound_index":"k","body":{"op":"Add","args":[
            {"op":"FreeVariable","name":"x"},{"op":"BoundVariable","name":"k"}]}});
        assert!(semantic_equal(&a, &b));
    }

    #[test]
    fn free_and_indexed_symbols_are_compared_by_bijective_correspondence() {
        let a = json!({"op":"TensorContraction","kind":"dot","args":[
            {"op":"FreeVariable","name":"x"},{"op":"IndexedValue","name":"weights","indices":[]}]});
        let b = json!({"op":"TensorContraction","kind":"dot","args":[
            {"op":"FreeVariable","name":"right"},{"op":"IndexedValue","name":"coefficients","indices":[]}]});
        assert!(semantic_equal(&a, &b));

        let pair = json!({"op":"TensorContraction","kind":"dot","args":[
            {"op":"FreeVariable","name":"x"},{"op":"FreeVariable","name":"y"}]});
        let non_bijective = json!({"op":"TensorContraction","kind":"dot","args":[
            {"op":"FreeVariable","name":"right"},{"op":"FreeVariable","name":"right"}]});
        assert!(!semantic_equal(&pair, &non_bijective));
    }
}
