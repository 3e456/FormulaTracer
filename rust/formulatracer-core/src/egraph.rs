use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::{
    semantic_hash, CanonicalPolicy, FormulaTracerError, NumericDomain, RelationKind, Result,
};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ENode {
    pub operator: String,
    pub children: Vec<usize>,
    pub semantic_hash: String,
    pub numeric_domain: Option<NumericDomain>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RewriteTrace {
    pub rule_id: String,
    pub from_hash: String,
    pub to_hash: String,
    pub relation: RelationKind,
    #[serde(default)]
    pub assumptions: Vec<String>,
}

#[derive(Debug, Default)]
pub struct ExactEGraph {
    nodes: Vec<ENode>,
    parents: Vec<usize>,
    by_hash: HashMap<String, usize>,
    pub trace: Vec<RewriteTrace>,
}

impl ExactEGraph {
    pub fn add_value(&mut self, value: &Value) -> Result<usize> {
        fn validate(value: &Value, root: bool) -> Result<()> {
            match value {
                Value::Object(object) => {
                    let op = object.get("op").and_then(Value::as_str);
                    if root && op.is_none() {
                        return Err(FormulaTracerError::InvalidSemanticDocument(
                            "e-graph root requires op".into(),
                        ));
                    }
                    if op == Some("PatternVariable") {
                        return Err(FormulaTracerError::InvalidSemanticDocument(
                            "wildcard pattern is not a well-formed concrete e-node".into(),
                        ));
                    }
                    if op == Some("BoundVariable")
                        && object.get("name").and_then(Value::as_str).is_none()
                    {
                        return Err(FormulaTracerError::InvalidSemanticDocument(
                            "bound variable requires a capture-safe name".into(),
                        ));
                    }
                    for item in object.values() {
                        validate(item, false)?;
                    }
                }
                Value::Array(items) => {
                    for item in items {
                        validate(item, false)?;
                    }
                }
                _ => {}
            }
            Ok(())
        }
        validate(value, true)?;
        let hash = semantic_hash(value, CanonicalPolicy::default())?;
        if let Some(id) = self.by_hash.get(&hash) {
            return Ok(*id);
        }
        let operator = value
            .get("op")
            .and_then(Value::as_str)
            .unwrap_or("Value")
            .to_owned();
        let id = self.nodes.len();
        self.nodes.push(ENode {
            operator,
            children: vec![],
            semantic_hash: hash.clone(),
            numeric_domain: value
                .get("numeric_domain")
                .cloned()
                .and_then(|value| serde_json::from_value(value).ok()),
        });
        self.parents.push(id);
        self.by_hash.insert(hash, id);
        Ok(id)
    }

    fn root(&mut self, id: usize) -> usize {
        if self.parents[id] != id {
            let root = self.root(self.parents[id]);
            self.parents[id] = root;
        }
        self.parents[id]
    }

    pub fn merge(
        &mut self,
        left: usize,
        right: usize,
        relation: RelationKind,
        rule_id: impl Into<String>,
        assumptions: Vec<String>,
    ) -> Result<usize> {
        if !relation.is_exact() {
            return Err(FormulaTracerError::NonExactMergeForbidden(format!(
                "{relation:?}"
            )));
        }
        if relation == RelationKind::ExactUnderAssumptions && assumptions.is_empty() {
            return Err(FormulaTracerError::ConstraintUnresolved(
                "exact-under-assumptions requires discharged assumptions".into(),
            ));
        }
        match (
            self.nodes[left].numeric_domain,
            self.nodes[right].numeric_domain,
        ) {
            (Some(a), Some(b)) if a != b => {
                return Err(FormulaTracerError::ConstraintUnresolved(format!(
                    "numeric domain mismatch: {a:?} vs {b:?}"
                )))
            }
            (Some(_), None) | (None, Some(_)) => {
                return Err(FormulaTracerError::ConstraintUnresolved(
                    "numeric domain evidence missing on one side".into(),
                ))
            }
            _ => {}
        }
        let l = self.root(left);
        let r = self.root(right);
        if l != r {
            self.parents[r] = l;
        }
        self.trace.push(RewriteTrace {
            rule_id: rule_id.into(),
            from_hash: self.nodes[left].semantic_hash.clone(),
            to_hash: self.nodes[right].semantic_hash.clone(),
            relation,
            assumptions,
        });
        Ok(l)
    }

    pub fn equivalent(&mut self, left: usize, right: usize) -> bool {
        self.root(left) == self.root(right)
    }
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }
    pub fn class_count(&mut self) -> usize {
        (0..self.nodes.len())
            .map(|id| self.root(id))
            .collect::<std::collections::HashSet<_>>()
            .len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn non_exact_relations_never_merge_classes() {
        let mut graph = ExactEGraph::default();
        let a = graph.add_value(&json!({"op":"Integral"})).unwrap();
        let b = graph.add_value(&json!({"op":"FiniteSum"})).unwrap();
        assert!(graph
            .merge(a, b, RelationKind::ApproximationOf, "quadrature", vec![])
            .is_err());
        assert!(!graph.equivalent(a, b));
    }

    #[test]
    fn wildcard_and_domain_mismatch_never_enter_an_exact_class() {
        let mut graph = ExactEGraph::default();
        assert!(graph
            .add_value(&json!({"op":"PatternVariable","name":"x"}))
            .is_err());
        let natural = graph
            .add_value(&json!({"op":"FreeVariable","name":"n","numeric_domain":"NATURAL"}))
            .unwrap();
        let integer = graph
            .add_value(&json!({"op":"FreeVariable","name":"z","numeric_domain":"INTEGER"}))
            .unwrap();
        assert!(graph
            .merge(
                natural,
                integer,
                RelationKind::ExactEquality,
                "invalid-domain",
                vec![]
            )
            .is_err());
        assert!(!graph.equivalent(natural, integer));
    }
}
