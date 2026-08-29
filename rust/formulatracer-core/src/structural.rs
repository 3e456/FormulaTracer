use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

const IGNORED_METADATA: &[&str] = &[
    "source",
    "source_span",
    "source_spans",
    "source_node_ids",
    "operator_span",
    "callable_span",
    "argument_spans",
    "keyword_spans",
    "condition_span",
    "origin",
    "origins",
    "provenance_id",
    "node_id",
    "expression_id",
    "temporary_id",
    "numeral_representation",
    "original_text",
    "literal_text",
];

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct StructuralFacts {
    #[serde(default)]
    pub commutative_operators: BTreeSet<String>,
    #[serde(default)]
    pub associative_operators: BTreeSet<String>,
    #[serde(default)]
    pub symbol_types: BTreeMap<String, Value>,
    #[serde(default)]
    pub explicit_symbol_mapping: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OperandPermutation {
    pub path: String,
    pub original_order: Vec<usize>,
    pub normalized_order: Vec<usize>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct IsomorphismWitness {
    #[serde(default)]
    pub mapping: BTreeMap<String, String>,
    #[serde(default)]
    pub binder_mapping: BTreeMap<String, String>,
    #[serde(default)]
    pub index_mapping: BTreeMap<String, String>,
    #[serde(default)]
    pub node_mapping: BTreeMap<String, String>,
    #[serde(default)]
    pub operand_permutations: Vec<OperandPermutation>,
    #[serde(default)]
    pub association_changes: Vec<String>,
    #[serde(default)]
    pub ignored_representation_metadata: BTreeSet<String>,
    #[serde(default)]
    pub required_facts: BTreeSet<String>,
    #[serde(default)]
    pub required_assumptions: BTreeSet<String>,
    #[serde(default)]
    pub blocked_reasons: BTreeSet<String>,
    #[serde(default)]
    pub provenance: Vec<String>,
    pub evidence_level: String,
    pub proof_authority: bool,
}

impl IsomorphismWitness {
    fn comparison_aid() -> Self {
        Self {
            evidence_level: "COMPARISON_AID".into(),
            proof_authority: false,
            provenance: vec!["formulatracer-core:typed-structural-isomorphism-v1".into()],
            ..Self::default()
        }
    }
    fn absorb(&mut self, other: Self) {
        self.binder_mapping.extend(other.binder_mapping);
        self.index_mapping.extend(other.index_mapping);
        self.operand_permutations.extend(other.operand_permutations);
        self.association_changes.extend(other.association_changes);
        self.ignored_representation_metadata
            .extend(other.ignored_representation_metadata);
        self.required_facts.extend(other.required_facts);
        self.required_assumptions.extend(other.required_assumptions);
        self.blocked_reasons.extend(other.blocked_reasons);
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct QuotientNormalizationResult {
    pub status: String,
    pub representative: Value,
    pub witness: IsomorphismWitness,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StructuralIsomorphismResult {
    pub status: String,
    pub left_representative: Value,
    pub right_representative: Value,
    pub witness: IsomorphismWitness,
    pub comparison_may_proceed: bool,
    pub establishes_mathematical_equality: bool,
}

fn binder_key(object: &Map<String, Value>, op: &str) -> Option<&'static str> {
    if object.contains_key("bound_index") {
        Some("bound_index")
    } else if matches!(op, "Integral" | "Derivative" | "Lambda") && object.contains_key("variable")
    {
        Some("variable")
    } else {
        None
    }
}

fn normalize_inner(
    value: &Value,
    facts: &StructuralFacts,
    binders: &BTreeMap<String, String>,
    next_binder: &mut usize,
    path: &str,
    witness: &mut IsomorphismWitness,
) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .iter()
                .enumerate()
                .map(|(index, item)| {
                    normalize_inner(
                        item,
                        facts,
                        binders,
                        next_binder,
                        &format!("{path}/{index}"),
                        witness,
                    )
                })
                .collect(),
        ),
        Value::Object(object) => {
            let op = object.get("op").and_then(Value::as_str).unwrap_or("");
            if op == "BoundVariable" {
                if let Some(name) = object.get("name").and_then(Value::as_str) {
                    if let Some(canonical) = binders.get(name) {
                        let mut result = object.clone();
                        result.insert("name".into(), Value::String(canonical.clone()));
                        witness.index_mapping.insert(name.into(), canonical.clone());
                        return Value::Object(result);
                    }
                }
            }
            let selected_binder = binder_key(object, op);
            let mut local_binders = binders.clone();
            let canonical_binder = selected_binder
                .and_then(|key| object.get(key).and_then(Value::as_str))
                .map(|name| {
                    let canonical = format!("#b{}", *next_binder);
                    *next_binder += 1;
                    local_binders.insert(name.into(), canonical.clone());
                    witness
                        .binder_mapping
                        .insert(name.into(), canonical.clone());
                    canonical
                });
            let mut result = Map::new();
            for (key, item) in object {
                if IGNORED_METADATA.contains(&key.as_str()) {
                    witness.ignored_representation_metadata.insert(key.clone());
                    continue;
                }
                if Some(key.as_str()) == selected_binder {
                    result.insert(
                        key.clone(),
                        Value::String(canonical_binder.clone().unwrap_or_default()),
                    );
                } else {
                    result.insert(
                        key.clone(),
                        normalize_inner(
                            item,
                            facts,
                            &local_binders,
                            next_binder,
                            &format!("{path}/{key}"),
                            witness,
                        ),
                    );
                }
            }
            if facts.associative_operators.contains(op) {
                if let Some(Value::Array(arguments)) = result.get_mut("args") {
                    let original_len = arguments.len();
                    let mut flattened = vec![];
                    for argument in arguments.drain(..) {
                        if argument.get("op").and_then(Value::as_str) == Some(op) {
                            if let Some(nested) = argument.get("args").and_then(Value::as_array) {
                                flattened.extend(nested.iter().cloned());
                                continue;
                            }
                        }
                        flattened.push(argument);
                    }
                    if flattened.len() != original_len {
                        witness.association_changes.push(path.into());
                        witness.required_facts.insert(format!("associative:{op}"));
                    }
                    *arguments = flattened;
                }
            }
            if facts.commutative_operators.contains(op) {
                if let Some(Value::Array(arguments)) = result.get_mut("args") {
                    let mut indexed = arguments.drain(..).enumerate().collect::<Vec<_>>();
                    indexed
                        .sort_by_key(|(_, item)| serde_json::to_string(item).unwrap_or_default());
                    let normalized_order =
                        indexed.iter().map(|(index, _)| *index).collect::<Vec<_>>();
                    if normalized_order != (0..normalized_order.len()).collect::<Vec<_>>() {
                        witness.operand_permutations.push(OperandPermutation {
                            path: path.into(),
                            original_order: (0..normalized_order.len()).collect(),
                            normalized_order,
                        });
                        witness.required_facts.insert(format!("commutative:{op}"));
                    }
                    *arguments = indexed.into_iter().map(|(_, item)| item).collect();
                }
            }
            Value::Object(result)
        }
        Value::Number(number) => {
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

pub fn quotient_normalize(
    expression: &Value,
    facts: &StructuralFacts,
) -> QuotientNormalizationResult {
    let mut witness = IsomorphismWitness::comparison_aid();
    let representative = normalize_inner(
        expression,
        facts,
        &BTreeMap::new(),
        &mut 0,
        "",
        &mut witness,
    );
    QuotientNormalizationResult {
        status: if &representative != expression {
            "QUOTIENT_NORMALIZED"
        } else {
            "STRUCTURALLY_IDENTICAL"
        }
        .into(),
        representative,
        witness,
    }
}

fn typed_symbol_correspondence(
    left: &str,
    right: &str,
    facts: &StructuralFacts,
    witness: &mut IsomorphismWitness,
) -> Option<bool> {
    if left == right {
        return Some(true);
    }
    if let Some(mapped) = facts.explicit_symbol_mapping.get(left) {
        if mapped == right && !witness.mapping.values().any(|existing| existing == right) {
            witness.mapping.insert(left.into(), right.into());
            witness
                .required_facts
                .insert(format!("explicit_symbol_mapping:{left}:{right}"));
            return Some(true);
        }
        return Some(false);
    }
    match (facts.symbol_types.get(left), facts.symbol_types.get(right)) {
        (Some(left_type), Some(right_type)) if left_type == right_type => {
            if let Some(existing) = witness.mapping.get(left) {
                return Some(existing == right);
            }
            if witness.mapping.values().any(|existing| existing == right) {
                return Some(false);
            }
            witness.mapping.insert(left.into(), right.into());
            witness
                .required_facts
                .insert(format!("typed_symbol_correspondence:{left}:{right}"));
            Some(true)
        }
        (Some(_), Some(_)) => Some(false),
        _ => {
            witness
                .blocked_reasons
                .insert(format!("SYMBOL_TYPE_UNRESOLVED:{left}:{right}"));
            None
        }
    }
}

fn compare_inner(
    left: &Value,
    right: &Value,
    facts: &StructuralFacts,
    path: &str,
    witness: &mut IsomorphismWitness,
) -> Option<bool> {
    if left == right {
        witness.node_mapping.insert(path.into(), path.into());
        return Some(true);
    }
    match (left, right) {
        (Value::Array(a), Value::Array(b)) => {
            if a.len() != b.len() {
                return Some(false);
            }
            for (index, (x, y)) in a.iter().zip(b).enumerate() {
                match compare_inner(x, y, facts, &format!("{path}/{index}"), witness) {
                    Some(true) => {}
                    other => return other,
                }
            }
            Some(true)
        }
        (Value::Object(a), Value::Object(b)) => {
            let left_op = a.get("op").and_then(Value::as_str);
            let right_op = b.get("op").and_then(Value::as_str);
            if left_op != right_op {
                return Some(false);
            }
            if matches!(left_op, Some("FreeVariable" | "IndexedValue")) {
                match typed_symbol_correspondence(
                    a.get("name").and_then(Value::as_str).unwrap_or(""),
                    b.get("name").and_then(Value::as_str).unwrap_or(""),
                    facts,
                    witness,
                ) {
                    Some(true) => {}
                    other => return other,
                }
            }
            if a.keys().collect::<BTreeSet<_>>() != b.keys().collect::<BTreeSet<_>>() {
                return Some(false);
            }
            for key in a.keys() {
                if key == "name" && matches!(left_op, Some("FreeVariable" | "IndexedValue")) {
                    continue;
                }
                match compare_inner(&a[key], &b[key], facts, &format!("{path}/{key}"), witness) {
                    Some(true) => {}
                    other => return other,
                }
            }
            witness.node_mapping.insert(path.into(), path.into());
            Some(true)
        }
        _ => Some(false),
    }
}

pub fn structural_isomorphism(
    left: &Value,
    right: &Value,
    facts: &StructuralFacts,
) -> StructuralIsomorphismResult {
    let left_normalized = quotient_normalize(left, facts);
    let right_normalized = quotient_normalize(right, facts);
    let mut witness = IsomorphismWitness::comparison_aid();
    witness.absorb(left_normalized.witness.clone());
    witness.absorb(right_normalized.witness.clone());
    let comparison = compare_inner(
        &left_normalized.representative,
        &right_normalized.representative,
        facts,
        "",
        &mut witness,
    );
    let status = match comparison {
        None => "ISOMORPHISM_UNRESOLVED",
        Some(false) => "NOT_STRUCTURALLY_ISOMORPHIC",
        Some(true) if left == right => "STRUCTURALLY_IDENTICAL",
        Some(true) if witness.required_facts.is_empty() => "STRUCTURALLY_ISOMORPHIC",
        Some(true) => "STRUCTURALLY_ISOMORPHIC_UNDER_FACTS",
    };
    StructuralIsomorphismResult {
        status: status.into(),
        left_representative: left_normalized.representative,
        right_representative: right_normalized.representative,
        witness,
        comparison_may_proceed: matches!(comparison, Some(true)),
        establishes_mathematical_equality: false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn variable(name: &str) -> Value {
        json!({"op":"FreeVariable","name":name})
    }
    #[test]
    fn alpha_binders_and_fact_gated_commutativity_have_witnesses_not_proof() {
        let sum_i =
            json!({"op":"FiniteSum","bound_index":"i","body":{"op":"BoundVariable","name":"i"}});
        let sum_j =
            json!({"op":"FiniteSum","bound_index":"j","body":{"op":"BoundVariable","name":"j"}});
        let alpha = structural_isomorphism(&sum_i, &sum_j, &StructuralFacts::default());
        assert_eq!(alpha.status, "STRUCTURALLY_ISOMORPHIC");
        assert!(!alpha.establishes_mathematical_equality);
        assert_eq!(alpha.witness.evidence_level, "COMPARISON_AID");
        let left = json!({"op":"Add","args":[variable("x"),variable("y")]});
        let right = json!({"op":"Add","args":[variable("b"),variable("a")]});
        let mut facts = StructuralFacts::default();
        facts.commutative_operators.insert("Add".into());
        for name in ["x", "y", "a", "b"] {
            facts
                .symbol_types
                .insert(name.into(), json!({"domain":"REAL"}));
        }
        let result = structural_isomorphism(&left, &right, &facts);
        assert_eq!(result.status, "STRUCTURALLY_ISOMORPHIC_UNDER_FACTS");
        assert!(!result.witness.operand_permutations.is_empty());
    }
    #[test]
    fn semantic_near_misses_are_never_quotiented() {
        let x = variable("x");
        let add = json!({"op":"Add","args":[x.clone(),{"op":"Constant","value":1}]});
        let subtract = json!({"op":"Subtract","args":[x,{"op":"Constant","value":1}]});
        assert_eq!(
            structural_isomorphism(&add, &subtract, &StructuralFacts::default()).status,
            "NOT_STRUCTURALLY_ISOMORPHIC"
        );
        let u8_value = json!({"op":"BitAnd","args":[],"bit_representation":{"width":8,"signedness":"UNSIGNED"}});
        let u16_value = json!({"op":"BitAnd","args":[],"bit_representation":{"width":16,"signedness":"UNSIGNED"}});
        assert_eq!(
            structural_isomorphism(&u8_value, &u16_value, &StructuralFacts::default()).status,
            "NOT_STRUCTURALLY_ISOMORPHIC"
        );
    }
    #[test]
    fn free_rename_without_types_is_unresolved() {
        let result =
            structural_isomorphism(&variable("x"), &variable("y"), &StructuralFacts::default());
        assert_eq!(result.status, "ISOMORPHISM_UNRESOLVED");
        assert!(!result.comparison_may_proceed);
    }
}
