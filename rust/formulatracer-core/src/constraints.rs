use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

use crate::{AlgebraicStructure, NumericDomain};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TruthStatus {
    ProvenTrue,
    ProvenFalse,
    Unresolved,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Fact {
    pub subject: String,
    pub predicate: String,
    pub value: Value,
    pub evidence: String,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct FactEngine {
    #[serde(default)]
    facts: BTreeMap<(String, String), Fact>,
    #[serde(default)]
    conflicts: BTreeSet<(String, String)>,
}

impl FactEngine {
    pub fn assert(&mut self, fact: Fact) -> TruthStatus {
        let key = (fact.subject.clone(), fact.predicate.clone());
        if let Some(existing) = self.facts.get(&key) {
            if existing.value != fact.value {
                self.conflicts.insert(key);
                return TruthStatus::Unresolved;
            }
        }
        self.facts.insert(key, fact);
        TruthStatus::ProvenTrue
    }

    pub fn query(&self, subject: &str, predicate: &str, expected: &Value) -> TruthStatus {
        let key = (subject.to_owned(), predicate.to_owned());
        if self.conflicts.contains(&key) {
            return TruthStatus::Unresolved;
        }
        match self.facts.get(&key) {
            Some(fact) if &fact.value == expected => TruthStatus::ProvenTrue,
            Some(_) => TruthStatus::ProvenFalse,
            None => TruthStatus::Unresolved,
        }
    }

    pub fn supports_structure(
        &self,
        domain: NumericDomain,
        structure: AlgebraicStructure,
    ) -> TruthStatus {
        if domain == NumericDomain::Unknown {
            TruthStatus::Unresolved
        } else if domain.supports(structure) {
            TruthStatus::ProvenTrue
        } else {
            TruthStatus::ProvenFalse
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn naturals_are_not_a_ring() {
        assert_eq!(
            FactEngine::default()
                .supports_structure(NumericDomain::Natural, AlgebraicStructure::Ring),
            TruthStatus::ProvenFalse
        );
        assert_eq!(
            FactEngine::default().supports_structure(
                NumericDomain::Natural,
                AlgebraicStructure::CommutativeSemiring
            ),
            TruthStatus::ProvenTrue
        );
        assert_eq!(
            FactEngine::default()
                .supports_structure(NumericDomain::Boolean, AlgebraicStructure::BooleanAlgebra),
            TruthStatus::ProvenTrue
        );
        assert_eq!(
            FactEngine::default()
                .supports_structure(NumericDomain::Real, AlgebraicStructure::BooleanAlgebra),
            TruthStatus::ProvenFalse
        );
    }
}
