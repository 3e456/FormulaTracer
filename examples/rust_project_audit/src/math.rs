pub fn weighted_sum(values: &[f64], factor: f64) -> f64 {
    values.iter().map(|x| x * factor).sum()
}

pub fn parallel_weighted_sum(values: &[f64], factor: f64) -> f64 {
    values.par_iter().map(|x| x * factor).sum()
}
