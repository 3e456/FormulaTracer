//! Native ownership of equality-saturation authorization and fact decisions.
use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};
use std::collections::BTreeSet;

fn invalid(message: impl Into<String>) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}
fn strings(value: Option<&Value>) -> Vec<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}
fn exact_kind(kind: &str) -> bool {
    matches!(
        kind,
        "EXACT"
            | "EXACT_UNDER_ASSUMPTIONS"
            | "ALGEBRAIC_EQUIVALENCE"
            | "IDENTITY_UNDER_ASSUMPTIONS"
    )
}
fn aliases(key: &str) -> &'static [&'static str] {
    match key {
        "x > 0" => &["x_positive_real"],
        "z is real" => &["z_real"],
        "n is natural" => &["n_natural"],
        "complex_semantics" => &["complex_valued"],
        "complex semantics" => &["complex_semantics", "complex_valued"],
        _ => &[],
    }
}
fn contradictions(key: &str) -> &'static [&'static str] {
    match key {
        "x > 0" => &["x <= 0", "x_nonpositive"],
        "x <= 0" => &["x > 0", "x_positive_real"],
        "x != 0" => &["x = 0"],
        "x = 0" => &["x != 0"],
        "n >= 0" => &["n < 0"],
        "n < 0" => &["n >= 0"],
        _ => &[],
    }
}
fn closure(structure: &str) -> &'static [&'static str] {
    match structure {
        "FIELD" => &["SEMIGROUP", "MONOID", "GROUP", "SEMIRING", "RING", "FIELD"],
        "COMMUTATIVE_RING" => &[
            "SEMIGROUP",
            "MONOID",
            "GROUP",
            "SEMIRING",
            "RING",
            "COMMUTATIVE_RING",
        ],
        "RING" => &["SEMIGROUP", "MONOID", "GROUP", "SEMIRING", "RING"],
        "COMMUTATIVE_SEMIRING" => &["SEMIGROUP", "MONOID", "SEMIRING", "COMMUTATIVE_SEMIRING"],
        "SEMIRING" => &["SEMIGROUP", "MONOID", "SEMIRING"],
        "GROUP" => &["SEMIGROUP", "MONOID", "GROUP"],
        "MONOID" => &["SEMIGROUP", "MONOID"],
        "SEMIGROUP" => &["SEMIGROUP"],
        _ => &[],
    }
}

fn assert_one(facts: &mut Vec<Value>, conflicts: &mut Vec<Value>, item: Value) -> bool {
    let subject = item
        .get("subject")
        .and_then(Value::as_str)
        .unwrap_or("global");
    let key = item.get("key").and_then(Value::as_str).unwrap_or("");
    let value = item.get("value").cloned().unwrap_or(json!(true));
    if let Some(previous) = facts
        .iter()
        .find(|f| f["subject"] == json!(subject) && f["key"] == json!(key))
    {
        if previous["value"] != value {
            conflicts
                .push(json!({"subject":subject,"key":key,"left":previous["value"],"right":value}));
            return false;
        }
        return true;
    }
    if value == json!(true) {
        for opposite in contradictions(key) {
            if facts.iter().any(|f| {
                (f["subject"] == json!(subject) || f["subject"] == json!("global"))
                    && f["key"] == json!(opposite)
                    && f["value"] == json!(true)
            }) {
                conflicts.push(json!({"subject":subject,"key":key,"left":true,"right":format!("contradicts:{opposite}")}));
                return false;
            }
        }
        if key.starts_with("numeric_domain:") {
            if let Some(old) = facts.iter().find(|f| {
                f["subject"] == json!(subject)
                    && f["key"]
                        .as_str()
                        .is_some_and(|k| k.starts_with("numeric_domain:"))
                    && f["key"] != json!(key)
                    && f["value"] == json!(true)
            }) {
                conflicts.push(
                    json!({"subject":subject,"key":"numeric_domain","left":old["key"],"right":key}),
                );
                return false;
            }
        }
    }
    facts.push(item.clone());
    if value == json!(true) {
        for alias in aliases(key) {
            assert_one(
                facts,
                conflicts,
                json!({"key":alias,"value":true,"subject":subject,"evidence":format!("DERIVED_FROM:{key}")}),
            );
        }
        if let Some(s) = key.strip_prefix("algebraic_structure:") {
            for implied in closure(s) {
                let implied_key = format!("algebraic_structure:{implied}");
                if implied_key != key {
                    assert_one(
                        facts,
                        conflicts,
                        json!({"key":implied_key,"value":true,"subject":subject,"evidence":format!("DERIVED_FROM:{key}")}),
                    );
                }
            }
        }
    }
    true
}
fn knows(facts: &[Value], statement: &str, subject: &str) -> bool {
    facts.iter().any(|f| {
        (f["subject"] == json!(subject) || f["subject"] == json!("global"))
            && f["key"] == json!(statement)
            && f["value"] == json!(true)
    })
}
fn state(r: &Value) -> (Vec<Value>, Vec<Value>) {
    (
        r.get("facts")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
        r.get("conflicts")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
    )
}

pub fn legacy_equality_operation(r: &Value) -> Result<Value> {
    match r.get("action").and_then(Value::as_str).unwrap_or("") {
        "FACT_ASSERT" => {
            let (mut facts, mut conflicts) = state(r);
            let accepted = assert_one(&mut facts, &mut conflicts, r["fact"].clone());
            Ok(json!({"accepted":accepted,"facts":facts,"conflicts":conflicts}))
        }
        "FACT_KNOWS" => {
            let (facts, _) = state(r);
            Ok(
                json!({"knows":knows(&facts,r["statement"].as_str().unwrap_or(""),r.get("subject").and_then(Value::as_str).unwrap_or("global"))}),
            )
        }
        "FACT_MISSING" => {
            let (facts, _) = state(r);
            let mut required = Vec::new();
            for key in [
                "preconditions",
                "domain_constraints",
                "type_constraints",
                "shape_constraints",
                "assumptions",
            ] {
                required.extend(strings(r["rule"].get(key)));
            }
            Ok(
                json!({"missing":required.into_iter().filter(|x|!knows(&facts,x,"global")).collect::<Vec<_>>()}),
            )
        }
        "FACT_MERGE" => {
            let (mut facts, mut conflicts) = state(r);
            let mut accepted = true;
            for item in r
                .get("other_facts")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
            {
                accepted = assert_one(&mut facts, &mut conflicts, item) && accepted;
            }
            Ok(
                json!({"accepted":accepted&&conflicts.is_empty(),"facts":facts,"conflicts":conflicts}),
            )
        }
        "UNION_VALIDATE" => {
            let mut facts = Vec::new();
            let mut conflicts = Vec::new();
            let mut accepted = true;
            for item in r
                .get("left_facts")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .chain(
                    r.get("right_facts")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten(),
                )
            {
                accepted = assert_one(&mut facts, &mut conflicts, item.clone()) && accepted;
            }
            Ok(
                json!({"accepted":accepted&&conflicts.is_empty(),"facts":facts,"conflicts":conflicts}),
            )
        }
        "RELATION_VALIDATE" => {
            let kind = r["relation_kind"].as_str().unwrap_or("");
            let allowed = matches!(
                kind,
                "APPROXIMATION_OF"
                    | "DISCRETIZATION_OF"
                    | "TRUNCATED_TO"
                    | "SAMPLED_AS"
                    | "TRANSFORMED_TO"
                    | "ALGORITHMICALLY_REALIZED_BY"
            );
            Ok(json!({"accepted":allowed,"relation_kind":kind}))
        }
        "PACK_SELECT" => {
            let motifs = strings(r.get("motifs"))
                .into_iter()
                .collect::<BTreeSet<_>>();
            let useful = strings(r.get("useful_rewrites"))
                .into_iter()
                .collect::<BTreeSet<_>>();
            let mut selected = r
                .get("packs")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter(|p| {
                    strings(p.get("motifs")).iter().any(|x| motifs.contains(x))
                        || strings(p.get("rule_ids"))
                            .iter()
                            .any(|x| useful.contains(x))
                })
                .collect::<Vec<_>>();
            selected.sort_by_key(|p| p["pack_id"].as_str().unwrap_or("").to_owned());
            Ok(Value::Array(selected))
        }
        "RULES_SELECT" => {
            let authorized = strings(r.get("authorized"))
                .into_iter()
                .collect::<BTreeSet<_>>();
            let eligible = strings(r.get("eligible"))
                .into_iter()
                .collect::<BTreeSet<_>>();
            let mut rules = r
                .get("rules")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter(|x| {
                    let id = x["rule_id"].as_str().unwrap_or("");
                    authorized.contains(id)
                        && exact_kind(x["relation_kind"].as_str().unwrap_or(""))
                        && (eligible.is_empty() || eligible.contains(id))
                })
                .collect::<Vec<_>>();
            rules.sort_by_key(|x| {
                (
                    x["cost"].as_i64().unwrap_or(1),
                    x["priority"].as_i64().unwrap_or(100),
                    x["rule_id"].as_str().unwrap_or("").to_owned(),
                )
            });
            Ok(Value::Array(rules))
        }
        "EXTRACT" => {
            let mut candidates = r
                .get("candidates")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            candidates.sort_by_key(|x| {
                (
                    x["cost"].as_i64().unwrap_or(0),
                    serde_json::to_string(&x["expression"])
                        .unwrap_or_default()
                        .len(),
                    x["expression_id"].as_str().unwrap_or("").to_owned(),
                )
            });
            Ok(candidates
                .first()
                .map(|x| x["expression"].clone())
                .unwrap_or(Value::Null))
        }
        "SATURATION_STATUS" => {
            let exhausted = r.get("exhausted").and_then(Value::as_bool).unwrap_or(false);
            let iterations = r["iterations"].as_u64().unwrap_or(0);
            let limit = r["iteration_limit"].as_u64().unwrap_or(0);
            let changed = r.get("changed").and_then(Value::as_bool).unwrap_or(false);
            let blocked = r["blocked_count"].as_u64().unwrap_or(0);
            let trace = r["trace_count"].as_u64().unwrap_or(0);
            let status = if exhausted || (iterations == limit && changed) {
                "SATURATION_BUDGET_EXHAUSTED"
            } else if blocked > 0 && trace == 0 {
                "CONDITIONALLY_BLOCKED"
            } else {
                "SATURATED"
            };
            Ok(
                json!({"status":status,"diagnostics":if status=="SATURATED"{vec![]}else{vec![status]}}),
            )
        }
        action => Err(invalid(format!(
            "UNSUPPORTED_LEGACY_EQUALITY_ACTION:{action}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn nonexact_rules_are_never_selected() {
        let r=legacy_equality_operation(&json!({"action":"RULES_SELECT","authorized":["bad"],"eligible":[],"rules":[{"rule_id":"bad","relation_kind":"APPROXIMATION_OF"}]})).unwrap();
        assert_eq!(r, json!([]));
    }
}
