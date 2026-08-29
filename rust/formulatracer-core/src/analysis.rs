use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Interval {
    pub lower: f64,
    pub upper: f64,
}

impl Interval {
    pub fn new(lower: f64, upper: f64) -> Option<Self> {
        (lower <= upper && lower.is_finite() && upper.is_finite()).then_some(Self { lower, upper })
    }
    pub fn interval_add(self, other: Self) -> Self {
        Self {
            lower: self.lower + other.lower,
            upper: self.upper + other.upper,
        }
    }
    pub fn interval_sub(self, other: Self) -> Self {
        Self {
            lower: self.lower - other.upper,
            upper: self.upper - other.lower,
        }
    }
    pub fn interval_mul(self, other: Self) -> Self {
        let p = [
            self.lower * other.lower,
            self.lower * other.upper,
            self.upper * other.lower,
            self.upper * other.upper,
        ];
        Self {
            lower: p.iter().copied().fold(f64::INFINITY, f64::min),
            upper: p.iter().copied().fold(f64::NEG_INFINITY, f64::max),
        }
    }
    pub fn interval_div(self, other: Self) -> Option<Self> {
        if other.lower <= 0.0 && other.upper >= 0.0 {
            None
        } else {
            Some(self.interval_mul(Self {
                lower: 1.0 / other.upper,
                upper: 1.0 / other.lower,
            }))
        }
    }
    pub fn overlaps(self, other: Self) -> bool {
        self.lower <= other.upper && other.lower <= self.upper
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum VerificationStatus {
    ExactEquality,
    CertifiedWithinErrorBound,
    CertifiedIntervalOverlap,
    EmpiricallyWithinTolerance,
    OutsideCertifiedBound,
    BoundNotAvailable,
    Unresolved,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ErrorEvidence {
    pub status: VerificationStatus,
    pub absolute_bound: Option<f64>,
    pub assumptions: Vec<String>,
    pub provenance: Vec<String>,
}

pub fn compose_absolute_errors(parts: &[ErrorEvidence]) -> ErrorEvidence {
    if parts
        .iter()
        .any(|p| p.status == VerificationStatus::Unresolved)
    {
        return ErrorEvidence {
            status: VerificationStatus::Unresolved,
            absolute_bound: None,
            assumptions: vec![],
            provenance: vec![],
        };
    }
    let Some(bound) = parts
        .iter()
        .map(|p| p.absolute_bound)
        .collect::<Option<Vec<_>>>()
        .map(|v| v.into_iter().sum())
    else {
        return ErrorEvidence {
            status: VerificationStatus::BoundNotAvailable,
            absolute_bound: None,
            assumptions: parts.iter().flat_map(|p| p.assumptions.clone()).collect(),
            provenance: parts.iter().flat_map(|p| p.provenance.clone()).collect(),
        };
    };
    ErrorEvidence {
        status: VerificationStatus::CertifiedWithinErrorBound,
        absolute_bound: Some(bound),
        assumptions: parts.iter().flat_map(|p| p.assumptions.clone()).collect(),
        provenance: parts.iter().flat_map(|p| p.provenance.clone()).collect(),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum InfiniteProcessStatus {
    Convergent,
    Divergent,
    ConvergenceUnresolved,
    TruncationRequired,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InfiniteProcessEvidence {
    pub status: InfiniteProcessStatus,
    pub tail_bound: Option<f64>,
    pub assumptions: Vec<String>,
}

pub fn require_truncation(
    evidence: InfiniteProcessEvidence,
    tolerance: f64,
) -> InfiniteProcessEvidence {
    if tolerance <= 0.0 {
        return InfiniteProcessEvidence {
            status: InfiniteProcessStatus::ConvergenceUnresolved,
            tail_bound: None,
            assumptions: vec!["positive tolerance required".into()],
        };
    }
    match evidence.status {
        InfiniteProcessStatus::Convergent => InfiniteProcessEvidence {
            status: InfiniteProcessStatus::TruncationRequired,
            ..evidence
        },
        _ => evidence,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn division_across_zero_is_unresolved() {
        assert!(Interval::new(1.0, 2.0)
            .unwrap()
            .interval_div(Interval::new(-1.0, 1.0).unwrap())
            .is_none());
    }
}
