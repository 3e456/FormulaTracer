//! Provider-neutral labeled array/table semantics.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::coverage::CoverageLevel;
use crate::{FormulaTracerError, RelationKind, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum LabeledContainerKind {
    LabeledArray,
    LabeledTable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum AlignmentKind {
    Positional,
    ExactLabels,
    Inner,
    Outer,
    Left,
    Right,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum MissingPolicy {
    Propagate,
    Ignore,
    Fill,
    Drop,
    ConditionalFallback,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum SelectionKind {
    Label,
    Position,
    BooleanMask,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub(crate) enum InterpolationKind {
    Nearest,
    Linear,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct DimensionSpec {
    pub name: String,
    pub length: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub(crate) struct LabeledDataObject {
    pub container_kind: LabeledContainerKind,
    pub provider: String,
    pub value_ir: Value,
    #[serde(default)]
    pub dimensions: Vec<DimensionSpec>,
    #[serde(default)]
    pub coordinates: BTreeMap<String, Vec<Value>>,
    pub dtype: Option<String>,
}

fn required<'a>(request: &'a Value, key: &str) -> Result<&'a Value> {
    request.get(key).ok_or_else(|| {
        FormulaTracerError::InvalidSemanticDocument(format!("labeled-data request missing {key}"))
    })
}

fn decode_object(value: &Value) -> Result<LabeledDataObject> {
    let object: LabeledDataObject = serde_json::from_value(value.clone())?;
    let names = object
        .dimensions
        .iter()
        .map(|d| d.name.as_str())
        .collect::<BTreeSet<_>>();
    if names.len() != object.dimensions.len() {
        return Err(FormulaTracerError::InvalidSemanticDocument(
            "duplicate named dimension".into(),
        ));
    }
    for dimension in &object.dimensions {
        if let Some(labels) = object.coordinates.get(&dimension.name) {
            if labels.len() != dimension.length {
                return Err(FormulaTracerError::InvalidSemanticDocument(format!(
                    "coordinate length mismatch for {}",
                    dimension.name
                )));
            }
        }
    }
    Ok(object)
}

fn label_key(value: &Value) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "null".into())
}

fn aligned_labels(left: &[Value], right: &[Value], kind: AlignmentKind) -> Vec<Value> {
    let right_keys = right.iter().map(label_key).collect::<BTreeSet<_>>();
    let left_keys = left.iter().map(label_key).collect::<BTreeSet<_>>();
    match kind {
        AlignmentKind::Inner => left
            .iter()
            .filter(|item| right_keys.contains(&label_key(item)))
            .cloned()
            .collect(),
        AlignmentKind::Outer => {
            let mut result = left.to_vec();
            result.extend(
                right
                    .iter()
                    .filter(|item| !left_keys.contains(&label_key(item)))
                    .cloned(),
            );
            result
        }
        AlignmentKind::Left => left.to_vec(),
        AlignmentKind::Right => right.to_vec(),
        AlignmentKind::ExactLabels | AlignmentKind::Positional => left.to_vec(),
    }
}

fn binary(request: &Value) -> Result<Value> {
    let left = decode_object(required(request, "left")?)?;
    let right = decode_object(required(request, "right")?)?;
    let kind: AlignmentKind = serde_json::from_value(required(request, "alignment")?.clone())?;
    if left.dimensions.iter().map(|d| &d.name).collect::<Vec<_>>()
        != right.dimensions.iter().map(|d| &d.name).collect::<Vec<_>>()
    {
        return Ok(json!({
            "status":CoverageLevel::Unresolved,
            "code":"DIMENSION_ALIGNMENT_UNRESOLVED",
            "missing":["explicit dimension mapping"]
        }));
    }
    let mut output_coordinates = BTreeMap::new();
    let mut mapping = vec![];
    for dimension in &left.dimensions {
        let right_dimension = right
            .dimensions
            .iter()
            .find(|candidate| candidate.name == dimension.name)
            .expect("dimension names were checked above");
        if kind == AlignmentKind::Positional {
            if dimension.length != right_dimension.length {
                return Ok(json!({
                    "status":CoverageLevel::Unresolved,
                    "code":"POSITIONAL_LENGTH_MISMATCH",
                    "dimension":dimension.name
                }));
            }
            mapping.extend((0..dimension.length).map(|position| {
                json!({
                    "dimension":dimension.name,
                    "output_position":position,
                    "left_position":position,
                    "right_position":position
                })
            }));
            if let Some(labels) = left.coordinates.get(&dimension.name) {
                output_coordinates.insert(dimension.name.clone(), labels.clone());
            }
            continue;
        }
        let Some(left_labels) = left.coordinates.get(&dimension.name) else {
            return Ok(json!({
                "status":CoverageLevel::Unresolved,
                "code":"LABEL_ALIGNMENT_UNRESOLVED",
                "missing":[format!("left coordinates for {}",dimension.name)]
            }));
        };
        let Some(right_labels) = right.coordinates.get(&dimension.name) else {
            return Ok(json!({
                "status":CoverageLevel::Unresolved,
                "code":"LABEL_ALIGNMENT_UNRESOLVED",
                "missing":[format!("right coordinates for {}",dimension.name)]
            }));
        };
        if kind == AlignmentKind::ExactLabels && left_labels != right_labels {
            return Ok(json!({"status":CoverageLevel::Unresolved,
                "code":"EXACT_LABEL_MISMATCH","dimension":dimension.name}));
        }
        let output = aligned_labels(left_labels, right_labels, kind);
        for label in &output {
            mapping.push(json!({
                "dimension":dimension.name,
                "output_label":label,
                "left_present":left_labels.iter().any(|x| x == label),
                "right_present":right_labels.iter().any(|x| x == label)
            }));
        }
        output_coordinates.insert(dimension.name.clone(), output);
    }
    let missing: MissingPolicy =
        serde_json::from_value(required(request, "missing_policy")?.clone())?;
    let operation = required(request, "value_operation")?.clone();
    let value_ir = if missing == MissingPolicy::ConditionalFallback {
        json!({
            "op":"Piecewise",
            "cases":[
                {"when":"both_available","then":operation},
                {"when":"left_only","then":left.value_ir},
                {"when":"right_only","then":right.value_ir}
            ],
            "otherwise":{"op":"Missing"}
        })
    } else {
        operation
    };
    Ok(json!({
        "status":CoverageLevel::FullReconstruction,
        "value_semantics":value_ir,
        "dimension_semantics":left.dimensions,
        "coordinate_semantics":output_coordinates,
        "alignment_semantics":{"kind":kind,"mapping":mapping},
        "missingness_semantics":missing,
        "evidence":[{"kind":"REFERENCE_CONTRACT","provider":left.provider}]
    }))
}

fn selection(request: &Value) -> Result<Value> {
    let object = decode_object(required(request, "input")?)?;
    let kind: SelectionKind = serde_json::from_value(required(request, "selection_kind")?.clone())?;
    let selector = required(request, "selector")?;
    if kind == SelectionKind::Label {
        let dimension = required(request, "dimension")?.as_str().unwrap_or("");
        if !object.coordinates.contains_key(dimension) {
            return Ok(json!({"status":CoverageLevel::Unresolved,
                "code":"LABEL_SELECTION_WITHOUT_COORDINATE"}));
        }
    }
    Ok(json!({
        "status":CoverageLevel::FullReconstruction,
        "value_semantics":{"op":"Selection","kind":kind,"input":object.value_ir,"selector":selector},
        "selection_semantics":{"kind":kind,"selector":selector},
        "evidence":[{"kind":"REFERENCE_CONTRACT","provider":object.provider}]
    }))
}

fn reduction(request: &Value) -> Result<Value> {
    let object = decode_object(required(request, "input")?)?;
    let dimensions: Vec<String> = serde_json::from_value(required(request, "dimensions")?.clone())?;
    if dimensions
        .iter()
        .any(|name| !object.dimensions.iter().any(|d| &d.name == name))
    {
        return Ok(
            json!({"status":CoverageLevel::Unresolved,"code":"UNKNOWN_REDUCTION_DIMENSION"}),
        );
    }
    let missing: MissingPolicy =
        serde_json::from_value(required(request, "missing_policy")?.clone())?;
    Ok(json!({
        "status":CoverageLevel::FullReconstruction,
        "value_semantics":{
            "op":required(request,"reduction")?, "input":object.value_ir,
            "dimensions":dimensions, "skip_missing":missing == MissingPolicy::Ignore
        },
        "reduction_semantics":{
            "dimensions":dimensions,
            "missing_policy":missing,
            "dtype":request.get("dtype").cloned().unwrap_or(Value::Null),
            "keepdims":request.get("keepdims").cloned().unwrap_or(json!(false))
        },
        "evidence":[{"kind":"REFERENCE_CONTRACT","provider":object.provider}]
    }))
}

fn interpolation(request: &Value) -> Result<Value> {
    let object = decode_object(required(request, "input")?)?;
    let method: InterpolationKind = serde_json::from_value(required(request, "method")?.clone())?;
    Ok(json!({
        "status":CoverageLevel::FullReconstruction,
        "value_semantics":{"op":"Interpolation","method":method,"input":object.value_ir,
            "coordinates":required(request,"new_coordinates")?},
        "relation":RelationKind::ApproximationOf,
        "exact_promotion":false,
        "evidence":[{"kind":"REFERENCE_CONTRACT","provider":object.provider}],
        "proof_obligations":["INTERPOLATION_ERROR_BOUND_NOT_ESTABLISHED"]
    }))
}

pub(crate) fn labeled_data_operation(request: &Value) -> Result<Value> {
    match required(request, "action")?.as_str().unwrap_or("") {
        "BINARY" => binary(request),
        "SELECTION" => selection(request),
        "REDUCTION" => reduction(request),
        "INTERPOLATION" => interpolation(request),
        _ => Err(FormulaTracerError::InvalidSemanticDocument(
            "unknown labeled-data action".into(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn array(provider: &str, labels: &[i64]) -> Value {
        json!({
            "container_kind":"LABELED_ARRAY", "provider":provider,
            "value_ir":{"op":"FreeVariable","name":"x"},
            "dimensions":[{"name":"time","length":labels.len()}],
            "coordinates":{"time":labels}, "dtype":"float64"
        })
    }

    #[test]
    fn inner_alignment_records_label_mapping() {
        let result = labeled_data_operation(&json!({
            "action":"BINARY", "left":array("xarray", &[0,1,2]),
            "right":array("xarray", &[1,2,3]), "alignment":"INNER",
            "missing_policy":"PROPAGATE", "value_operation":{"op":"Add"}
        }))
        .unwrap();
        assert_eq!(result["status"], "FULL_RECONSTRUCTION");
        assert_eq!(
            result["alignment_semantics"]["mapping"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
    }

    #[test]
    fn interpolation_is_never_exact() {
        let result = labeled_data_operation(&json!({
            "action":"INTERPOLATION", "input":array("xarray", &[0,1]),
            "method":"LINEAR", "new_coordinates":{"time":[0.5]}
        }))
        .unwrap();
        assert_eq!(result["relation"], "APPROXIMATION_OF");
        assert_eq!(result["exact_promotion"], false);
    }
}
