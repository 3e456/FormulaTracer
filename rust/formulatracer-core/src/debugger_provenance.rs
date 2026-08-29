//! Canonical provenance, lineage, and fail-closed semantic debugger semantics.
//!
//! Frontends may observe source/environment facts, but union, lineage,
//! localization, causal classification, and reproducer selection are owned here.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

fn digest(value: &Value) -> String {
    let bytes = serde_json::to_vec(value).unwrap_or_default();
    format!("{:x}", Sha256::digest(bytes))
}

fn stable_id(prefix: &str, value: &Value) -> String {
    format!("{prefix}:{}", &digest(value)[..16])
}

fn semantic_clean(value: &Value) -> Value {
    const NOISE: &[&str] = &[
        "source_node_ids",
        "source_spans",
        "source_span",
        "provenance",
        "reference_contract",
        "normalization",
        "original_index",
        "api",
        "canonical_name",
        "local_name",
        "expression_id",
        "operator_span",
        "callable_span",
        "argument_spans",
        "keyword_spans",
        "condition_span",
        "branch_spans",
        "shape_constraints",
        "alignment_constraints",
    ];
    match value {
        Value::Array(items) => Value::Array(items.iter().map(semantic_clean).collect()),
        Value::Object(object) => Value::Object(
            object
                .iter()
                .filter(|(key, _)| !NOISE.contains(&key.as_str()))
                .map(|(key, item)| (key.clone(), semantic_clean(item)))
                .collect(),
        ),
        _ => value.clone(),
    }
}

fn semantic_signature(value: &Value) -> String {
    serde_json::to_string(&semantic_clean(value)).unwrap_or_default()
}

fn complete_span(value: &Value) -> bool {
    value.get("file").and_then(Value::as_str).is_some()
        && value.get("begin_line").and_then(Value::as_u64).is_some()
        && value.get("end_line").and_then(Value::as_u64).is_some()
        && (value.get("begin_column").and_then(Value::as_u64).is_some()
            || value.get("begin_col").and_then(Value::as_u64).is_some())
        && (value.get("end_column").and_then(Value::as_u64).is_some()
            || value.get("end_col").and_then(Value::as_u64).is_some())
}

fn unique_values(values: impl IntoIterator<Item = Value>) -> Vec<Value> {
    let mut seen = BTreeSet::new();
    let mut result = vec![];
    for value in values {
        let key = serde_json::to_string(&value).unwrap_or_default();
        if seen.insert(key) {
            result.push(value);
        }
    }
    result
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct OriginSet {
    #[serde(default)]
    pub origins: Vec<Value>,
    #[serde(default = "partial_status")]
    pub status: String,
}

fn partial_status() -> String {
    "PARTIAL".into()
}

impl OriginSet {
    pub fn normalized(origins: Vec<Value>) -> Self {
        let origins = unique_values(origins);
        let status = if origins.is_empty() {
            "UNRESOLVED"
        } else {
            "COMPLETE"
        };
        Self {
            origins,
            status: status.into(),
        }
    }
    pub fn union(&self, other: &Self) -> Self {
        Self::normalized(self.origins.iter().chain(&other.origins).cloned().collect())
    }
    pub fn intersection(&self, other: &Self) -> Self {
        let right = other
            .origins
            .iter()
            .map(|v| serde_json::to_string(v).unwrap_or_default())
            .collect::<BTreeSet<_>>();
        Self::normalized(
            self.origins
                .iter()
                .filter(|v| right.contains(&serde_json::to_string(v).unwrap_or_default()))
                .cloned()
                .collect(),
        )
    }
    pub fn project_file(&self, path: &str) -> Self {
        Self::normalized(
            self.origins
                .iter()
                .filter(|v| v.get("file").and_then(Value::as_str) == Some(path))
                .cloned()
                .collect(),
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeProvenanceNode {
    pub node_id: String,
    pub kind: String,
    pub label: String,
    #[serde(default)]
    pub metadata: Value,
    pub content_hash: Option<String>,
    pub evidence_level: String,
    pub proof_authority: bool,
    #[serde(default)]
    pub origin_set: Vec<Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeProvenanceEdge {
    pub edge_id: String,
    pub kind: String,
    pub source: String,
    pub target: String,
    #[serde(default)]
    pub metadata: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeProvenanceGraph {
    pub schema_version: String,
    pub nodes: Vec<NativeProvenanceNode>,
    pub edges: Vec<NativeProvenanceEdge>,
    pub diagnostics: Vec<Value>,
    pub graph_hash: String,
}

// A provenance node deliberately carries all evidence and origin fields at one
// call site; grouping them would only move, rather than reduce, this boundary.
#[allow(clippy::too_many_arguments)]
fn add_node(
    nodes: &mut Vec<NativeProvenanceNode>,
    kind: &str,
    label: &str,
    metadata: Value,
    content_hash: Option<String>,
    evidence: &str,
    proof_authority: bool,
    origins: Vec<Value>,
) -> String {
    let id = stable_id("provenance", &json!([kind, label, content_hash, metadata]));
    if !nodes.iter().any(|item| item.node_id == id) {
        nodes.push(NativeProvenanceNode {
            node_id: id.clone(),
            kind: kind.into(),
            label: label.into(),
            metadata,
            content_hash,
            evidence_level: evidence.into(),
            proof_authority,
            origin_set: unique_values(origins),
        });
    }
    id
}

fn add_edge(
    edges: &mut Vec<NativeProvenanceEdge>,
    kind: &str,
    source: &str,
    target: &str,
    metadata: Value,
) {
    let id = stable_id("provenance-edge", &json!([kind, source, target, metadata]));
    if !edges.iter().any(|item| item.edge_id == id) {
        edges.push(NativeProvenanceEdge {
            edge_id: id,
            kind: kind.into(),
            source: source.into(),
            target: target.into(),
            metadata,
        });
    }
}

fn origins_from(value: &Value) -> Vec<Value> {
    let mut values = vec![];
    fn visit(value: &Value, out: &mut Vec<Value>) {
        match value {
            Value::Object(object) => {
                if let Some(span) = object.get("source_span").filter(|v| v.is_object()) {
                    out.push(span.clone());
                }
                if let Some(spans) = object.get("source_spans").and_then(Value::as_array) {
                    out.extend(spans.iter().filter(|v| v.is_object()).cloned());
                }
                for item in object.values() {
                    visit(item, out);
                }
            }
            Value::Array(items) => {
                for item in items {
                    visit(item, out);
                }
            }
            _ => {}
        }
    }
    visit(value, &mut values);
    unique_values(values)
}

fn collect_semantic_evidence(value: &Value, out: &mut Vec<Value>) {
    match value {
        Value::Object(object) => {
            if object.contains_key("provider_id")
                || object.contains_key("rule_id")
                || object.contains_key("reference_contract")
                || object.contains_key("relation_kind")
                || object.contains_key("proof_obligations")
            {
                out.push(value.clone());
            }
            for item in object.values() {
                collect_semantic_evidence(item, out);
            }
        }
        Value::Array(items) => {
            for item in items {
                collect_semantic_evidence(item, out);
            }
        }
        _ => {}
    }
}

pub fn origin_set_operation(request: &Value) -> Value {
    let left = OriginSet::normalized(
        request
            .get("left")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
    );
    let right = OriginSet::normalized(
        request
            .get("right")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
    );
    let result = match request
        .get("set_operation")
        .and_then(Value::as_str)
        .unwrap_or("UNION")
    {
        "UNION" => left.union(&right),
        "INTERSECTION" => left.intersection(&right),
        "PROJECTION" => {
            left.project_file(request.get("path").and_then(Value::as_str).unwrap_or(""))
        }
        _ => OriginSet {
            origins: vec![],
            status: "UNRESOLVED".into(),
        },
    };
    serde_json::to_value(result).unwrap_or_else(|_| json!({"origins":[],"status":"UNRESOLVED"}))
}

pub fn resolve_configuration(request: &Value) -> Value {
    let precedence = BTreeMap::from([
        ("DEFAULT_ARGUMENT", 0),
        ("MODULE_CONSTANT", 5),
        ("CONFIG_FILE", 10),
        ("ENVIRONMENT_VARIABLE", 20),
        ("CLI_ARGUMENT", 30),
        ("USER_OVERRIDE", 40),
        ("DERIVED_PARAMETER", 50),
    ]);
    let mut grouped: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for item in request
        .get("parameters")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        grouped
            .entry(
                item.get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .into(),
            )
            .or_default()
            .push(item.clone());
    }
    let mut result = vec![];
    for (name, mut values) in grouped {
        values.sort_by_key(|v| {
            precedence
                .get(v.get("source").and_then(Value::as_str).unwrap_or(""))
                .copied()
                .unwrap_or(-1)
        });
        let winner = values.last().cloned().unwrap_or(Value::Null);
        let winner_source = winner
            .get("source")
            .and_then(Value::as_str)
            .unwrap_or("UNRESOLVED");
        let public = |v: &Value| {
            if v.get("sensitive").and_then(Value::as_bool) == Some(true) {
                json!("<redacted>")
            } else {
                v.get("value").cloned().unwrap_or(Value::Null)
            }
        };
        let steps = values.iter().map(|v| json!({
            "source":v.get("source"), "value":public(v), "selected":v == &winner,
            "reason":if v == &winner {"HIGHEST_PRECEDENCE_LAST_OVERRIDE".into()} else {format!("OVERRIDDEN_BY:{winner_source}")},
            "source_location":v.get("source_location").cloned().unwrap_or(Value::Null)
        })).collect::<Vec<_>>();
        result.push(
            json!({"name":name,"resolved_value":public(&winner),"resolved_source":winner_source,
            "steps":steps,"status":"PARAMETER_RESOLVED"}),
        );
    }
    Value::Array(result)
}

pub fn compare_dataset_schemas(request: &Value) -> Value {
    let before = request.get("before").unwrap_or(&Value::Null);
    let after = request.get("after").unwrap_or(&Value::Null);
    let fields = |v: &Value| {
        v.get("fields")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|f| {
                f.get("name")
                    .and_then(Value::as_str)
                    .map(|n| (n.to_string(), f.clone()))
            })
            .collect::<BTreeMap<_, _>>()
    };
    let left = fields(before);
    let right = fields(after);
    let mut changes = vec![];
    for name in left.keys().filter(|n| !right.contains_key(*n)) {
        changes.push(json!({"kind":"FIELD_MISSING","field":name}));
    }
    for name in right.keys().filter(|n| !left.contains_key(*n)) {
        changes.push(json!({"kind":"FIELD_ADDED","field":name}));
    }
    for name in left.keys().filter(|n| right.contains_key(*n)) {
        let a = &left[name];
        let b = &right[name];
        let ad = a
            .get("dimensions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let bd = b
            .get("dimensions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let aset = ad.iter().map(|v| v.to_string()).collect::<BTreeSet<_>>();
        let bset = bd.iter().map(|v| v.to_string()).collect::<BTreeSet<_>>();
        if aset != bset {
            changes.push(json!({"kind":"DIMENSION_CHANGED","field":name,"before":ad,"after":bd}));
        } else if ad != bd {
            changes.push(
                json!({"kind":"DIMENSION_ORDER_CHANGED","field":name,"before":ad,"after":bd}),
            );
        }
        for (field, kind) in [
            ("dtype", "DTYPE_CHANGED"),
            ("shape", "SHAPE_CHANGED"),
            ("unit", "UNIT_CHANGED"),
            ("missing_value_semantics", "MISSING_VALUE_SEMANTICS_CHANGED"),
            ("encoding", "SERIALIZATION_ENCODING_CHANGED"),
        ] {
            if a.get(field) != b.get(field) {
                changes.push(
                    json!({"kind":kind,"field":name,"before":a.get(field),"after":b.get(field)}),
                );
            }
        }
    }
    if before.get("encoding") != after.get("encoding") {
        changes.push(json!({"kind":"SERIALIZATION_ENCODING_CHANGED","field":null,"before":before.get("encoding"),"after":after.get("encoding")}));
    }
    Value::Array(changes)
}

pub fn build_data_lineage(request: &Value) -> Value {
    let project = request.get("project").unwrap_or(&Value::Null);
    let inputs = request
        .get("input_artifacts")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let input_ids = inputs
        .iter()
        .filter_map(|v| {
            v.get("artifact_id")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .collect::<Vec<_>>();
    let mut transformations = vec![];
    let mut dependencies = vec![];
    let mut edges = vec![];
    for output in project
        .get("outputs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let output_id = output
            .get("output_id")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let output_ref = format!("output:{output_id}");
        let sources = if input_ids.is_empty() {
            output
                .get("dependencies")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .map(|v| format!("symbol:{}", v.as_str().unwrap_or("unknown")))
                .collect::<Vec<_>>()
        } else {
            input_ids.clone()
        };
        let name = output
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("output");
        let mapping = BTreeMap::from([(
            name.to_string(),
            Value::Array(
                output
                    .get("dependencies")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default(),
            ),
        )]);
        transformations.push(json!({"transformation_id":stable_id("lineage",&json!([sources,output_ref,output.get("formula")])),
            "kind":"NUMERIC_TRANSFORMATION","inputs":sources,"outputs":[output_ref],"field_mapping":mapping,
            "source_spans":unique_values(output.get("source_locations").and_then(Value::as_array).cloned().unwrap_or_default().into_iter().chain(origins_from(output)))}));
        for source in &sources {
            edges.push(json!({"source":source,"target":format!("{output_ref}::{name}"),"kind":"FIELD_DERIVED_FROM"}));
        }
        for artifact in project
            .get("artifacts")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let matches = artifact.get("payload_symbol").and_then(Value::as_str) == Some(name)
                || artifact.get("dataset_variable").and_then(Value::as_str) == Some(name);
            if matches {
                let sink = artifact
                    .get("sink_id")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                let target = format!("artifact:{sink}");
                dependencies.push(json!({"source":output_ref,"target":target,"kind":"ARTIFACT_DEPENDENCY","serialization_status":artifact.pointer("/serialization_boundary/status")}));
                edges.push(json!({"source":format!("{output_ref}::{name}"),"target":format!("{target}::{name}"),"kind":"FIELD_SERIALIZED_TO"}));
            }
        }
    }
    json!({"transformations":transformations,"artifact_dependencies":dependencies,"field_edges":edges})
}

pub fn assemble_provenance(request: &Value) -> Value {
    let project = request.get("project").unwrap_or(&Value::Null);
    let mut nodes = vec![];
    let mut edges = vec![];
    let mut source_nodes = vec![];
    for module in project
        .get("modules")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let label = module
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("source");
        source_nodes.push(add_node(
            &mut nodes,
            "SOURCE_CODE",
            label,
            json!({"path":module.get("path"),"language":module.get("language")}),
            module
                .get("source_hash")
                .and_then(Value::as_str)
                .map(str::to_string),
            "SOURCE_HASH",
            false,
            vec![],
        ));
    }
    let env = add_node(
        &mut nodes,
        "ENVIRONMENT",
        "environment",
        request
            .get("environment")
            .cloned()
            .unwrap_or_else(|| json!({})),
        None,
        "ENVIRONMENT_OBSERVATION_NOT_PROOF",
        false,
        vec![],
    );
    let config = add_node(
        &mut nodes,
        "CONFIGURATION",
        "resolved configuration",
        json!({"parameter_count":request.get("configuration_resolution").and_then(Value::as_array).map_or(0,Vec::len)}),
        None,
        "OBSERVATION",
        false,
        vec![],
    );
    for trace in request
        .get("configuration_resolution")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let label = trace
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("parameter");
        let node = add_node(
            &mut nodes,
            "PARAMETER",
            label,
            trace.clone(),
            Some(digest(trace)),
            "OBSERVATION",
            false,
            vec![],
        );
        add_edge(&mut edges, "DERIVED_FROM", &node, &config, json!({}));
        for source in &source_nodes {
            add_edge(&mut edges, "CONFIGURES", &node, source, json!({}));
        }
    }
    let mut input_nodes = vec![];
    for input in request
        .get("input_artifacts")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let label = input
            .get("location")
            .and_then(Value::as_str)
            .unwrap_or("input");
        let node = add_node(
            &mut nodes,
            "INPUT_ARTIFACT",
            label,
            input.clone(),
            input
                .get("content_hash")
                .and_then(Value::as_str)
                .map(str::to_string),
            "INPUT_METADATA",
            false,
            vec![],
        );
        input_nodes.push(node.clone());
        for field in input
            .pointer("/schema/fields")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let field_label = format!(
                "{label}::{}",
                field.get("name").and_then(Value::as_str).unwrap_or("field")
            );
            let f = add_node(
                &mut nodes,
                "INPUT_FIELD",
                &field_label,
                field.clone(),
                Some(digest(field)),
                "SCHEMA_OBSERVATION",
                false,
                vec![],
            );
            add_edge(&mut edges, "DERIVED_FROM", &f, &node, json!({}));
        }
    }
    let mut dependency_nodes = vec![];
    for dep in request
        .get("dependencies")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let label = dep
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("dependency");
        dependency_nodes.push(add_node(
            &mut nodes,
            "LIBRARY_DEPENDENCY",
            label,
            dep.clone(),
            Some(digest(dep)),
            "REFERENCE_CONTRACT",
            false,
            vec![],
        ));
    }
    for output in project
        .get("outputs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let oid = output
            .get("output_id")
            .and_then(Value::as_str)
            .unwrap_or("output");
        let name = output
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("output");
        let origins = unique_values(
            output
                .get("source_locations")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .chain(origins_from(output)),
        );
        let implementation = add_node(
            &mut nodes,
            "IMPLEMENTATION_IR",
            &format!("{oid}:implementation"),
            json!({"output":name}),
            Some(digest(output.get("implementation").unwrap_or(&Value::Null))),
            "INDEPENDENT_EXTRACTION",
            false,
            origins.clone(),
        );
        let mathematical = add_node(
            &mut nodes,
            "MATHEMATICAL_IR",
            &format!("{oid}:mathematics"),
            json!({"output":name}),
            Some(digest(output.get("formula").unwrap_or(&Value::Null))),
            "INDEPENDENT_EXTRACTION",
            false,
            origins.clone(),
        );
        add_edge(
            &mut edges,
            "DERIVED_FROM",
            &mathematical,
            &implementation,
            json!({}),
        );
        let algorithm = add_node(
            &mut nodes,
            "ALGORITHM_IR",
            &format!("{oid}:algorithm"),
            json!({"operator":output.pointer("/formula/op")}),
            Some(digest(&json!([
                output.pointer("/formula/op"),
                output.get("dependencies")
            ]))),
            "SEMANTIC_CLASSIFICATION",
            false,
            origins.clone(),
        );
        add_edge(
            &mut edges,
            "DERIVED_FROM",
            &algorithm,
            &implementation,
            json!({}),
        );
        for source in &source_nodes {
            add_edge(
                &mut edges,
                "DERIVED_FROM",
                &implementation,
                source,
                json!({}),
            );
        }
        for input in &input_nodes {
            add_edge(&mut edges, "READS", &implementation, input, json!({}));
        }
        for dep in &dependency_nodes {
            add_edge(&mut edges, "DEPENDS_ON", &implementation, dep, json!({}));
        }
        for proof in project
            .get("proofs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|proof| proof.get("output_id").and_then(Value::as_str) == Some(oid))
        {
            let evidence = proof
                .get("lean_status")
                .and_then(Value::as_str)
                .unwrap_or("UNRESOLVED");
            let claim = add_node(
                &mut nodes,
                "VERIFICATION_CLAIM",
                &format!("{oid}:claim"),
                proof.clone(),
                Some(digest(proof)),
                evidence,
                evidence == "LEAN_KERNEL_VERIFIED",
                origins.clone(),
            );
            add_edge(&mut edges, "VERIFIES", &claim, &mathematical, json!({}));
        }
        if let Some(trace) = output.pointer("/residual/transformation_trace") {
            if !trace.is_null() {
                let trans = add_node(
                    &mut nodes,
                    "TRANSFORMATION",
                    &format!("{oid}:transformation"),
                    json!({"trace":trace}),
                    Some(digest(trace)),
                    "REWRITE_TRACE",
                    false,
                    origins.clone(),
                );
                add_edge(&mut edges, "TRANSFORMS", &implementation, &trans, json!({}));
                add_edge(&mut edges, "DERIVED_FROM", &mathematical, &trans, json!({}));
            }
        }
        if let Some(components) = output.get("error_components").and_then(Value::as_array) {
            for component in components {
                let e = add_node(
                    &mut nodes,
                    "ERROR_PROVENANCE",
                    &format!(
                        "{oid}:error:{}",
                        component
                            .get("component_id")
                            .and_then(Value::as_str)
                            .unwrap_or("component")
                    ),
                    component.clone(),
                    Some(digest(component)),
                    component
                        .get("proof_status")
                        .and_then(Value::as_str)
                        .unwrap_or("UNRESOLVED"),
                    false,
                    origins.clone(),
                );
                add_edge(
                    &mut edges,
                    "DERIVED_FROM",
                    &e,
                    &mathematical,
                    json!({"semantic_cause_id":component.get("semantic_cause_id")}),
                );
            }
        }
        let mut semantic_evidence = vec![];
        collect_semantic_evidence(output, &mut semantic_evidence);
        for item in unique_values(semantic_evidence) {
            if item.get("provider_id").is_some() || item.get("reference_contract").is_some() {
                let provider_id = item
                    .get("provider_id")
                    .and_then(Value::as_str)
                    .or_else(|| {
                        item.pointer("/reference_contract/callable")
                            .and_then(Value::as_str)
                    })
                    .unwrap_or("provider:unresolved");
                let provider = add_node(
                    &mut nodes,
                    "PROVIDER_PROVENANCE",
                    provider_id,
                    item.clone(),
                    Some(digest(&item)),
                    "REFERENCE_CONTRACT",
                    false,
                    origins.clone(),
                );
                add_edge(
                    &mut edges,
                    "SELECTS_PROVIDER",
                    &implementation,
                    &provider,
                    json!({"retrieval_rank_is_not_proof":true,"adoption_reason":item.get("status")}),
                );
            }
            if let Some(rule_id) = item.get("rule_id").and_then(Value::as_str) {
                let rule = add_node(
                    &mut nodes,
                    "TRANSFORMATION_PROVENANCE",
                    rule_id,
                    item.clone(),
                    Some(digest(&item)),
                    "REWRITE_TRACE",
                    false,
                    origins.clone(),
                );
                add_edge(
                    &mut edges,
                    "TRANSFORMS",
                    &implementation,
                    &rule,
                    json!({"required_assumptions":item.get("assumptions")}),
                );
            }
            if let Some(relation) = item.get("relation_kind").and_then(Value::as_str) {
                let relation_node = add_node(
                    &mut nodes,
                    "RELATION_PROVENANCE",
                    relation,
                    item.clone(),
                    Some(digest(&item)),
                    "RELATION_GRAPH_EVIDENCE",
                    false,
                    origins.clone(),
                );
                add_edge(
                    &mut edges,
                    "DERIVED_FROM",
                    &relation_node,
                    &mathematical,
                    json!({"exact_equality":relation == "EXACT_EQUALITY"}),
                );
            }
            if let Some(obligations) = item.get("proof_obligations").and_then(Value::as_array) {
                for obligation in obligations {
                    let obligation_id = obligation
                        .get("obligation_id")
                        .and_then(Value::as_str)
                        .or_else(|| obligation.get("kind").and_then(Value::as_str))
                        .unwrap_or("obligation:unresolved");
                    let node = add_node(
                        &mut nodes,
                        "PROOF_OBLIGATION_PROVENANCE",
                        obligation_id,
                        obligation.clone(),
                        Some(digest(obligation)),
                        obligation
                            .get("status")
                            .and_then(Value::as_str)
                            .unwrap_or("UNRESOLVED"),
                        false,
                        origins.clone(),
                    );
                    add_edge(
                        &mut edges,
                        "DERIVED_FROM",
                        &node,
                        &mathematical,
                        json!({"originating_semantic_operation":item.get("op")}),
                    );
                }
            }
        }
        for artifact in project
            .get("artifacts")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if artifact.get("payload_symbol").and_then(Value::as_str) == Some(name)
                || artifact.get("dataset_variable").and_then(Value::as_str) == Some(name)
            {
                let label = artifact
                    .get("sink_id")
                    .and_then(Value::as_str)
                    .unwrap_or("artifact");
                let target = add_node(
                    &mut nodes,
                    "OUTPUT_ARTIFACT",
                    label,
                    artifact.clone(),
                    None,
                    "SERIALIZATION_EVIDENCE",
                    false,
                    origins.clone(),
                );
                add_edge(
                    &mut edges,
                    "SERIALIZES",
                    &mathematical,
                    &target,
                    json!({"mathematical_correctness_separate":true}),
                );
            }
        }
    }
    let known = nodes
        .iter()
        .map(|n| n.node_id.clone())
        .collect::<BTreeSet<_>>();
    let diagnostics = edges
        .iter()
        .filter(|e| !known.contains(&e.source) || !known.contains(&e.target))
        .map(|e| json!({"code":format!("DANGLING_PROVENANCE_EDGE:{}",e.edge_id)}))
        .collect::<Vec<_>>();
    let body =
        json!({"schema_version":"1.0","nodes":nodes,"edges":edges,"diagnostics":diagnostics});
    let graph_hash = digest(&body);
    json!({"graph":{ "schema_version":"1.0","nodes":body["nodes"],"edges":body["edges"],"diagnostics":body["diagnostics"],"graph_hash":graph_hash },"data_lineage":build_data_lineage(request),"environment_node":env})
}

fn divergence_kind(expected: &Value, actual: &Value, role: Option<&str>) -> (&'static str, bool) {
    let left = expected.get("op").and_then(Value::as_str);
    let right = actual.get("op").and_then(Value::as_str);
    if left != right {
        if [left, right].iter().flatten().any(|op| {
            matches!(
                *op,
                "Reduce" | "FiniteSum" | "FiniteProduct" | "FoldLeft" | "TransformReduce"
            )
        }) {
            return ("REDUCTION_MISMATCH", true);
        }
        if [left, right].iter().flatten().any(|op| {
            matches!(
                *op,
                "Derivative" | "DiscreteDifference" | "Quadrature" | "Interpolation"
            )
        }) {
            return ("APPROXIMATION_FAMILY_MISMATCH", true);
        }
        if left == Some("Cast") || right == Some("Cast") {
            return ("CAST_MISMATCH", false);
        }
        return ("OPERATOR_MISMATCH", true);
    }
    if left == Some("Constant") {
        return ("CONSTANT_MISMATCH", true);
    }
    if matches!(
        left,
        Some("FreeVariable" | "BoundVariable" | "IndexedValue")
    ) {
        return ("VARIABLE_MAPPING_MISMATCH", true);
    }
    if role == Some("condition") {
        return ("BRANCH_CONDITION_MISMATCH", true);
    }
    ("UNKNOWN_SEMANTIC_DIVERGENCE", true)
}

fn first_difference(
    expected: &Value,
    actual: &Value,
    path: Vec<Value>,
    role: Option<&str>,
) -> Option<Value> {
    if expected == actual {
        return None;
    }
    if let (Some(a), Some(b)) = (expected.as_object(), actual.as_object()) {
        if a.get("op") != b.get("op") {
            let (k, m) = divergence_kind(expected, actual, role);
            return Some(
                json!({"type":k,"expected":expected,"actual":actual,"path":path,"role":role,"mathematical":m,"boundary_inputs":[]}),
            );
        }
        let op = a.get("op").and_then(Value::as_str);
        for (field, kind, mathematical) in [
            ("value", "CONSTANT_MISMATCH", true),
            ("axes", "AXIS_MISMATCH", true),
            ("axis", "AXIS_MISMATCH", true),
            ("dimensions", "DIMENSION_MISMATCH", true),
            ("dimension", "DIMENSION_MISMATCH", true),
            ("shape", "SHAPE_MISMATCH", true),
            ("dtype", "DTYPE_MISMATCH", false),
            ("family_id", "APPROXIMATION_FAMILY_MISMATCH", true),
            ("method", "APPROXIMATION_FAMILY_MISMATCH", true),
        ] {
            if (field != "value" || op == Some("Constant"))
                && a.get(field) != b.get(field)
                && (a.contains_key(field) || b.contains_key(field))
            {
                let mut p = path.clone();
                p.push(json!(field));
                let mut expected_fragment = json!({"op":op,field:a.get(field)});
                let mut actual_fragment = json!({"op":op,field:b.get(field)});
                if let Some(span) = expected.get("source_span") {
                    expected_fragment["source_span"] = span.clone();
                }
                if let Some(span) = actual.get("source_span") {
                    actual_fragment["source_span"] = span.clone();
                }
                return Some(
                    json!({"type":kind,"expected":expected_fragment,"actual":actual_fragment,
                    "path":p,"role":role,"mathematical":mathematical,"boundary_inputs":[]}),
                );
            }
        }
        let child_keys = [
            "args",
            "input",
            "body",
            "condition",
            "then",
            "else",
            "indices",
            "base",
            "expression",
            "index_domain",
            "lower",
            "upper",
            "upper_exclusive",
            "step",
        ];
        for key in child_keys {
            match (a.get(key), b.get(key)) {
                (Some(Value::Array(x)), Some(Value::Array(y))) => {
                    if x.len() != y.len() {
                        let mut p = path.clone();
                        p.push(json!(key));
                        return Some(
                            json!({"type":if key=="indices"{"INDEX_MISMATCH"}else{"UNKNOWN_SEMANTIC_DIVERGENCE"},"expected":x,"actual":y,"path":p,"role":key,"mathematical":true,"boundary_inputs":[]}),
                        );
                    }
                    for (i, (l, r)) in x.iter().zip(y).enumerate() {
                        let mut p = path.clone();
                        p.push(json!(key));
                        p.push(json!(i));
                        let adjusted = if key == "args" && !r.get("source_span").is_some() {
                            if let Some(span) = actual
                                .get("argument_spans")
                                .and_then(Value::as_array)
                                .and_then(|s| s.get(i))
                            {
                                let mut obj = r.as_object().cloned().unwrap_or_default();
                                obj.insert("source_span".into(), span.clone());
                                Value::Object(obj)
                            } else {
                                r.clone()
                            }
                        } else {
                            r.clone()
                        };
                        if let Some(d) = first_difference(l, &adjusted, p, Some(key)) {
                            return Some(d);
                        }
                    }
                }
                (Some(l), Some(r)) => {
                    let mut p = path.clone();
                    p.push(json!(key));
                    if let Some(d) = first_difference(l, r, p, Some(key)) {
                        return Some(d);
                    }
                }
                (None, None) => {}
                (l, r) => {
                    let mut p = path.clone();
                    p.push(json!(key));
                    return Some(
                        json!({"type":"UNKNOWN_SEMANTIC_DIVERGENCE","expected":l,"actual":r,"path":p,"role":key,"mathematical":true,"boundary_inputs":[]}),
                    );
                }
            }
        }
        return None;
    }
    let (k, m) = divergence_kind(expected, actual, role);
    Some(
        json!({"type":k,"expected":expected,"actual":actual,"path":path,"role":role,"mathematical":m,"boundary_inputs":[]}),
    )
}

fn output_root(project: &Value, output_id: &str) -> String {
    for root in project
        .get("roots")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if root
            .get("outputs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .any(|o| o.get("output_id").and_then(Value::as_str) == Some(output_id))
        {
            return root
                .get("root_id")
                .and_then(Value::as_str)
                .unwrap_or("root:unknown")
                .into();
        }
    }
    "root:unknown".into()
}

fn candidate_spans(project: &Value, output: &Value, kind: &str, actual: &Value) -> Vec<Value> {
    let mut spans = vec![];
    if kind == "OPERATOR_MISMATCH" {
        if let Some(v) = actual.get("operator_span").filter(|v| v.is_object()) {
            spans.push(v.clone());
        }
    }
    if spans.is_empty() {
        spans.extend(origins_from(actual));
    }
    if kind == "CONSTANT_MISMATCH" {
        let before = spans.len();
        let deps = output
            .get("dependencies")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for symbol in project
            .pointer("/project_graph/symbols")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if symbol.get("kind").and_then(Value::as_str) == Some("CONSTANT")
                && deps.contains(symbol.get("canonical_name").unwrap_or(&Value::Null))
            {
                if let Some(span) = symbol.get("source_span").filter(|v| v.is_object()) {
                    spans.push(span.clone());
                }
            }
        }
        if spans.len() > before {
            return unique_values(spans);
        }
    }
    spans.extend(
        output
            .get("source_locations")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default(),
    );
    unique_values(spans)
}

fn source_symbol(project: &Value, source: Option<&Value>) -> Option<String> {
    let source = source?;
    project
        .pointer("/project_graph/symbols")
        .and_then(Value::as_array)?
        .iter()
        .find_map(|symbol| {
            let span = symbol.get("source_span")?;
            (span.get("file") == source.get("file")
                && span.get("begin_line") == source.get("begin_line"))
            .then(|| {
                symbol
                    .get("canonical_name")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string()
            })
        })
}

fn error_contributions(output: &Value) -> Vec<Value> {
    let mut values = output
        .get("error_components")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|component| {
            let symmetric = component.pointer("/bound/symmetric_bound");
            let magnitude = symmetric
                .and_then(Value::as_f64)
                .or_else(|| {
                    symmetric
                        .and_then(|v| v.get("value"))
                        .and_then(Value::as_f64)
                })
                .map(f64::abs);
            (component, magnitude)
        })
        .collect::<Vec<_>>();
    values.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    values.into_iter().enumerate().map(|(index,(item,magnitude))| json!({
        "component_id":item.get("component_id"),"source":item.get("source"),"magnitude":magnitude,
        "semantic_cause_id":item.get("semantic_cause_id").or_else(||item.get("origin_id")).or_else(||item.get("component_id")),
        "proof_status":item.get("proof_status").and_then(Value::as_str).unwrap_or("UNRESOLVED"),"rank":index+1
    })).collect()
}

fn amplification_points(output: &Value) -> Vec<Value> {
    fn visit(node: &Value, path: &mut Vec<Value>, out: &mut Vec<Value>) {
        if let Some(object) = node.as_object() {
            if object.get("op").and_then(Value::as_str) == Some("Divide") {
                let factor = object
                    .get("args")
                    .and_then(Value::as_array)
                    .and_then(|args| args.get(1))
                    .filter(|v| v.get("op").and_then(Value::as_str) == Some("Constant"))
                    .and_then(|v| v.get("value"))
                    .and_then(Value::as_f64)
                    .and_then(|v| if v == 0.0 { None } else { Some(1.0 / v.abs()) });
                out.push(json!({"operation":"Divide","expression_path":path,"amplification_factor":factor,
                    "source":origins_from(node).first().cloned(),
                    "explanation":"Division sensitivity can amplify upstream absolute error; denominator range evidence controls the factor."}));
            }
            for (key, value) in object {
                if value.is_object() || value.is_array() {
                    path.push(json!(key));
                    visit(value, path, out);
                    path.pop();
                }
            }
        } else if let Some(items) = node.as_array() {
            for (index, item) in items.iter().enumerate() {
                path.push(json!(index));
                visit(item, path, out);
                path.pop();
            }
        }
    }
    let mut out = vec![];
    visit(
        output.get("formula").unwrap_or(&Value::Null),
        &mut vec![],
        &mut out,
    );
    out
}

fn localize_evidence(
    actual: &Value,
    spans: &[Value],
) -> (&'static str, &'static str, Option<Value>) {
    let direct = if let Some(v) = actual.get("operator_span").filter(|v| v.is_object()) {
        vec![v.clone()]
    } else {
        origins_from(actual)
    };
    if direct.len() == 1 && complete_span(&direct[0]) {
        return (
            "EXACT_SOURCE_SPAN",
            "RECORDED_OPERATOR_OR_ARGUMENT_ORIGIN",
            Some(direct[0].clone()),
        );
    }
    if !direct.is_empty() || spans.len() > 1 {
        return (
            "SOURCE_SPAN_SET",
            "ORIGIN_SET_NO_SINGLE_SPAN_INVENTED",
            spans.first().cloned(),
        );
    }
    if !spans.is_empty() {
        return (
            "SOURCE_FUNCTION",
            "FALLBACK_OUTPUT_OR_SYMBOL_SPAN",
            spans.first().cloned(),
        );
    }
    if actual.is_object() {
        return ("CORRECT_SEMANTIC_NODE", "SEMANTIC_NODE_ONLY", None);
    }
    ("UNRESOLVED", "NO_RECORDED_ORIGIN", None)
}

pub fn debug_project(request: &Value) -> Value {
    let project = request.get("project").unwrap_or(&Value::Null);
    let mut raw = vec![];
    let mut comparable = 0usize;
    for output in project
        .get("outputs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if let (Some(theory), Some(formula)) = (
            output
                .pointer("/residual/theory_expression")
                .filter(|v| v.is_object()),
            output.get("formula").filter(|v| v.is_object()),
        ) {
            comparable += 1;
            if let Some(mut d) = first_difference(theory, formula, vec![], None) {
                d["output"] = output.clone();
                raw.push(d);
            }
        }
        let matrix = output
            .pointer("/end_to_end_claim/verification_matrix")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for layer in matrix {
            if layer.get("status").and_then(Value::as_str) == Some("UNRESOLVED") {
                match layer.get("layer").and_then(Value::as_str){Some("FFI")=>raw.push(json!({"type":"FFI_BOUNDARY_UNRESOLVED","expected":{"representation_mapping":"RANGE_PRESERVING"},"actual":output.pointer("/end_to_end_claim/ffi_boundaries"),"path":["ffi_boundaries"],"role":"ffi","mathematical":false,"boundary_inputs":[],"output":output})),Some("SERIALIZATION")=>raw.push(json!({"type":"SERIALIZATION_DIVERGENCE","expected":{"serialization":"SERIALIZATION_VALUE_PRESERVING"},"actual":output.pointer("/end_to_end_claim/serialization_boundaries"),"path":["serialization_boundaries"],"role":"serialization","mathematical":false,"boundary_inputs":[],"output":output})),_=>{}}
            }
        }
        if output
            .get("range_constraint_status")
            .and_then(Value::as_str)
            == Some("OUTPUT_RANGE_CONSTRAINT_VIOLATED")
        {
            raw.push(json!({"type":"RANGE_VIOLATION","expected":output.pointer("/interval_propagation/output_range_constraint"),"actual":output.get("true_value_enclosure"),"path":["true_value_enclosure"],"role":"range","mathematical":false,"boundary_inputs":[],"output":output}));
        }
        if output
            .pointer("/end_to_end_claim/observed_result_status")
            .and_then(Value::as_str)
            == Some("OBSERVED_VALUE_OUTSIDE_CERTIFIED_RANGE")
        {
            raw.push(json!({"type":"RANGE_VIOLATION","expected":output.get("true_value_enclosure"),"actual":output.pointer("/end_to_end_claim/observed_result"),"path":["observed_result"],"role":"runtime_range","mathematical":false,"runtime_only":true,"boundary_inputs":[],"output":output}));
        }
        if output
            .pointer("/end_to_end_claim/tolerance_status")
            .and_then(Value::as_str)
            == Some("TOTAL_TOLERANCE_NOT_PROVEN")
        {
            raw.push(json!({"type":"ERROR_BOUND_VIOLATION","expected":{"tolerance_status":"TOTAL_TOLERANCE_PROVEN"},"actual":output.get("total_error_bound"),"path":["total_error_bound"],"role":"error","mathematical":false,"boundary_inputs":[],"output":output}));
        }
    }
    let mut groups: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for mut item in raw {
        let output = item.get("output").cloned().unwrap_or(Value::Null);
        let kind = item
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("UNKNOWN_SEMANTIC_DIVERGENCE")
            .to_string();
        let actual = item.get("actual").cloned().unwrap_or(Value::Null);
        let expected = item.get("expected").cloned().unwrap_or(Value::Null);
        let spans = candidate_spans(project, &output, &kind, &actual);
        let (_, _, source) = localize_evidence(&actual, &spans);
        item["source"] = source.clone().unwrap_or(Value::Null);
        item["source_spans"] = Value::Array(spans);
        let key = stable_id(
            "root-cause-key",
            &json!([
                output_root(
                    project,
                    output
                        .get("output_id")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                ),
                kind,
                source,
                semantic_signature(&expected),
                semantic_signature(&actual)
            ]),
        );
        groups.entry(key).or_default().push(item);
    }
    let mut findings = vec![];
    let mut first = vec![];
    let mut subgraphs = vec![];
    let mut roots = vec![];
    let mut traces = vec![];
    for (rank, values) in groups.values().enumerate() {
        let p = &values[0];
        let output = p.get("output").unwrap_or(&Value::Null);
        let kind = p
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("UNKNOWN_SEMANTIC_DIVERGENCE");
        let actual = p.get("actual").unwrap_or(&Value::Null);
        let spans = p
            .get("source_spans")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let (level, evidence, source) = localize_evidence(actual, &spans);
        let output_id = output
            .get("output_id")
            .and_then(Value::as_str)
            .unwrap_or("output");
        let name = output
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("output");
        let root_id = output_root(project, output_id);
        let mut affected_outputs = vec![];
        for value in values {
            let candidate = value.get("output").unwrap_or(&Value::Null);
            let candidate_id = candidate
                .get("output_id")
                .and_then(Value::as_str)
                .unwrap_or("output");
            let affected = json!({"output_id":candidate_id,
                "name":candidate.get("name").and_then(Value::as_str).unwrap_or("output"),
                "root_id":output_root(project,candidate_id),
                "end_to_end_status":candidate.get("end_to_end_status"),"artifact_outputs":[]});
            if !affected_outputs
                .iter()
                .any(|item: &Value| item.get("output_id") == affected.get("output_id"))
            {
                affected_outputs.push(affected);
            }
        }
        let affected_ids = affected_outputs
            .iter()
            .filter_map(|v| v.get("output_id").cloned())
            .collect::<Vec<_>>();
        let divergence_id = stable_id(
            "semantic-divergence",
            &json!([kind, p.get("expected"), actual, source]),
        );
        let difference = json!({"type":kind,"path":p.get("path"),"role":p.get("role")});
        let subgraph_id = stable_id("minimal-divergent-subgraph", &json!(divergence_id));
        subgraphs.push(json!({"subgraph_id":subgraph_id,"theory_nodes":if p.get("expected").is_some_and(Value::is_object){vec![p.get("expected").cloned().unwrap()]}else{vec![]},"implementation_nodes":if actual.is_object(){vec![actual.clone()]}else{vec![]},"boundary_inputs":p.get("boundary_inputs").cloned().unwrap_or_else(||json!([])),"boundary_outputs":affected_ids,"source_spans":spans,"semantic_difference":difference}));
        first.push(json!({"divergence_id":divergence_id,"root_id":root_id,"output_ids":affected_ids,"divergence":{"divergence_id":divergence_id,"type":kind,"expected":p.get("expected"),"actual":actual,"expression_path":p.get("path"),"source":source,"semantic_difference":difference,"mathematical_layer":p.get("mathematical")},"matching_upstream_region":p.get("boundary_inputs"),"downstream_affected_region":affected_ids,"minimal_subgraph_id":subgraph_id}));
        let trace_id = stable_id("debug-trace", &json!([divergence_id, output_id]));
        let trace = json!({"trace_id":trace_id,"root_cause_node":divergence_id,"dependency_path":[{"kind":"SEMANTIC_NODE","id":divergence_id,"source_span":source},{"kind":"OUTPUT","id":output_id,"name":name}],"output_ids":affected_ids,"artifact_outputs":[]});
        traces.push(trace.clone());
        let confidence = if kind == "FFI_BOUNDARY_UNRESOLVED" {
            "BLOCKED_BY_UNRESOLVED_SEMANTICS"
        } else if p.get("runtime_only").and_then(Value::as_bool) == Some(true) {
            "POSSIBLE_ROOT_CAUSE"
        } else if p
            .get("mathematical")
            .and_then(Value::as_bool)
            .unwrap_or(true)
            && source.is_some()
            && matches!(level, "EXACT_SOURCE_SPAN" | "SOURCE_SPAN_SET")
        {
            "STRONG_ROOT_CAUSE_CANDIDATE"
        } else {
            "POSSIBLE_ROOT_CAUSE"
        };
        let mut invalidated = vec![];
        if matches!(
            kind,
            "APPROXIMATION_FAMILY_MISMATCH" | "APPROXIMATION_PARAMETER_MISMATCH"
        ) {
            invalidated.push(json!("CERTIFIED_BOUND_INVALIDATED"));
            invalidated.push(json!("APPROXIMATION_THEOREM_INVALIDATED"));
        }
        if kind == "ERROR_BOUND_VIOLATION" {
            invalidated.push(json!("TOTAL_TOLERANCE_NOT_PROVEN"));
        }
        let finding_id = stable_id("debug-finding", &json!([divergence_id, affected_ids]));
        let symbol = source_symbol(project, source.as_ref());
        let contributions = if kind == "ERROR_BOUND_VIOLATION" {
            error_contributions(output)
        } else {
            vec![]
        };
        let amplification = if contributions.is_empty() {
            vec![]
        } else {
            amplification_points(output)
        };
        let finding = json!({"finding_id":finding_id,"type":kind,"expected":p.get("expected"),"actual":actual,"source":source,"affected_outputs":affected_outputs,"debug_trace":trace,"confidence":confidence,"diagnostic_code":kind,"message_key":format!("semantic_debug.{}",kind.to_lowercase()),"parameters":{"expected":p.get("expected"),"actual":actual,"source_symbol":symbol},"invalidated_claims":invalidated,"error_contributions":contributions,"amplification_points":amplification,"source_spans":spans,"localization_level":level,"localization_confidence":evidence,"blocking_evidence":if kind=="SERIALIZATION_DIVERGENCE"{vec![json!({"reason":"MATHEMATICAL_PAYLOAD_AND_SERIALIZATION_ARE_SEPARATE_CLAIMS"})]}else{vec![]},"rewrite_explanation":[]});
        findings.push(finding.clone());
        roots.push(json!({"finding_id":finding_id,"divergence_type":kind,"confidence":confidence,"expected_semantics":p.get("expected"),"actual_semantics":actual,"source_file":source.as_ref().and_then(|v|v.get("file")).cloned(),"source_span":source,"source_symbol":symbol,"upstream_context":p.get("boundary_inputs"),"downstream_affected_outputs":affected_outputs,"proofs_invalidated":[],"error_bounds_invalidated":invalidated,"range_claims_invalidated":[],"rank":rank+1}));
    }
    let blocked = findings.iter().any(|v| {
        v.get("confidence").and_then(Value::as_str) == Some("BLOCKED_BY_UNRESOLVED_SEMANTICS")
    });
    let status = if !findings.is_empty() {
        if blocked {
            "PARTIAL_SEMANTIC_LOCALIZATION"
        } else {
            "SEMANTIC_DIVERGENCE_LOCALIZED"
        }
    } else if comparable > 0 {
        "NO_SEMANTIC_DIVERGENCE_FOUND"
    } else {
        "SEMANTIC_DEBUG_BLOCKED"
    };
    let exact = findings
        .iter()
        .filter(|v| {
            v.get("localization_level").and_then(Value::as_str) == Some("EXACT_SOURCE_SPAN")
        })
        .count();
    let span_set = findings
        .iter()
        .filter(|v| v.get("localization_level").and_then(Value::as_str) == Some("SOURCE_SPAN_SET"))
        .count();
    let unresolved = findings
        .iter()
        .filter(|v| v.get("localization_level").and_then(Value::as_str) == Some("UNRESOLVED"))
        .count();
    json!({"status":status,"project_status":project.get("status"),"end_to_end_status":project.get("end_to_end_status"),"findings":findings,"first_divergences":first,"minimal_divergent_subgraphs":subgraphs,"root_causes":roots,"affected_outputs":[],"debug_traces":traces,"invalidated_claims":[],"root_results":{},"diagnostics":[],"localization_metrics":{"total":findings.len(),"exact_span":exact,"span_set":span_set,"semantic_node_or_better":findings.len()-unresolved,"unresolved":unresolved,"false_localization":0,"false_localization_basis":"No exact ground-truth assertion made without recorded origin evidence"}})
}

pub fn select_minimal_reproducer(request: &Value) -> Value {
    let finding = request.get("finding").unwrap_or(&Value::Null);
    let expected = finding.get("expected").cloned().unwrap_or(Value::Null);
    let actual = finding.get("actual").cloned().unwrap_or(Value::Null);
    if expected.is_null() || actual.is_null() {
        return json!({"status":"MINIMAL_REPRODUCER_UNRESOLVED","reason":"SEMANTIC_DEPENDENCY_UNKNOWN"});
    }
    json!({"status":"MINIMAL_REPRODUCER_SELECTED","reproducer_id":stable_id("reproducer",&json!([expected,actual,finding.get("type")])),"expected":expected,"actual":actual,"divergence_type":finding.get("type"),"required_inputs":[],"required_config":[],"required_assumptions":[],"semantic_roots":[finding.get("finding_id")],"source_subset":finding.get("source_spans").cloned().unwrap_or_else(||json!([]))})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn origin_union_is_many_to_many_and_deduplicated() {
        let a = json!({"file":"a.py","begin_line":1});
        let b = json!({"file":"a.py","begin_line":2});
        let result = origin_set_operation(
            &json!({"set_operation":"UNION","left":[a.clone(),b.clone()],"right":[a]}),
        );
        assert_eq!(result["origins"].as_array().unwrap().len(), 2);
    }
    #[test]
    fn ambiguous_origins_never_claim_exact_span() {
        let result = debug_project(
            &json!({"project":{"status":"PROJECT_UNRESOLVED","outputs":[{"output_id":"o","name":"y","formula":{"op":"Multiply","source_spans":[{"file":"a.py","begin_line":1,"end_line":1},{"file":"a.py","begin_line":2,"end_line":2}]},"residual":{"theory_expression":{"op":"Divide"}},"source_locations":[]}],"roots":[],"artifacts":[],"project_graph":{"symbols":[]}}}),
        );
        assert_eq!(
            result["findings"][0]["localization_level"],
            "SOURCE_SPAN_SET"
        );
    }
}
