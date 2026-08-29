use serde_json::Value;

fn field_tex(value: &Value, key: &str, default: &str) -> String {
    value.get(key).map(to_tex).unwrap_or_else(|| default.into())
}

fn args(value: &Value) -> Vec<Value> {
    value
        .get("args")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

pub fn to_tex(value: &Value) -> String {
    let op = value.get("op").and_then(Value::as_str).unwrap_or("");
    match op {
        "Constant" => value
            .get("value")
            .map(|item| {
                item.as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| item.to_string())
            })
            .unwrap_or_else(|| "?".into()),
        "FreeVariable" | "BoundVariable" => value
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("?")
            .to_owned(),
        "IndexedValue" => format!(
            "{}_{{{}}}",
            value.get("name").and_then(Value::as_str).unwrap_or("?"),
            value
                .get("indices")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .map(to_tex)
                .collect::<Vec<_>>()
                .join(",")
        ),
        "Negate" => format!(
            "-{}",
            args(value)
                .first()
                .map(to_tex)
                .unwrap_or_else(|| "?".into())
        ),
        "Divide" => {
            let operands = args(value);
            format!(
                "\\frac{{{}}}{{{}}}",
                operands.first().map(to_tex).unwrap_or_else(|| "?".into()),
                operands.get(1).map(to_tex).unwrap_or_else(|| "?".into())
            )
        }
        "Add" | "Subtract" | "Multiply" | "FloorDivide" | "Modulo" | "Power" | "BitAnd"
        | "BitOr" | "BitXor" | "ShiftLeft" | "ShiftRight" | "LogicalAnd" | "LogicalOr" => {
            let symbol = match op {
                "Add" => "+",
                "Subtract" => "-",
                "Multiply" => "\\,",
                "FloorDivide" => "//",
                "Modulo" => "\\bmod",
                "Power" => "^",
                "BitAnd" => "\\mathbin{\\&}",
                "BitOr" => "\\mathbin{|}",
                "BitXor" => "\\mathbin{\\oplus}",
                "ShiftLeft" => "\\ll",
                "ShiftRight" => "\\gg",
                "LogicalAnd" => "\\land",
                "LogicalOr" => "\\lor",
                _ => unreachable!(),
            };
            format!(
                "{{{}}}",
                args(value)
                    .iter()
                    .map(to_tex)
                    .collect::<Vec<_>>()
                    .join(symbol)
            )
        }
        "FunctionCall" => format!(
            "\\{}({})",
            value.get("name").and_then(Value::as_str).unwrap_or("f"),
            args(value).iter().map(to_tex).collect::<Vec<_>>().join(",")
        ),
        "BitNot" | "LogicalNot" => format!(
            "{}({})",
            if op == "BitNot" {
                "\\operatorname{bitnot}"
            } else {
                "\\neg"
            },
            args(value)
                .first()
                .map(to_tex)
                .unwrap_or_else(|| "?".into())
        ),
        "RotateLeft" | "RotateRight" | "BitFieldExtract" | "BitFieldInsert" | "PopCount"
        | "Minimum" | "Maximum" | "Clamp" | "Indicator" | "RealPart" | "ImagPart" | "Conjugate"
        | "Argument" | "Magnitude" | "Quotient" | "DivMod" | "EncodeBits" | "DecodeBits" => {
            let operation_args = value
                .get("args")
                .and_then(Value::as_array)
                .cloned()
                .or_else(|| value.get("value").cloned().map(|item| vec![item]))
                .unwrap_or_default();
            let suffix = if op.starts_with("Bit") || op.starts_with("Rotate") {
                value
                    .pointer("/bit_representation/width")
                    .map(|item| format!("_{{{item}}}"))
                    .unwrap_or_default()
            } else {
                String::new()
            };
            format!(
                "\\operatorname{{{op}}}{suffix}({})",
                operation_args
                    .iter()
                    .map(to_tex)
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
        "Predicate" => field_tex(value, "expression", "?"),
        "Select" => format!(
            "\\begin{{cases}} {}, & {} \\\\ {}, & \\text{{otherwise}} \\end{{cases}}",
            field_tex(value, "then", "?"),
            value
                .pointer("/condition/expression")
                .or_else(|| value.get("condition"))
                .map(to_tex)
                .unwrap_or_else(|| "?".into()),
            field_tex(value, "else", "?")
        ),
        "Piecewise" => {
            let mut rows = value
                .get("cases")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .map(|case| {
                    let predicate = case
                        .pointer("/predicate/expression")
                        .or_else(|| case.get("predicate"))
                        .map(to_tex)
                        .unwrap_or_else(|| "?".into());
                    format!("{}, & {predicate}", field_tex(case, "expression", "?"))
                })
                .collect::<Vec<_>>();
            if let Some(otherwise) = value.get("otherwise") {
                rows.push(format!("{}, & \\text{{otherwise}}", to_tex(otherwise)));
            }
            format!("\\begin{{cases}} {} \\end{{cases}}", rows.join(" \\\\ "))
        }
        "FiniteSum" => format!(
            "\\sum_{{{}={}}}^{{{}-1}} {}",
            value
                .get("bound_index")
                .and_then(Value::as_str)
                .unwrap_or("i"),
            value
                .pointer("/index_domain/lower")
                .map(to_tex)
                .unwrap_or_else(|| "0".into()),
            value
                .pointer("/index_domain/upper_exclusive")
                .map(to_tex)
                .unwrap_or_else(|| "N".into()),
            field_tex(value, "body", "?")
        ),
        "InfiniteSeries" => format!(
            "\\sum_{{{}={}}}^{{\\infty}} {}",
            value
                .get("bound_index")
                .and_then(Value::as_str)
                .unwrap_or("i"),
            field_tex(value, "lower", "0"),
            field_tex(value, "body", "?")
        ),
        "Integral" => format!(
            "\\int_{{{}}}^{{{}}} {}\\,d{}",
            field_tex(value, "lower", "?"),
            field_tex(value, "upper", "?"),
            field_tex(value, "integrand", "?"),
            value.get("variable").and_then(Value::as_str).unwrap_or("x")
        ),
        "Limit" => format!(
            "\\lim_{{{}\\to{}}} {}",
            value.get("variable").and_then(Value::as_str).unwrap_or("x"),
            field_tex(value, "target", "?"),
            field_tex(value, "body", "?")
        ),
        _ => format!(
            "\\operatorname{{{}}}",
            if op.is_empty() { "unresolved" } else { op }
        ),
    }
}
