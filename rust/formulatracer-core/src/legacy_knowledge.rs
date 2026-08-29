//! Versioned knowledge entries are data; all applicability decisions live here.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
fn invalid(m: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(m.into())
}
const EXACT: &[&str] = &[
    "EXACT",
    "EXACT_UNDER_ASSUMPTIONS",
    "DEFINITIONAL",
    "IDENTITY",
];
fn strings(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}
fn conditions(e: &Value) -> Vec<String> {
    [
        "preconditions",
        "domain_constraints",
        "type_constraints",
        "shape_constraints",
        "required_facts",
    ]
    .into_iter()
    .flat_map(|k| strings(e.get(k)))
    .collect()
}
fn is_exact(e: &Value) -> bool {
    EXACT.contains(&e.get("relation_kind").and_then(Value::as_str).unwrap_or(""))
}
fn pattern_vars(v: &Value, out: &mut BTreeSet<String>) {
    match v {
        Value::Object(m) => {
            if m.get("op").and_then(Value::as_str) == Some("PatternVariable") {
                if let Some(n) = m.get("name").and_then(Value::as_str) {
                    out.insert(n.into());
                }
            }
            for x in m.values() {
                pattern_vars(x, out)
            }
        }
        Value::Array(a) => {
            for x in a {
                pattern_vars(x, out)
            }
        }
        _ => {}
    }
}
fn validate_entry(e: &Value) -> Vec<String> {
    let id = e.get("knowledge_id").and_then(Value::as_str).unwrap_or("");
    let mut d = Vec::new();
    let relation = e.get("relation_kind").and_then(Value::as_str).unwrap_or("");
    let evidence = e.get("evidence_kind").and_then(Value::as_str).unwrap_or("");
    if ![
        "EXACT",
        "EXACT_UNDER_ASSUMPTIONS",
        "DEFINITIONAL",
        "IDENTITY",
        "TRANSFORMATION",
        "APPROXIMATION",
        "DISCRETIZATION",
        "TRUNCATION",
        "SAMPLING",
        "ALGORITHMIC_REALIZATION",
    ]
    .contains(&relation)
    {
        d.push(format!("INVALID_KNOWLEDGE_RELATION:{id}"))
    }
    if ![
        "LEAN_VERIFIED",
        "FORMALLY_DERIVED",
        "REFERENCE_THEOREM",
        "REFERENCE_CONTRACT",
        "USER_ASSUMPTION",
    ]
    .contains(&evidence)
    {
        d.push(format!("INVALID_KNOWLEDGE_EVIDENCE:{id}"))
    }
    if !e
        .get("lhs")
        .is_some_and(|v| v.as_object().is_some_and(|m| !m.is_empty()))
        || !e
            .get("rhs")
            .is_some_and(|v| v.as_object().is_some_and(|m| !m.is_empty()))
    {
        d.push(format!("KNOWLEDGE_EXPRESSION_MISSING:{id}"))
    }
    if relation == "EXACT_UNDER_ASSUMPTIONS" && conditions(e).is_empty() {
        d.push(format!("CONDITIONAL_KNOWLEDGE_WITHOUT_CONDITION:{id}"))
    }
    if ["REFERENCE_THEOREM", "REFERENCE_CONTRACT"].contains(&evidence)
        && e.get("reference").is_none_or(Value::is_null)
    {
        d.push(format!("REFERENCE_EVIDENCE_MISSING:{id}"))
    }
    let forward = e
        .get("forward_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let reverse = e
        .get("reverse_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !forward && !reverse {
        d.push(format!("KNOWLEDGE_DIRECTION_DISABLED:{id}"))
    }
    if reverse && e.pointer("/rhs/op").and_then(Value::as_str) == Some("PatternVariable") {
        d.push(format!("UNBOUNDED_REVERSE_PATTERN_VARIABLE:{id}"))
    }
    if is_exact(e) {
        let mut lhs = BTreeSet::new();
        let mut rhs = BTreeSet::new();
        pattern_vars(&e["lhs"], &mut lhs);
        pattern_vars(&e["rhs"], &mut rhs);
        if forward {
            let u = rhs.difference(&lhs).cloned().collect::<Vec<_>>();
            if !u.is_empty() {
                d.push(format!(
                    "EXACT_KNOWLEDGE_UNBOUND_FORWARD_VARIABLE:{id}:{}",
                    u.join(",")
                ))
            }
        }
        if reverse {
            let u = lhs.difference(&rhs).cloned().collect::<Vec<_>>();
            if !u.is_empty() {
                d.push(format!(
                    "EXACT_KNOWLEDGE_UNBOUND_REVERSE_VARIABLE:{id}:{}",
                    u.join(",")
                ))
            }
        }
    }
    d
}
fn matches(pattern: &Value, value: &Value, b: &mut BTreeMap<String, Value>) -> bool {
    if pattern.get("op").and_then(Value::as_str) == Some("PatternVariable") {
        let n = pattern.get("name").and_then(Value::as_str).unwrap_or("");
        if let Some(old) = b.get(n) {
            old == value
        } else {
            b.insert(n.into(), value.clone());
            true
        }
    } else {
        match (pattern, value) {
            (Value::Array(a), Value::Array(v)) => {
                a.len() == v.len() && a.iter().zip(v).all(|(x, y)| matches(x, y, b))
            }
            (Value::Object(a), Value::Object(v)) => a
                .iter()
                .all(|(k, x)| v.get(k).is_some_and(|y| matches(x, y, b))),
            _ => pattern == value,
        }
    }
}
fn template(v: &Value, b: &BTreeMap<String, Value>) -> Result<Value> {
    if v.get("op").and_then(Value::as_str) == Some("PatternVariable") {
        return b
            .get(v.get("name").and_then(Value::as_str).unwrap_or(""))
            .cloned()
            .ok_or_else(|| invalid("KNOWLEDGE_PATTERN_BINDING_MISSING"));
    }
    Ok(match v {
        Value::Array(a) => Value::Array(
            a.iter()
                .map(|x| template(x, b))
                .collect::<Result<Vec<_>>>()?,
        ),
        Value::Object(m) => Value::Object(
            m.iter()
                .map(|(k, x)| Ok((k.clone(), template(x, b)?)))
                .collect::<Result<_>>()?,
        ),
        _ => v.clone(),
    })
}
fn apply_at(
    node: &Value,
    pattern: &Value,
    replacement: &Value,
    out: &mut Vec<Value>,
) -> Result<()> {
    let mut b = BTreeMap::new();
    if matches(pattern, node, &mut b) {
        let candidate = template(replacement, &b)?;
        if candidate != *node {
            out.push(candidate)
        }
    }
    match node {
        Value::Object(m) => {
            for (k, v) in m {
                let mut children = Vec::new();
                apply_at(v, pattern, replacement, &mut children)?;
                for child in children {
                    let mut clone = m.clone();
                    clone.insert(k.clone(), child);
                    out.push(Value::Object(clone))
                }
            }
        }
        Value::Array(a) => {
            for (i, v) in a.iter().enumerate() {
                let mut children = Vec::new();
                apply_at(v, pattern, replacement, &mut children)?;
                for child in children {
                    let mut clone = a.clone();
                    clone[i] = child;
                    out.push(Value::Array(clone))
                }
            }
        }
        _ => {}
    }
    Ok(())
}
fn descriptor(e: &Value) -> Value {
    json!({"rule_id":e["knowledge_id"],"relation_kind":if e["relation_kind"]==json!("EXACT_UNDER_ASSUMPTIONS"){"EXACT_UNDER_ASSUMPTIONS"}else{"EXACT"},"preconditions":e.get("preconditions").cloned().unwrap_or(json!([])),"domain_constraints":e.get("domain_constraints").cloned().unwrap_or(json!([])),"type_constraints":e.get("type_constraints").cloned().unwrap_or(json!([])),"shape_constraints":e.get("shape_constraints").cloned().unwrap_or(json!([])),"assumptions":e.get("required_facts").cloned().unwrap_or(json!([])),"cost":e.get("rewrite_cost").cloned().unwrap_or(json!(1)),"priority":e.get("priority").cloned().unwrap_or(json!(100)),"evidence":e.get("reference").cloned().unwrap_or(Value::Null),"inverse_rule":null,"motifs":e.get("motif_tags").cloned().unwrap_or(json!([]))})
}
pub fn legacy_knowledge_operation(r: &Value) -> Result<Value> {
    let entries = r
        .get("entries")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    match r.get("action").and_then(Value::as_str).unwrap_or("") {
        "ENTRY_PROPERTIES" => {
            let e = &r["entry"];
            Ok(
                json!({"is_exact":is_exact(e),"all_conditions":conditions(e),"descriptor":descriptor(e)}),
            )
        }
        "VALIDATE_ENTRY" => Ok(json!({"diagnostics":validate_entry(&r["entry"])})),
        "SELECT" => {
            let motifs = strings(r.get("motifs"));
            let hints = strings(r.get("provider_hints"));
            let allowed = r
                .get("authorized_ids")
                .and_then(Value::as_array)
                .map(|v| v.iter().filter_map(Value::as_str).collect::<BTreeSet<_>>());
            let category = r.get("category").and_then(Value::as_str);
            let exact_only = r
                .get("exact_only")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let filter_motifs = r
                .get("filter_motifs")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            let mut selected = entries
                .into_iter()
                .filter(|e| {
                    category.is_none_or(|c| e["category"].as_str() == Some(c))
                        && (!exact_only || is_exact(e))
                        && allowed
                            .as_ref()
                            .is_none_or(|a| a.contains(e["knowledge_id"].as_str().unwrap_or("")))
                        && (!filter_motifs
                            || strings(e.get("motif_tags")).is_empty()
                            || strings(e.get("motif_tags"))
                                .iter()
                                .any(|v| motifs.contains(v))
                            || strings(e.get("provider_hints"))
                                .iter()
                                .any(|v| hints.contains(v)))
                })
                .collect::<Vec<_>>();
            selected.sort_by_key(|e| {
                (
                    e["priority"].as_i64().unwrap_or(100),
                    e["knowledge_id"].as_str().unwrap_or("").to_owned(),
                )
            });
            Ok(Value::Array(selected))
        }
        "METRICS" => {
            let mut c = BTreeMap::new();
            let mut rel = BTreeMap::new();
            let mut ev = BTreeMap::new();
            for e in &entries {
                *c.entry(e["category"].as_str().unwrap_or("")).or_insert(0) += 1;
                *rel.entry(e["relation_kind"].as_str().unwrap_or(""))
                    .or_insert(0) += 1;
                *ev.entry(e["evidence_kind"].as_str().unwrap_or(""))
                    .or_insert(0) += 1;
            }
            Ok(
                json!({"entries":entries.len(),"categories":c,"relations":rel,"evidence":ev,"exact_entries":entries.iter().filter(|e|is_exact(e)).count(),"conditional_entries":entries.iter().filter(|e|!conditions(e).is_empty()).count()}),
            )
        }
        "VALIDATE" => {
            Ok(json!({"diagnostics":entries.iter().flat_map(validate_entry).collect::<Vec<_>>()}))
        }
        "APPLY_ONCE" => {
            let e = &r["entry"];
            let mut out = Vec::new();
            if e.get("forward_enabled")
                .and_then(Value::as_bool)
                .unwrap_or(true)
            {
                apply_at(&r["node"], &e["lhs"], &e["rhs"], &mut out)?
            }
            if e.get("reverse_enabled")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                apply_at(&r["node"], &e["rhs"], &e["lhs"], &mut out)?
            }
            out.sort_by_key(|v| serde_json::to_string(v).unwrap_or_default());
            out.dedup();
            Ok(Value::Array(out))
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_KNOWLEDGE_ACTION:{action}"
        ))),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn non_exact_is_never_exact() {
        assert!(!is_exact(&json!({"relation_kind":"APPROXIMATION"})));
    }
}
