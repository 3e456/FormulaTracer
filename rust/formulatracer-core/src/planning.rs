//! Native high-recall provider planning with strict typed adoption.
use crate::{semantic_equal, typed_unify, Result};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Default, Clone)]
struct Features {
    ops: BTreeSet<String>,
    functions: BTreeSet<String>,
    motifs: BTreeSet<String>,
    rank: usize,
    bound: usize,
}
fn visit(
    value: &Value,
    path: &mut Vec<Value>,
    nodes: &mut Vec<(Vec<Value>, Value)>,
    f: &mut Features,
) {
    if let Some(o) = value.as_object() {
        if let Some(op) = o.get("op").and_then(Value::as_str) {
            f.ops.insert(op.into());
            nodes.push((path.clone(), value.clone()));
            if op == "FunctionCall" {
                if let Some(n) = o.get("name").and_then(Value::as_str) {
                    f.functions.insert(n.to_lowercase());
                }
            }
            if op == "IndexedValue" {
                f.rank = f.rank.max(
                    o.get("indices")
                        .and_then(Value::as_array)
                        .map_or(0, Vec::len),
                );
            }
            if o.get("bound_index").is_some() {
                f.bound += 1;
            }
        }
        for (k, v) in o {
            path.push(json!(k));
            visit(v, path, nodes, f);
            path.pop();
        }
    } else if let Some(a) = value.as_array() {
        for (i, v) in a.iter().enumerate() {
            path.push(json!(i));
            visit(v, path, nodes, f);
            path.pop();
        }
    }
}
fn features(value: &Value) -> (Features, Vec<(Vec<Value>, Value)>) {
    let mut f = Features::default();
    let mut n = vec![];
    visit(value, &mut vec![], &mut n, &mut f);
    for (op, m) in [
        ("FiniteSum", "finite_sum"),
        ("InfiniteSeries", "series"),
        ("Integral", "integral"),
        ("Factorial", "factorial"),
        ("Derivative", "derivative"),
        ("Transpose", "transpose"),
        ("MatMul", "matmul"),
        ("Convolution", "convolution"),
        ("Multiply", "multiply"),
        ("Divide", "divide"),
        ("Add", "add"),
        ("Power", "power"),
    ] {
        if f.ops.contains(op) {
            f.motifs.insert(m.into());
        }
    }
    f.motifs.extend(f.functions.clone());
    if f.functions.contains("exp") && f.ops.contains("FiniteSum") {
        f.motifs
            .extend(["complex_exponential".into(), "fourier".into()]);
    }
    if f.ops.contains("Factorial") || f.functions.contains("factorial") {
        f.motifs.extend(["factorial".into(), "series".into()]);
    }
    if f.ops.contains("Integral") && f.functions.contains("exp") {
        f.motifs.extend(["transform".into(), "laplace".into()]);
    }
    if f.ops.contains("FiniteSum") && f.ops.contains("Multiply") {
        f.motifs
            .extend(["weighted_sum".into(), "indexed_multiplication".into()]);
    }
    (f, n)
}
fn score(q: &Value, c: &Value) -> (f64, Vec<String>) {
    if c["provider_id"] == "python.builtin.direct" {
        return (0.1, vec!["universal direct lowering fallback".into()]);
    }
    let (qf, _) = features(q);
    let (pf, _) = features(&c["pattern"]);
    let cm: BTreeSet<String> = c
        .get("motifs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_string)
        .collect();
    let shared: Vec<_> = qf.motifs.intersection(&cm).cloned().collect();
    let mut s = shared
        .iter()
        .map(|m| {
            if matches!(
                m.as_str(),
                "complex_exponential"
                    | "finite_sum"
                    | "integral"
                    | "factorial"
                    | "convolution"
                    | "shifted_evaluation"
            ) {
                4.0
            } else {
                2.0
            }
        })
        .sum::<f64>();
    s += 1.5 * qf.ops.intersection(&pf.ops).count() as f64;
    if qf.bound > 0 && pf.bound > 0 {
        s += 2.0;
    }
    if qf.rank > 0 && qf.rank == pf.rank {
        s += 1.0;
    }
    (
        s,
        if shared.is_empty() {
            vec!["weak structural fallback".into()]
        } else {
            shared
                .into_iter()
                .map(|m| format!("shared mathematical motif: {m}"))
                .collect()
        },
    )
}
fn generalized(value: &Value) -> Value {
    fn go(v: &Value, n: &mut BTreeMap<String, String>, b: &mut BTreeMap<String, String>) -> Value {
        if let Some(a) = v.as_array() {
            return Value::Array(a.iter().map(|x| go(x, n, b)).collect());
        }
        let Some(o) = v.as_object() else {
            return v.clone();
        };
        let op = o.get("op").and_then(Value::as_str).unwrap_or("");
        let mut local = b.clone();
        let mut r = o.clone();
        if matches!(op, "FiniteSum" | "FiniteProduct" | "InfiniteSeries") {
            if let Some(old) = o.get("bound_index").and_then(Value::as_str) {
                let new = format!("$i{}", b.len());
                local.insert(old.into(), new.clone());
                r.insert("bound_index".into(), json!(new));
            }
        }
        if matches!(op, "FreeVariable" | "BoundVariable" | "IndexedValue") {
            if let Some(old) = o.get("name").and_then(Value::as_str) {
                let new = b.get(old).cloned().unwrap_or_else(|| {
                    let x = format!("$v{}", n.len());
                    n.entry(old.into()).or_insert(x).clone()
                });
                r.insert("name".into(), json!(new));
            }
        }
        for (k, x) in o {
            if k != "name" && k != "bound_index" {
                r.insert(k.clone(), go(x, n, &mut local));
            }
        }
        Value::Object(r)
    }
    go(value, &mut BTreeMap::new(), &mut BTreeMap::new())
}
fn direct_supported(e: &Value, language: &str) -> bool {
    let (f, _) = features(e);
    let mut a: BTreeSet<&str> = [
        "Constant",
        "FreeVariable",
        "BoundVariable",
        "IndexedValue",
        "Add",
        "Subtract",
        "Multiply",
        "Divide",
        "FloorDivide",
        "Modulo",
        "Power",
        "Negate",
        "Compare",
        "IfThenElse",
        "Select",
        "Piecewise",
        "Predicate",
        "Indicator",
        "LogicalAnd",
        "LogicalOr",
        "LogicalNot",
        "Minimum",
        "Maximum",
        "Clamp",
        "BitAnd",
        "BitOr",
        "BitXor",
        "BitNot",
        "ShiftLeft",
        "ShiftRight",
        "RotateLeft",
        "RotateRight",
        "BitFieldExtract",
        "BitFieldInsert",
        "PopCount",
        "LeadingZeros",
        "TrailingZeros",
        "BitTest",
        "FunctionCall",
        "FiniteSum",
        "FiniteProduct",
        "FoldLeft",
        "TransformReduce",
        "Map",
        "Filter",
        "DiscreteDifference",
        "Quadrature",
    ]
    .into_iter()
    .collect();
    if language != "python" {
        a.remove("Quadrature");
    }
    f.ops.iter().all(|op| a.contains(op.as_str()))
}

fn factor_multiplication_equivalent(left: &Value, right: &Value) -> bool {
    fn parts(value: &Value) -> Option<(&Value, &Value, &Value)> {
        let add = value.get("args")?.as_array()?;
        if value.get("op")?.as_str()? != "Add" || add.len() != 2 {
            return None;
        }
        let a = add[0].get("args")?.as_array()?;
        let b = add[1].get("args")?.as_array()?;
        if add[0].get("op")?.as_str()? != "Multiply"
            || add[1].get("op")?.as_str()? != "Multiply"
            || a.len() != 2
            || b.len() != 2
        {
            return None;
        }
        for (common, first, second) in [(&a[0], &a[1], &b[1]), (&a[1], &a[0], &b[0])] {
            if semantic_equal(
                common,
                if std::ptr::eq(common, &a[0]) {
                    &b[0]
                } else {
                    &b[1]
                },
            ) {
                return Some((common, first, second));
            }
        }
        None
    }
    fn factored(value: &Value) -> Option<(&Value, &Value, &Value)> {
        let args = value.get("args")?.as_array()?;
        if value.get("op")?.as_str() != Some("Multiply") || args.len() != 2 {
            return None;
        }
        for (common, sum) in [(&args[0], &args[1]), (&args[1], &args[0])] {
            let terms = sum.get("args")?.as_array()?;
            if sum.get("op")?.as_str() == Some("Add") && terms.len() == 2 {
                return Some((common, &terms[0], &terms[1]));
            }
        }
        None
    }
    if let (Some((c, a, b)), Some((d, x, y))) = (parts(left), factored(right)) {
        semantic_equal(c, d)
            && ((semantic_equal(a, x) && semantic_equal(b, y))
                || (semantic_equal(a, y) && semantic_equal(b, x)))
    } else if let (Some((c, a, b)), Some((d, x, y))) = (parts(right), factored(left)) {
        semantic_equal(c, d)
            && ((semantic_equal(a, x) && semantic_equal(b, y))
                || (semantic_equal(a, y) && semantic_equal(b, x)))
    } else {
        false
    }
}

pub fn plan_generation_native(request: &Value) -> Result<Value> {
    let expression = request.get("expression").cloned().unwrap_or(Value::Null);
    let (qf, nodes) = features(&expression);
    let language = request.get("language").and_then(Value::as_str);
    let assumptions: BTreeSet<String> = request
        .get("assumptions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_string)
        .collect();
    let budget=request.get("budget").cloned().unwrap_or_else(||json!({"retrieval":100,"detailed_unification":20,"full_verification":5,"rewrite_states":30,"rewrite_depth":4,"egraph_iterations":8,"egraph_enodes":200,"egraph_rule_applications":500}));
    let retrieval = budget["retrieval"].as_u64().unwrap_or(100) as usize;
    let detailed = budget["detailed_unification"].as_u64().unwrap_or(20) as usize;
    let mut scored = vec![];
    for c in request
        .get("registry")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
    {
        if language.is_some() && c.get("language").and_then(Value::as_str) != language {
            continue;
        }
        let mut best = (-1.0, vec![], vec![], expression.clone());
        for (path, node) in &nodes {
            let s = score(node, &c);
            if s.0 > best.0 || (s.0 == best.0 && path.len() > best.2.len()) {
                best = (s.0, s.1, path.clone(), node.clone());
            }
        }
        scored.push((c, best));
    }
    scored.sort_by(|a, b| {
        b.1 .0.total_cmp(&a.1 .0).then_with(|| {
            a.0["provider_id"]
                .as_str()
                .cmp(&b.0["provider_id"].as_str())
        })
    });
    scored.truncate(retrieval);
    let mut out = vec![];
    for (index, (contract, (score, reasons, path, target))) in scored.into_iter().enumerate() {
        let mut status = "NOT_VERIFIED";
        let mut stage = "LOOSE_RETRIEVAL";
        let mut obligations: Vec<String> = vec![];
        let mut relations = vec![];
        if index < detailed {
            let lowering = contract
                .get("lowering")
                .and_then(Value::as_str)
                .unwrap_or("direct");
            let pattern = contract.get("pattern").cloned().unwrap_or(Value::Null);
            if lowering == "direct" && pattern.as_object().is_some_and(serde_json::Map::is_empty) {
                stage = "RIGOROUS_RECOMPARISON";
                status = if direct_supported(
                    &expression,
                    contract
                        .get("language")
                        .and_then(Value::as_str)
                        .unwrap_or("python"),
                ) {
                    "RIGOROUS_EXACT_MATCH"
                } else {
                    "GENERATION_LOWERING_UNSUPPORTED"
                };
                if status.ends_with("UNSUPPORTED") {
                    obligations.push("finite algorithm lowering required".into());
                }
            } else {
                stage = "TYPED_UNIFICATION";
                let u = typed_unify(&generalized(&pattern), &generalized(&target));
                if semantic_equal(&pattern, &target)
                    || matches!(u.status.as_str(), "MATCH" | "TYPED_UNIFICATION_SUCCEEDED")
                {
                    obligations.extend(u.substitution.obligations);
                    obligations.extend(
                        contract
                            .get("constraints")
                            .and_then(Value::as_array)
                            .into_iter()
                            .flatten()
                            .filter_map(Value::as_str)
                            .filter(|x| !assumptions.contains(*x))
                            .map(str::to_string),
                    );
                    let relation = contract
                        .get("implementation_relation")
                        .and_then(Value::as_str)
                        .unwrap_or("EXACT_EQUAL");
                    if relation != "EXACT_EQUAL" {
                        status = "NON_EXACT_RELATION_CANDIDATE";
                        relations.push(json!({"source_eclass_id":"requested","target_eclass_id":contract["provider_id"],"relation_kind":relation,"conditions":obligations,"evidence":"LibraryContract relation evidence","metadata":{}}));
                    } else {
                        status = if obligations.is_empty() {
                            "RIGOROUS_EXACT_MATCH"
                        } else {
                            "CONTRACT_OBLIGATIONS_REMAINING"
                        };
                    }
                } else if request
                    .get("authorized_rewrites")
                    .and_then(Value::as_array)
                    .is_some_and(|r| {
                        r.iter()
                            .any(|v| v.as_str() == Some("factor_multiplication"))
                    })
                    && factor_multiplication_equivalent(&expression, &pattern)
                {
                    stage = "EXACT_EQUALITY_SATURATION";
                    status = "MATCH_WITH_EXACT_EGRAPH";
                }
            }
        }
        out.push(json!({"contract":contract,"rank":index+1,"score":score,"reasons":reasons,"matched_path":path,"stage":stage,"verification_status":status,"remaining_obligations":obligations,"relation_edges":relations,"egraph_status":null}));
    }
    let edges: Vec<Value> = out
        .iter()
        .flat_map(|c| c["relation_edges"].as_array().cloned().unwrap_or_default())
        .collect();
    Ok(
        json!({"requested_expression":expression,"candidates":out,"budget":budget,"status":if out.is_empty(){"PROVIDER_RETRIEVAL_MISS"}else{"PROVIDER_CANDIDATES_PLANNED"},"relation_graph":{"edges":edges},"decision_provenance":[{"event":"BROAD_RETRIEVAL","candidate_count":out.len(),"motifs":qf.motifs}]}),
    )
}
