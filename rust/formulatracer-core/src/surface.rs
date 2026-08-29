//! Conservative TeX-first surface parser.
//!
//! This is intentionally not a general TeX engine. It recognizes a documented
//! mathematical subset and rejects notation whose meaning is not unique.

use crate::{FormulaTracerError, Result};
use serde_json::{json, Value};

#[derive(Debug, Clone, PartialEq)]
enum Token {
    Number(f64),
    Ident(String),
    Plus,
    Minus,
    Star,
    Slash,
    Caret,
    LParen,
    RParen,
    Comma,
}

pub fn parse_tex(tex: &str) -> Result<Value> {
    let uncommented = tex
        .lines()
        .map(|line| line.split_once('%').map(|(code, _)| code).unwrap_or(line))
        .collect::<Vec<_>>()
        .join(" ");
    let source = uncommented.trim();
    if source.is_empty() {
        return Err(invalid("EMPTY_TEX"));
    }
    if source.starts_with("\\sum_") {
        return parse_indexed_binder(source, "\\sum_", "FiniteSum", "InfiniteSeries");
    }
    if source.starts_with("\\prod_") {
        return parse_indexed_binder(source, "\\prod_", "FiniteProduct", "InfiniteProduct");
    }
    if source.starts_with("\\int_") {
        return parse_definite_integral(source);
    }
    if source.starts_with("\\lim_") {
        return parse_limit(source);
    }
    if source.starts_with("\\frac{d}{d") {
        return parse_derivative(source);
    }
    reject_ambiguous_indices(source)?;
    if source.contains("\\sum") || source.contains("\\int") || source.contains("\\lim") {
        return Err(incomplete("binder TeX parser"));
    }
    let normalized = normalize_tex(source)?;
    let tokens = tokenize(&normalized)?;
    let mut parser = Parser {
        tokens,
        position: 0,
    };
    let value = parser.expression(0)?;
    if parser.position != parser.tokens.len() {
        return Err(invalid("AMBIGUOUS_FORMULA_PARSE: trailing tokens"));
    }
    Ok(value)
}

fn take_braced(source: &str, start: usize) -> Result<(&str, usize)> {
    if source.as_bytes().get(start) != Some(&b'{') {
        return Err(invalid("TeX binder group required"));
    }
    let mut depth = 0usize;
    for (offset, byte) in source.as_bytes()[start..].iter().enumerate() {
        match byte {
            b'{' => depth += 1,
            b'}' => {
                depth -= 1;
                if depth == 0 {
                    let end = start + offset;
                    return Ok((&source[start + 1..end], end + 1));
                }
            }
            _ => {}
        }
    }
    Err(invalid("unclosed TeX binder group"))
}

fn parse_indexed_binder(
    source: &str,
    prefix: &str,
    finite_op: &str,
    infinite_op: &str,
) -> Result<Value> {
    let (lower_declaration, after_lower) = take_braced(source, prefix.len())?;
    let (binder, lower_text) = lower_declaration
        .split_once('=')
        .ok_or_else(|| invalid("finite sum requires an explicit lower bound"))?;
    if binder.len() != 1 || !binder.chars().all(|ch| ch.is_ascii_alphabetic()) {
        return Err(invalid("binder must be a single declared symbol"));
    }
    if source.as_bytes().get(after_lower) != Some(&b'^') {
        return Err(invalid("finite sum requires an explicit upper bound"));
    }
    let (upper_text, after_upper) = take_braced(source, after_lower + 1)?;
    let body_text = source[after_upper..].trim();
    let lower = parse_tex(lower_text.trim())?;
    let body = parse_bound_body(body_text, binder)?;
    if upper_text.trim() == "\\infty" {
        return Ok(json!({
            "op":infinite_op,
            "bound_index":binder,
            "lower":lower,
            "body":body,
            "convergence_status":"UNRESOLVED"
        }));
    }
    let upper_inclusive = parse_tex(upper_text.trim())?;
    let upper_exclusive = match upper_inclusive {
        Value::Object(ref object)
            if object.get("op").and_then(Value::as_str) == Some("Subtract")
                && object
                    .get("args")
                    .and_then(Value::as_array)
                    .is_some_and(|args| {
                        args.len() == 2
                            && args[1].get("op").and_then(Value::as_str) == Some("Constant")
                            && args[1].get("value").and_then(Value::as_f64) == Some(1.0)
                    }) =>
        {
            object["args"][0].clone()
        }
        value => json!({"op":"Add","args":[value,{"op":"Constant","value":1.0}]}),
    };
    Ok(json!({
        "op":finite_op,
        "bound_index":binder,
        "index_domain":{"lower":lower,"upper_exclusive":upper_exclusive},
        "body":body
    }))
}

fn parse_bound_body(source: &str, binder: &str) -> Result<Value> {
    let mut normalized = source.trim().to_string();
    let braced = format!("_{{{binder}}}");
    let compact = format!("_{binder}");
    for marker in [&braced, &compact] {
        while let Some(position) = normalized.find(marker) {
            let base_end = position;
            let base_start = normalized[..base_end]
                .char_indices()
                .rev()
                .take_while(|(_, ch)| ch.is_ascii_alphabetic())
                .last()
                .map(|(position, _)| position)
                .ok_or_else(|| invalid("AMBIGUOUS_NOTATION: indexed base requires a symbol"))?;
            let base = normalized[base_start..base_end].to_string();
            if base.chars().count() != 1 {
                return Err(invalid(
                    "AMBIGUOUS_NOTATION: indexed base requires a declaration",
                ));
            }
            normalized.replace_range(
                base_start..position + marker.len(),
                &format!("index({base},{binder})"),
            );
        }
    }
    let parsed = parse_tex(&normalized)?;
    Ok(bind_declared_index(parsed, binder))
}

fn bind_declared_index(value: Value, binder: &str) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .into_iter()
                .map(|item| bind_declared_index(item, binder))
                .collect(),
        ),
        Value::Object(mut object) => {
            if object.get("op").and_then(Value::as_str) == Some("FreeVariable")
                && object.get("name").and_then(Value::as_str) == Some(binder)
            {
                return json!({"op":"BoundVariable","name":binder});
            }
            if object.get("op").and_then(Value::as_str) == Some("FunctionCall")
                && object.get("name").and_then(Value::as_str) == Some("index")
            {
                if let Some(arguments) = object.get("args").and_then(Value::as_array) {
                    if arguments.len() == 2 {
                        let base = arguments[0].get("name").and_then(Value::as_str);
                        let index = arguments[1].get("name").and_then(Value::as_str);
                        if let (Some(base), Some(index)) = (base, index) {
                            if index == binder {
                                return json!({"op":"IndexedValue","name":base,
                                    "indices":[{"op":"BoundVariable","name":binder}]});
                            }
                        }
                    }
                }
            }
            for item in object.values_mut() {
                *item = bind_declared_index(item.take(), binder);
            }
            Value::Object(object)
        }
        other => other,
    }
}

fn parse_definite_integral(source: &str) -> Result<Value> {
    let (lower_text, after_lower) = take_braced(source, "\\int_".len())?;
    if source.as_bytes().get(after_lower) != Some(&b'^') {
        return Err(invalid("definite integral requires an upper bound"));
    }
    let (upper_text, after_upper) = take_braced(source, after_lower + 1)?;
    let body_and_measure = source[after_upper..].trim().replace("\\,", " ");
    let split = body_and_measure
        .rfind(" d")
        .or_else(|| body_and_measure.rfind("\\mathrm{d}"))
        .ok_or_else(|| invalid("AMBIGUOUS_NOTATION: integral measure must be explicit"))?;
    let (body_text, measure_text) = body_and_measure.split_at(split);
    let variable = measure_text
        .trim()
        .strip_prefix("\\mathrm{d}")
        .or_else(|| measure_text.trim().strip_prefix('d'))
        .map(str::trim)
        .ok_or_else(|| invalid("invalid integral measure"))?;
    if variable.chars().count() != 1 || !variable.chars().all(|ch| ch.is_ascii_alphabetic()) {
        return Err(invalid(
            "integral variable must be a single declared symbol",
        ));
    }
    Ok(json!({
        "op":"DefiniteIntegral",
        "bound_variable":variable,
        "lower":parse_tex(lower_text.trim())?,
        "upper":parse_tex(upper_text.trim())?,
        "body":bind_declared_index(parse_tex(body_text.trim())?, variable)
    }))
}

fn parse_limit(source: &str) -> Result<Value> {
    let (declaration, after) = take_braced(source, "\\lim_".len())?;
    let (variable, target) = declaration
        .split_once("\\to")
        .ok_or_else(|| invalid("limit requires an explicit \\to declaration"))?;
    let variable = variable.trim();
    if variable.chars().count() != 1 || !variable.chars().all(|ch| ch.is_ascii_alphabetic()) {
        return Err(invalid("limit variable must be a single declared symbol"));
    }
    let target = if target.trim() == "\\infty" {
        json!({"op":"Infinity","direction":"POSITIVE"})
    } else {
        parse_tex(target.trim())?
    };
    Ok(json!({
        "op":"Limit",
        "bound_variable":variable,
        "target":target,
        "direction":"TWO_SIDED",
        "body":bind_declared_index(parse_tex(source[after..].trim())?, variable)
    }))
}

fn parse_derivative(source: &str) -> Result<Value> {
    let (numerator, after_numerator) = take_braced(source, "\\frac".len())?;
    let (denominator, after_denominator) = take_braced(source, after_numerator)?;
    if numerator.trim() != "d" || !denominator.trim().starts_with('d') {
        return Err(invalid(
            "only explicit ordinary derivative notation is supported",
        ));
    }
    let variable = denominator.trim().trim_start_matches('d').trim();
    if variable.chars().count() != 1 || !variable.chars().all(|ch| ch.is_ascii_alphabetic()) {
        return Err(invalid(
            "derivative variable must be a single declared symbol",
        ));
    }
    Ok(json!({
        "op":"Derivative",
        "bound_variable":variable,
        "order":1,
        "body":bind_declared_index(parse_tex(source[after_denominator..].trim())?, variable)
    }))
}

fn invalid(message: &str) -> FormulaTracerError {
    FormulaTracerError::InvalidSemanticDocument(message.into())
}

fn incomplete(component: &'static str) -> FormulaTracerError {
    FormulaTracerError::NativeComponentIncomplete(component)
}

fn reject_ambiguous_indices(source: &str) -> Result<()> {
    if source.contains('_') && !source.contains("\\sum") {
        return Err(invalid("AMBIGUOUS_NOTATION: undeclared subscript role"));
    }
    Ok(())
}

fn normalize_tex(source: &str) -> Result<String> {
    fn group(chars: &[char], position: &mut usize) -> Result<String> {
        if chars.get(*position) != Some(&'{') {
            return Err(invalid("TeX group required"));
        }
        *position += 1;
        let start = *position;
        let mut depth = 1;
        while *position < chars.len() {
            match chars[*position] {
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        let value: String = chars[start..*position].iter().collect();
                        *position += 1;
                        return Ok(value);
                    }
                }
                _ => {}
            }
            *position += 1;
        }
        Err(invalid("unclosed TeX group"))
    }

    let chars: Vec<char> = source.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '\\' {
            i += 1;
            let start = i;
            while i < chars.len() && chars[i].is_ascii_alphabetic() {
                i += 1;
            }
            let command: String = chars[start..i].iter().collect();
            match command.as_str() {
                "left" | "right" => {}
                "cdot" | "times" => {
                    return Err(invalid(
                        "AMBIGUOUS_NOTATION: dot may denote scalar, inner, cross, tensor, or generic multiplication",
                    ))
                }
                "frac" => {
                    let numerator = group(&chars, &mut i)?;
                    let denominator = group(&chars, &mut i)?;
                    out.push('(');
                    out.push_str(&normalize_tex(&numerator)?);
                    out.push_str(")/(");
                    out.push_str(&normalize_tex(&denominator)?);
                    out.push(')');
                }
                "sqrt" | "sin" | "cos" | "tan" | "sinh" | "cosh" | "tanh" | "log" | "exp"
                | "abs" => {
                    out.push_str(&command);
                    while chars.get(i).is_some_and(|ch| ch.is_whitespace()) {
                        i += 1;
                    }
                    if chars.get(i) != Some(&'(') && chars.get(i) != Some(&'{') {
                        let start = i;
                        while chars.get(i).is_some_and(|ch| ch.is_alphanumeric()) {
                            i += 1;
                        }
                        if start == i {
                            return Err(invalid("AMBIGUOUS_NOTATION: function application"));
                        }
                        out.push('(');
                        out.extend(chars[start..i].iter());
                        out.push(')');
                    }
                }
                "pi" => out.push_str("pi"),
                "infty" => return Err(incomplete("infinite TeX parser")),
                "operatorname" => {
                    let name = group(&chars, &mut i)?;
                    if name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
                        out.push_str(&name);
                    } else {
                        return Err(invalid("invalid operator name"));
                    }
                }
                "bar" | "overline" => return Err(invalid("AMBIGUOUS_NOTATION: bar role")),
                "" => out.push(' '), // TeX spacing is not multiplication evidence.
                _ => return Err(invalid("UNRESOLVED_TEX_COMMAND")),
            }
            continue;
        }
        match chars[i] {
            '{' => out.push('('),
            '}' => out.push(')'),
            '_' => {
                out.push('_');
                if chars.get(i + 1) == Some(&'{') {
                    i += 2;
                    while i < chars.len() && chars[i] != '}' {
                        out.push(chars[i]);
                        i += 1;
                    }
                }
            }
            ch if ch.is_whitespace() => out.push(' '),
            '|' | '\'' | '<' | '>' => {
                return Err(invalid("AMBIGUOUS_NOTATION: overloaded notation"));
            }
            '*' => return Err(invalid("AMBIGUOUS_NOTATION: star role")),
            ch => out.push(ch),
        }
        i += 1;
    }
    Ok(out)
}

fn tokenize(source: &str) -> Result<Vec<Token>> {
    let chars: Vec<char> = source.chars().collect();
    let mut result = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let ch = chars[i];
        if ch.is_whitespace() {
            i += 1;
            continue;
        }
        if ch.is_ascii_digit() || ch == '.' {
            let start = i;
            i += 1;
            while i < chars.len()
                && (chars[i].is_ascii_digit()
                    || chars[i] == '.'
                    || chars[i] == 'e'
                    || chars[i] == 'E'
                    || ((chars[i] == '+' || chars[i] == '-')
                        && matches!(chars.get(i.wrapping_sub(1)), Some('e' | 'E'))))
            {
                i += 1;
            }
            let text: String = chars[start..i].iter().collect();
            let number = text
                .parse::<f64>()
                .map_err(|_| invalid("invalid numeric literal"))?;
            result.push(Token::Number(number));
            continue;
        }
        if ch.is_alphabetic() {
            let start = i;
            i += 1;
            while i < chars.len() && (chars[i].is_alphanumeric() || chars[i] == '_') {
                i += 1;
            }
            result.push(Token::Ident(chars[start..i].iter().collect()));
            continue;
        }
        result.push(match ch {
            '+' => Token::Plus,
            '-' => Token::Minus,
            '·' => Token::Star,
            '/' => Token::Slash,
            '^' => Token::Caret,
            '(' => Token::LParen,
            ')' => Token::RParen,
            ',' => Token::Comma,
            _ => return Err(invalid("unsupported TeX token")),
        });
        i += 1;
    }
    Ok(result)
}

struct Parser {
    tokens: Vec<Token>,
    position: usize,
}

impl Parser {
    fn expression(&mut self, minimum_binding_power: u8) -> Result<Value> {
        let token = self.next().ok_or_else(|| invalid("expression required"))?;
        let mut left = match token {
            Token::Number(value) => json!({"op":"Constant","value":value}),
            Token::Minus => {
                let argument = self.expression(7)?;
                json!({"op":"Negate","args":[argument]})
            }
            Token::Ident(name) => {
                if self.peek() == Some(&Token::LParen) {
                    self.next();
                    let mut arguments = vec![];
                    if self.peek() != Some(&Token::RParen) {
                        loop {
                            arguments.push(self.expression(0)?);
                            if self.peek() != Some(&Token::Comma) {
                                break;
                            }
                            self.next();
                        }
                    }
                    if self.next() != Some(Token::RParen) {
                        return Err(invalid("unclosed function call"));
                    }
                    json!({"op":"FunctionCall","name":name,"args":arguments})
                } else if name == "pi" {
                    json!({"op":"Constant","value":"pi"})
                } else {
                    if name.chars().count() > 1 {
                        return Err(invalid(
                            "AMBIGUOUS_NOTATION: juxtaposition or multi-letter symbol",
                        ));
                    }
                    json!({"op":"FreeVariable","name":name})
                }
            }
            Token::LParen => {
                let value = self.expression(0)?;
                if self.next() != Some(Token::RParen) {
                    return Err(invalid("unclosed parenthesis"));
                }
                value
            }
            _ => return Err(invalid("invalid prefix operator")),
        };
        loop {
            let (left_bp, right_bp, op) = match self.peek() {
                Some(Token::Plus) => (1, 2, "Add"),
                Some(Token::Minus) => (1, 2, "Subtract"),
                Some(Token::Star) => (3, 4, "Multiply"),
                Some(Token::Slash) => (3, 4, "Divide"),
                Some(Token::Caret) => (6, 5, "Power"),
                _ => break,
            };
            if left_bp < minimum_binding_power {
                break;
            }
            self.next();
            let right = self.expression(right_bp)?;
            if op == "Power" && !is_unambiguous_power_exponent(&right) {
                return Err(invalid(
                    "AMBIGUOUS_NOTATION: superscript may be power, inverse, transpose, or label",
                ));
            }
            left = json!({"op":op,"args":[left,right]});
        }
        Ok(left)
    }
    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.position)
    }
    fn next(&mut self) -> Option<Token> {
        let value = self.tokens.get(self.position).cloned();
        self.position += usize::from(value.is_some());
        value
    }
}

fn is_unambiguous_power_exponent(value: &Value) -> bool {
    value.get("op").and_then(Value::as_str) == Some("Constant")
        && value
            .get("value")
            .and_then(Value::as_f64)
            .is_some_and(|number| number >= 0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_documented_exact_subset_and_rejects_implicit_contraction() {
        let value = parse_tex(r"\frac{x^2}{2}+\sin(x)").unwrap();
        assert_eq!(value["op"], "Add");
        assert!(parse_tex(r"x_i y_i").is_err());
        assert!(parse_tex(r"\unknown{x}").is_err());
        assert!(parse_tex(r"A^T").is_err());
        assert!(parse_tex(r"A^{-1}").is_err());
        assert!(parse_tex(r"x*y").is_err());
        assert!(parse_tex(r"x \cdot y").is_err());
        assert!(parse_tex(r"x \times y").is_err());
        assert!(parse_tex(r"xy").is_err());
        assert!(parse_tex(r"x y").is_err());
        assert!(parse_tex(r"|x|").is_err());
        assert!(parse_tex(r"<x,y>").is_err());
        assert!(parse_tex(r"f'").is_err());
        assert!(parse_tex(r"\bar{x}").is_err());
        assert!(parse_tex(r"T_1").is_err());
        assert_eq!(
            parse_tex("x+1 % + fake").unwrap(),
            parse_tex("x+1").unwrap()
        );
        assert_eq!(parse_tex(r"\sin x").unwrap()["op"], "FunctionCall");
        let sum = parse_tex(r"\sum_{i=0}^{N-1} x_i").unwrap();
        assert_eq!(sum["op"], "FiniteSum");
        assert_eq!(sum["bound_index"], "i");
        assert_eq!(sum["index_domain"]["upper_exclusive"]["name"], "N");
        let series = parse_tex(r"\sum_{n=0}^{\infty} x_n").unwrap();
        assert_eq!(series["op"], "InfiniteSeries");
        assert_eq!(series["convergence_status"], "UNRESOLVED");
        let product = parse_tex(r"\prod_{i=1}^{N} x_i").unwrap();
        assert_eq!(product["op"], "FiniteProduct");
        let integral = parse_tex(r"\int_{0}^{1} f(x) \, dx").unwrap();
        assert_eq!(integral["op"], "DefiniteIntegral");
        assert_eq!(integral["body"]["args"][0]["op"], "BoundVariable");
        let limit = parse_tex(r"\lim_{x\to 0} f(x)").unwrap();
        assert_eq!(limit["op"], "Limit");
        let derivative = parse_tex(r"\frac{d}{dx} f(x)").unwrap();
        assert_eq!(derivative["op"], "Derivative");
    }
}
