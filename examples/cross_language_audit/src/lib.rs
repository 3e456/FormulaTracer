use pyo3::prelude::*;

#[pyfunction]
pub fn scale(value: f64, factor: f64) -> f64 {
    value * factor
}

#[pymodule]
fn native_ext(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(scale, module)?)?;
    Ok(())
}
