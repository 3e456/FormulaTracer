mod constants;
mod math;
mod model;

use crate::model::calculate_total;

fn main() {
    let values = vec![1.0, 2.0, 3.0];
    let result = calculate_total(&values);
    std::fs::write("result.txt", result.to_string());
}
