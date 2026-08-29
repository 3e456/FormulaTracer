use formulatracer_core::Formula;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let theory = Formula::from_json(r#"{"op":"Constant","value":42,"radix":16}"#)?;
    let implementation = Formula::from_json(r#"{"op":"Constant","value":42,"radix":10}"#)?;
    let result = theory.verify_against(&implementation);
    println!("{}", result.explain("en"));
    println!("{}", result.to_json()?);
    assert_eq!(result.status, "EXACT_EQUALITY");
    Ok(())
}
