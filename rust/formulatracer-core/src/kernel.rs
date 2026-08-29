//! Unified request boundary for semantic kernels A--F.
//!
//! Bindings send versioned data and receive semantic decisions.  This module is
//! deliberately orchestration-only: each decision delegates to the native
//! component that owns the relevant invariant.

use std::collections::{BTreeMap, BTreeSet};

use serde::de::DeserializeOwned;
use serde_json::{json, Value};

use crate::coverage::coverage_blocker_operation;
use crate::labeled_data::labeled_data_operation;
use crate::provider_execution::provider_execution_operation;
use crate::{
    approximation_family_operation, approximation_proof_operation, assemble_project_verification,
    assemble_provenance, bitvector_operation, build_data_lineage, canonicalize,
    compare_dataset_schemas, compose_absolute_errors, compose_error_components, debug_project,
    evaluate_error_budget, legacy_core_operation, legacy_equality_operation,
    legacy_expression_operation, legacy_ieee754_operation, legacy_interval_operation,
    legacy_knowledge_operation, legacy_math_semantics_operation, legacy_numeric_types_operation,
    legacy_probability_operation, legacy_synthesis_operation, legacy_transformations_operation,
    localize, logic_operation, origin_set_operation, parallel_operation, plan_generation_native,
    project_audit_bundle, quotient_normalize, reconstruct, representation_operation,
    resolve_configuration, scientific_foundation_operation, select_minimal_reproducer,
    semantic_equal, semantic_hash, structural_isomorphism, substitute, to_tex, typed_unify,
    unit_operation, AlgebraicStructure, AuditBundle, CacheKey, CanonicalPolicy, CompositionRequest,
    ErrorBound, ErrorEvidence, ExactEGraph, Fact, FactEngine, FormulaTracerError,
    GraphPropagationRequest, IntegrityEnvelope, Interval, NumericDomain, ProviderPack,
    ReconstructionRequest, RelationEdge, RelationGraph, RelationKind, Result, SourceOrigin,
    StructuralFacts, VerificationResult,
};

fn required<'a>(request: &'a Value, key: &str) -> Result<&'a Value> {
    request.get(key).ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument(format!("kernel request missing {key}"))
    })
}

fn decode<T: DeserializeOwned>(value: &Value) -> Result<T> {
    Ok(serde_json::from_value(value.clone())?)
}

fn interval(request: &Value) -> Result<Value> {
    let left: Interval = decode(required(request, "left")?)?;
    let right: Interval = decode(required(request, "right")?)?;
    let result = match required(request, "operator")?.as_str() {
        Some("ADD") => Some(left.interval_add(right)),
        Some("SUBTRACT") => Some(left.interval_sub(right)),
        Some("MULTIPLY") => Some(left.interval_mul(right)),
        Some("DIVIDE") => left.interval_div(right),
        _ => {
            return Err(FormulaTracerError::InvalidSemanticDocument(
                "unknown interval operator".into(),
            ))
        }
    };
    Ok(match result {
        Some(value) => json!({"status":"ENCLOSED","interval":value}),
        None => json!({"status":"UNRESOLVED","diagnostic":"DIVISOR_CONTAINS_ZERO"}),
    })
}

fn egraph(request: &Value) -> Result<Value> {
    let values = required(request, "values")?.as_array().ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument("values must be an array".into())
    })?;
    let mut graph = ExactEGraph::default();
    let ids = values
        .iter()
        .map(|value| graph.add_value(value))
        .collect::<Result<Vec<_>>>()?;
    for merge in request
        .get("merges")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let left = merge.get("left").and_then(Value::as_u64).ok_or_else(|| {
            FormulaTracerError::InvalidSemanticDocument("merge left required".into())
        })? as usize;
        let right = merge.get("right").and_then(Value::as_u64).ok_or_else(|| {
            FormulaTracerError::InvalidSemanticDocument("merge right required".into())
        })? as usize;
        let relation: RelationKind = decode(required(merge, "relation")?)?;
        let assumptions = merge
            .get("assumptions")
            .cloned()
            .map(|value| decode(&value))
            .transpose()?
            .unwrap_or_default();
        graph.merge(
            ids[left],
            ids[right],
            relation,
            merge
                .get("rule_id")
                .and_then(Value::as_str)
                .unwrap_or("anonymous"),
            assumptions,
        )?;
    }
    let equivalents = request
        .get("queries")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .map(|query| {
            let left = query[0].as_u64().unwrap_or(u64::MAX) as usize;
            let right = query[1].as_u64().unwrap_or(u64::MAX) as usize;
            left < ids.len() && right < ids.len() && graph.equivalent(ids[left], ids[right])
        })
        .collect::<Vec<_>>();
    Ok(
        json!({"node_count":graph.node_count(),"class_count":graph.class_count(),
              "equivalents":equivalents,"trace":graph.trace}),
    )
}

fn semantic_diff(left: &Value, right: &Value) -> Value {
    let left = canonicalize(left, CanonicalPolicy::default());
    let right = canonicalize(right, CanonicalPolicy::default());
    if left == right {
        return json!({"status":"SEMANTICALLY_EQUAL","changes":[]});
    }
    let mut changes = vec![];
    fn walk(path: String, left: Option<&Value>, right: Option<&Value>, out: &mut Vec<Value>) {
        if left == right {
            return;
        }
        match (
            left.and_then(Value::as_object),
            right.and_then(Value::as_object),
        ) {
            (Some(a), Some(b)) => {
                let keys = a
                    .keys()
                    .chain(b.keys())
                    .collect::<std::collections::BTreeSet<_>>();
                for key in keys {
                    walk(format!("{path}/{key}"), a.get(key), b.get(key), out);
                }
            }
            _ => out.push(json!({"path":path,"before":left,"after":right})),
        }
    }
    walk(String::new(), Some(&left), Some(&right), &mut changes);
    json!({"status":"SEMANTIC_DIVERGENCE","changes":changes})
}

fn ignored_generalization_field(key: &str) -> bool {
    matches!(
        key,
        "source_spans"
            | "source_node_ids"
            | "source_span"
            | "operator_span"
            | "callable_span"
            | "argument_spans"
            | "keyword_spans"
            | "condition_span"
            | "shape_constraints"
            | "numeral_representation"
            | "mathematical_semantic"
            | "alignment_constraints"
            | "resolution_trace"
            | "reduction_order"
            | "lowered_from"
    )
}

fn generalize_expression(expression: &Value, declarations: &Value) -> Value {
    fn declaration(name: &str, role: &str, rank: usize, declarations: &Value) -> Value {
        declarations.get(name).cloned().unwrap_or_else(|| json!({
            "canonical_name": name, "namespace": "user", "role": role,
            "shape": if role == "tensor" { Value::Array(vec![Value::Null; rank]) } else { json!([]) },
            "named_dimensions": [], "domain": null
        }))
    }
    fn visit(
        value: &Value,
        bound: &BTreeMap<String, String>,
        names: &mut BTreeMap<String, String>,
        metavariables: &mut BTreeMap<String, Value>,
        declarations: &Value,
    ) -> Value {
        if let Some(values) = value.as_array() {
            return Value::Array(
                values
                    .iter()
                    .map(|item| visit(item, bound, names, metavariables, declarations))
                    .collect(),
            );
        }
        let Some(object) = value.as_object() else {
            return value.clone();
        };
        let op = object.get("op").and_then(Value::as_str).unwrap_or("");
        let mut local = bound.clone();
        if matches!(op, "FiniteSum" | "FiniteProduct" | "InfiniteSeries") {
            let old = object
                .get("bound_index")
                .and_then(Value::as_str)
                .unwrap_or("");
            let new = format!("$i{}", bound.len());
            local.insert(old.to_string(), new.clone());
            let mut result = serde_json::Map::new();
            for (key, item) in object {
                if key != "bound_index" && !ignored_generalization_field(key) {
                    result.insert(
                        key.clone(),
                        visit(item, &local, names, metavariables, declarations),
                    );
                }
            }
            result.insert("bound_index".into(), Value::String(new));
            return Value::Object(result);
        }
        if matches!(op, "FreeVariable" | "BoundVariable") {
            let name = object.get("name").and_then(Value::as_str).unwrap_or("");
            let renamed = bound.get(name).cloned().unwrap_or_else(|| {
                let next = names.len();
                names
                    .entry(name.to_string())
                    .or_insert_with(|| format!("$v{next}"))
                    .clone()
            });
            if !bound.contains_key(name) {
                metavariables
                    .entry(renamed.clone())
                    .or_insert_with(|| declaration(name, "scalar", 0, declarations));
            }
            let mut result = serde_json::Map::new();
            for (key, item) in object {
                if !ignored_generalization_field(key) {
                    result.insert(
                        key.clone(),
                        if key == "name" {
                            Value::String(renamed.clone())
                        } else {
                            item.clone()
                        },
                    );
                }
            }
            return Value::Object(result);
        }
        if op == "IndexedValue" {
            let name = object.get("name").and_then(Value::as_str).unwrap_or("");
            let next = names.len();
            let renamed = names
                .entry(name.to_string())
                .or_insert_with(|| format!("$v{next}"))
                .clone();
            let rank = object
                .get("indices")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            metavariables
                .entry(renamed.clone())
                .or_insert_with(|| declaration(name, "tensor", rank, declarations));
            let mut result = serde_json::Map::new();
            for (key, item) in object {
                if !ignored_generalization_field(key) {
                    let replacement = match key.as_str() {
                        "name" => Value::String(renamed.clone()),
                        "indices" => visit(item, &local, names, metavariables, declarations),
                        _ => item.clone(),
                    };
                    result.insert(key.clone(), replacement);
                }
            }
            return Value::Object(result);
        }
        Value::Object(
            object
                .iter()
                .filter(|(key, _)| !ignored_generalization_field(key))
                .map(|(key, item)| {
                    (
                        key.clone(),
                        visit(item, &local, names, metavariables, declarations),
                    )
                })
                .collect(),
        )
    }
    let mut names = BTreeMap::new();
    let mut metavariables = BTreeMap::new();
    let pattern = visit(
        expression,
        &BTreeMap::new(),
        &mut names,
        &mut metavariables,
        declarations,
    );
    json!({"pattern": pattern, "metavariables": metavariables})
}

fn anti_unify_expression(left: &Value, right: &Value) -> Value {
    fn visit(
        left: &Value,
        right: &Value,
        counter: &mut usize,
        left_sub: &mut BTreeMap<String, Value>,
        right_sub: &mut BTreeMap<String, Value>,
    ) -> Option<Value> {
        if left == right {
            return Some(left.clone());
        }
        if let (Some(a), Some(b)) = (left.as_array(), right.as_array()) {
            if a.len() != b.len() {
                return None;
            }
            return a
                .iter()
                .zip(b)
                .map(|(x, y)| visit(x, y, counter, left_sub, right_sub))
                .collect::<Option<Vec<_>>>()
                .map(Value::Array);
        }
        if let (Some(a), Some(b)) = (left.as_object(), right.as_object()) {
            if a.get("op") != b.get("op") || a.get("op").and_then(Value::as_str) == Some("Constant")
            {
                return None;
            }
            let keys = a.keys().chain(b.keys()).cloned().collect::<BTreeSet<_>>();
            let mut result = serde_json::Map::new();
            for key in keys {
                result.insert(
                    key.clone(),
                    visit(
                        a.get(&key).unwrap_or(&Value::Null),
                        b.get(&key).unwrap_or(&Value::Null),
                        counter,
                        left_sub,
                        right_sub,
                    )?,
                );
            }
            return Some(Value::Object(result));
        }
        if left.is_string() && right.is_string() {
            let key = format!("$g{}", *counter);
            *counter += 1;
            left_sub.insert(key.clone(), left.clone());
            right_sub.insert(key.clone(), right.clone());
            return Some(Value::String(key));
        }
        None
    }
    let mut left_sub = BTreeMap::new();
    let mut right_sub = BTreeMap::new();
    let mut counter = 0;
    let pattern = visit(left, right, &mut counter, &mut left_sub, &mut right_sub);
    match pattern {
        Some(pattern) => json!({"status":"ANTI_UNIFICATION_SUCCEEDED", "pattern":pattern,
            "left_substitution":left_sub, "right_substitution":right_sub}),
        None => json!({"status":"ANTI_UNIFICATION_REJECTED", "pattern":null,
            "left_substitution":left_sub, "right_substitution":right_sub}),
    }
}

/// Execute one versioned semantic-kernel request.
pub fn execute_kernel(request: &Value) -> Result<Value> {
    let version = request
        .get("schema_version")
        .and_then(Value::as_str)
        .unwrap_or("1.0");
    if version != "1.0" {
        return Err(FormulaTracerError::InvalidSemanticDocument(
            "KERNEL_SCHEMA_VERSION_UNSUPPORTED".into(),
        ));
    }
    let kernel = required(request, "kernel")?.as_str().unwrap_or("");
    let operation = required(request, "operation")?.as_str().unwrap_or("");
    let result = match (kernel, operation) {
        ("A", "SUPPORTS_STRUCTURE") => {
            let domain: NumericDomain = decode(required(request, "domain")?)?;
            let structure: AlgebraicStructure = decode(required(request, "structure")?)?;
            json!({"status":FactEngine::default().supports_structure(domain, structure)})
        }
        ("A", "BITVECTOR") => bitvector_operation(request)?,
        ("A", "LOGIC") => logic_operation(request)?,
        ("A", "UNITS") => unit_operation(request)?,
        ("A", "QUERY_FACTS") => {
            let facts: Vec<Fact> = decode(required(request, "facts")?)?;
            let mut engine = FactEngine::default();
            for fact in facts {
                engine.assert(fact);
            }
            let subject = required(request, "subject")?.as_str().unwrap_or("");
            let predicate = required(request, "predicate")?.as_str().unwrap_or("");
            json!({"status":engine.query(subject, predicate, required(request, "expected")?)})
        }
        ("A", "STRUCTURE_CLOSURE") => {
            let structures: Vec<AlgebraicStructure> = decode(required(request, "structures")?)?;
            json!({"structures":AlgebraicStructure::closure(structures)})
        }
        ("B", "CANONICALIZE") => {
            canonicalize(required(request, "expression")?, CanonicalPolicy::default())
        }
        ("B", "SEMANTIC_HASH") => {
            json!({"semantic_hash":semantic_hash(required(request, "expression")?, CanonicalPolicy::default())?})
        }
        ("B", "EQUAL") => {
            json!({"equal":semantic_equal(required(request, "left")?, required(request, "right")?)})
        }
        ("B", "RENDER_TEX") => {
            json!({"tex":to_tex(required(request, "expression")?)})
        }
        ("B", "TYPED_UNIFY") => serde_json::to_value(typed_unify(
            required(request, "pattern")?,
            required(request, "candidate")?,
        ))?,
        ("B", "GENERALIZE") => generalize_expression(
            required(request, "expression")?,
            request.get("declarations").unwrap_or(&Value::Null),
        ),
        ("B", "ANTI_UNIFY") => {
            anti_unify_expression(required(request, "left")?, required(request, "right")?)
        }
        ("B", "SUBSTITUTE") => {
            let mapping: BTreeMap<String, Value> = decode(required(request, "mapping")?)?;
            substitute(required(request, "expression")?, &mapping)
        }
        ("B", "EGRAPH") => egraph(request)?,
        ("B", "LEGACY_EQUALITY") => legacy_equality_operation(request)?,
        ("A", "LEGACY_IEEE754") => legacy_ieee754_operation(request)?,
        ("C", "LEGACY_INTERVAL") => legacy_interval_operation(request)?,
        ("C", "LEGACY_PROBABILITY") => legacy_probability_operation(request)?,
        ("B", "QUOTIENT_NORMALIZE") => {
            let facts: StructuralFacts = request
                .get("facts")
                .cloned()
                .map(|value| decode(&value))
                .transpose()?
                .unwrap_or_default();
            serde_json::to_value(quotient_normalize(required(request, "expression")?, &facts))?
        }
        ("B", "STRUCTURAL_ISOMORPHISM") => {
            let facts: StructuralFacts = request
                .get("facts")
                .cloned()
                .map(|value| decode(&value))
                .transpose()?
                .unwrap_or_default();
            serde_json::to_value(structural_isomorphism(
                required(request, "left")?,
                required(request, "right")?,
                &facts,
            ))?
        }
        ("C", "RELATION_GRAPH") => {
            let edges: Vec<RelationEdge> = decode(required(request, "edges")?)?;
            let mut graph = RelationGraph::v1();
            for edge in edges {
                graph.add(edge);
            }
            serde_json::to_value(graph)?
        }
        ("C", "APPROXIMATION_FAMILY") => approximation_family_operation(request)?,
        ("C", "APPROXIMATION_PROOF") => approximation_proof_operation(request)?,
        ("C", "PARALLEL_ANALYZE") => parallel_operation(request)?,
        ("C", "COVERAGE_BLOCKER") => coverage_blocker_operation(request)?,
        ("C", "LABELED_DATA") => labeled_data_operation(request)?,
        ("C", "PROVIDER_EXECUTION") => provider_execution_operation(request)?,
        ("C", "INTERVAL") => interval(request)?,
        ("C", "COMPOSE_ABSOLUTE_ERRORS") => {
            let parts: Vec<ErrorEvidence> = decode(required(request, "parts")?)?;
            serde_json::to_value(compose_absolute_errors(&parts))?
        }
        ("C", "COMPOSE_ERROR_COMPONENTS") => {
            let input: CompositionRequest = decode(request)?;
            serde_json::to_value(compose_error_components(input)?)?
        }
        ("C", "EVALUATE_ERROR_BUDGET") => {
            let bound: ErrorBound = decode(required(request, "known_bound")?)?;
            let tolerance = request.get("absolute_tolerance").and_then(Value::as_f64);
            evaluate_error_budget(
                &bound,
                required(request, "total_status")?.as_str().ok_or_else(|| {
                    FormulaTracerError::InvalidSemanticDocument(
                        "total_status must be a string".into(),
                    )
                })?,
                tolerance,
            )
        }
        ("C", "PROPAGATE_ERROR_GRAPH") => {
            let input: GraphPropagationRequest = decode(request)?;
            serde_json::to_value(crate::propagate_expression_graph(input)?)?
        }
        ("C", "BUILD_ERROR_ANALYSIS") => crate::build_error_analysis(request)?,
        ("F", "ASSEMBLE_PROJECT_VERIFICATION") => assemble_project_verification(request)?,
        ("F", "LEGACY_CORE") => legacy_core_operation(request)?,
        ("F", "LEGACY_EXPRESSION") => legacy_expression_operation(request)?,
        ("F", "LEGACY_NUMERIC_TYPES") => legacy_numeric_types_operation(request)?,
        ("F", "LEGACY_MATH_SEMANTICS") => legacy_math_semantics_operation(request)?,
        ("D", "LEGACY_KNOWLEDGE") => legacy_knowledge_operation(request)?,
        ("D", "LEGACY_SYNTHESIS") => legacy_synthesis_operation(request)?,
        ("F", "RECONSTRUCT") => {
            let input: ReconstructionRequest = decode(required(request, "request")?)?;
            serde_json::to_value(reconstruct(&input))?
        }
        ("B", "LEGACY_TRANSFORMATIONS") => legacy_transformations_operation(request)?,
        ("F", "PROJECT_AUDIT_BUNDLE") => project_audit_bundle(request)?,
        ("D", "PROVIDER_MATCH") => {
            let pack: ProviderPack = decode(required(request, "pack")?)?;
            serde_json::to_value(pack.match_expression(required(request, "expression")?))?
        }
        ("D", "SCIENTIFIC_FOUNDATIONS") => scientific_foundation_operation(request)?,
        ("D", "REPRESENTATION") => representation_operation(request)?,
        ("D", "PLAN_GENERATION") => plan_generation_native(request)?,
        ("E", "CACHE_VERIFY") => {
            let key: CacheKey = decode(required(request, "key")?)?;
            let envelope: IntegrityEnvelope = decode(required(request, "envelope")?)?;
            json!({"valid":envelope.verify(&key)?})
        }
        ("E", "LOCALIZE") => {
            let origins: Vec<SourceOrigin> = decode(required(request, "origins")?)?;
            let path = request
                .get("semantic_path")
                .cloned()
                .map(|value| decode(&value))
                .transpose()?
                .unwrap_or_default();
            serde_json::to_value(localize(&origins, path))?
        }
        ("E", "SEMANTIC_DIFF") => {
            semantic_diff(required(request, "left")?, required(request, "right")?)
        }
        ("E", "ORIGIN_SET") => origin_set_operation(request),
        ("E", "RESOLVE_CONFIGURATION") => resolve_configuration(request),
        ("E", "COMPARE_DATASET_SCHEMAS") => compare_dataset_schemas(request),
        ("E", "BUILD_DATA_LINEAGE") => build_data_lineage(request),
        ("E", "ASSEMBLE_PROVENANCE") => assemble_provenance(request),
        ("E", "DEBUG_PROJECT") => debug_project(request),
        ("E", "SELECT_MINIMAL_REPRODUCER") => select_minimal_reproducer(request),
        ("F", "AUDIT_BUNDLE") => {
            let result: VerificationResult = decode(required(request, "result")?)?;
            serde_json::to_value(AuditBundle::new_with_structural(
                result,
                request
                    .get("source_context")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
                request
                    .get("environment")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
                request
                    .get("artifact_lineage")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
                request
                    .get("data_schema")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
                request
                    .get("provider_decisions")
                    .cloned()
                    .unwrap_or_else(|| json!([])),
                request
                    .get("generation_decisions")
                    .cloned()
                    .unwrap_or_else(|| json!([])),
                request
                    .get("structural_normalization")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
                request
                    .get("structural_isomorphism")
                    .cloned()
                    .unwrap_or_else(|| json!({})),
                request
                    .get("ignored_representation_differences")
                    .cloned()
                    .unwrap_or_else(|| json!([])),
            )?)?
        }
        _ => {
            return Err(FormulaTracerError::NativeComponentIncomplete(
                "semantic kernel operation",
            ))
        }
    };
    Ok(json!({"schema_version":"1.0","kernel":kernel,"operation":operation,"result":result}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kernels_a_through_f_share_one_fail_closed_dispatch() {
        let natural_ring = execute_kernel(&json!({"kernel":"A","operation":"SUPPORTS_STRUCTURE",
            "domain":"NATURAL","structure":"RING"}))
        .unwrap();
        assert_eq!(natural_ring["result"]["status"], "PROVEN_FALSE");
        let equality = execute_kernel(&json!({"kernel":"B","operation":"EQUAL",
            "left":{"op":"Add","args":[{"op":"FreeVariable","name":"x"},{"op":"Constant","value":1}]},
            "right":{"op":"Add","args":[{"op":"Constant","value":1},{"op":"FreeVariable","name":"y"}]}})).unwrap();
        assert_eq!(equality["result"]["equal"], true);
        let enclosure = execute_kernel(
            &json!({"kernel":"C","operation":"INTERVAL","operator":"DIVIDE",
            "left":{"lower":1.0,"upper":2.0},"right":{"lower":-1.0,"upper":1.0}}),
        )
        .unwrap();
        assert_eq!(enclosure["result"]["status"], "UNRESOLVED");
        assert!(execute_kernel(&json!({"kernel":"Z","operation":"UNKNOWN"})).is_err());
    }
}
