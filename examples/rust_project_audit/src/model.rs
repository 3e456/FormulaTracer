use crate::constants::TON_SCALE;
use crate::math::weighted_sum;

pub fn calculate_total(values: &[f64]) -> f64 {
    let factor = 2.0 * TON_SCALE;
    weighted_sum(values, factor)
}
