//! Stable C ABI v1. All public data handles are opaque.

#![allow(non_camel_case_types)]
// The pointer/lifetime contract is documented once in include/formulatracer.h;
// safe Rust callers use formulatracer_core::Formula rather than this FFI layer.
#![allow(clippy::missing_safety_doc)]

use std::collections::BTreeMap;
use std::ffi::{c_char, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;

use formulatracer_core::{
    execute_kernel, to_tex, Formula as CoreFormula, MathematicalFunction, SemanticObject,
    VerificationResult,
};
use serde_json::{json, Value};

pub const FT_ABI_VERSION: u32 = 1;

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FT_Status {
    FT_STATUS_OK = 0,
    FT_STATUS_EXACT_EQUALITY = 1,
    FT_STATUS_DIVERGED = 2,
    FT_STATUS_UNRESOLVED = 3,
    FT_STATUS_UNSUPPORTED = 4,
    FT_STATUS_NATIVE_COMPONENT_INCOMPLETE = 5,
    FT_STATUS_INVALID_ARGUMENT = 100,
    FT_STATUS_INVALID_JSON = 101,
    FT_STATUS_PANIC_CONTAINED = 199,
}

#[derive(Debug, Default)]
pub struct FT_Context {
    last_error: Option<String>,
}

#[derive(Debug)]
pub struct FT_Formula {
    core: CoreFormula,
}

#[derive(Debug)]
pub struct FT_Result {
    status: FT_Status,
    value: VerificationResult,
}

#[derive(Debug)]
pub struct FT_SemanticObject {
    value: SemanticObject,
}

#[derive(Debug)]
pub struct FT_Function {
    value: MathematicalFunction,
}

fn c_input<'a>(input: *const c_char) -> Result<&'a str, FT_Status> {
    if input.is_null() {
        return Err(FT_Status::FT_STATUS_INVALID_ARGUMENT);
    }
    // SAFETY: C ABI contract requires a live NUL-terminated UTF-8 string for the call duration.
    unsafe { CStr::from_ptr(input) }
        .to_str()
        .map_err(|_| FT_Status::FT_STATUS_INVALID_ARGUMENT)
}

fn result_handle(status: FT_Status, value: VerificationResult) -> *mut FT_Result {
    Box::into_raw(Box::new(FT_Result { status, value }))
}

fn unresolved(diagnostic: impl Into<String>, tex: String) -> *mut FT_Result {
    result_handle(
        FT_Status::FT_STATUS_UNRESOLVED,
        VerificationResult {
            schema_version: "1.0".into(),
            status: "UNRESOLVED".into(),
            relation: "UNRESOLVED".into(),
            theory_hash: None,
            implementation_hash: None,
            theory: None,
            implementation: None,
            assumptions: vec![],
            diagnostics: vec![diagnostic.into()],
            evidence: vec![],
            error: None,
            range: None,
            provenance: None,
            debugger: None,
            reconstruction: None,
            tex,
        },
    )
}

#[no_mangle]
pub extern "C" fn ft_abi_version() -> u32 {
    FT_ABI_VERSION
}

/// Execute a versioned semantic-kernel request through the single native core.
#[no_mangle]
pub unsafe extern "C" fn ft_kernel_execute_json(
    context: *mut FT_Context,
    input: *const c_char,
) -> *mut c_char {
    let operation = catch_unwind(AssertUnwindSafe(|| -> Result<String, String> {
        let request: Value =
            serde_json::from_str(c_input(input).map_err(|status| format!("{status:?}"))?)
                .map_err(|error| format!("INVALID_JSON: {error}"))?;
        let result = execute_kernel(&request).map_err(|error| error.to_string())?;
        serde_json::to_string(&result).map_err(|error| error.to_string())
    }));
    match operation {
        Ok(Ok(value)) => string_result(value),
        Ok(Err(error)) => {
            set_error(context, error);
            ptr::null_mut()
        }
        Err(_) => {
            set_error(context, "PANIC_CONTAINED".into());
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub extern "C" fn ft_context_create() -> *mut FT_Context {
    Box::into_raw(Box::new(FT_Context::default()))
}

#[no_mangle]
pub unsafe extern "C" fn ft_context_free(context: *mut FT_Context) {
    if !context.is_null() {
        /* SAFETY: ownership was returned by ft_context_create and is released once. */
        unsafe {
            drop(Box::from_raw(context));
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_formula_from_json(
    context: *mut FT_Context,
    input: *const c_char,
) -> *mut FT_Formula {
    let operation = catch_unwind(AssertUnwindSafe(|| {
        let input = c_input(input)?;
        CoreFormula::from_json(input)
            .map(|core| Box::into_raw(Box::new(FT_Formula { core })))
            .map_err(|_| FT_Status::FT_STATUS_INVALID_JSON)
    }));
    match operation {
        Ok(Ok(handle)) => handle,
        Ok(Err(status)) => {
            set_error(context, format!("{status:?}"));
            ptr::null_mut()
        }
        Err(_) => {
            set_error(context, "PANIC_CONTAINED".into());
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_formula_from_tex(
    context: *mut FT_Context,
    input: *const c_char,
) -> *mut FT_Formula {
    let operation = catch_unwind(AssertUnwindSafe(|| -> Result<*mut FT_Formula, String> {
        let tex = c_input(input).map_err(|status| format!("{status:?}"))?;
        CoreFormula::from_tex(tex)
            .map(|core| Box::into_raw(Box::new(FT_Formula { core })))
            .map_err(|error| error.to_string())
    }));
    match operation {
        Ok(Ok(handle)) => handle,
        Ok(Err(error)) => {
            set_error(context, error);
            ptr::null_mut()
        }
        Err(_) => {
            set_error(context, "PANIC_CONTAINED".into());
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_formula_free(formula: *mut FT_Formula) {
    if !formula.is_null() {
        /* SAFETY: ownership was returned by a formula constructor and is released once. */
        unsafe {
            drop(Box::from_raw(formula));
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_verify(
    _context: *mut FT_Context,
    formula: *const FT_Formula,
) -> *mut FT_Result {
    if formula.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller retains a live formula handle for this call.
    let formula = unsafe { &*formula };
    unresolved(
        "verification requires an independent theory and implementation",
        to_tex(&formula.core.document().payload),
    )
}

#[no_mangle]
pub unsafe extern "C" fn ft_verify_pair(
    _context: *mut FT_Context,
    theory: *const FT_Formula,
    implementation: *const FT_Formula,
) -> *mut FT_Result {
    if theory.is_null() || implementation.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller retains both live handles for this call.
    let (theory, implementation) = unsafe { (&*theory, &*implementation) };
    let value = theory.core.verify_against(&implementation.core);
    let status = if value.status == "EXACT_EQUALITY" {
        FT_Status::FT_STATUS_EXACT_EQUALITY
    } else {
        FT_Status::FT_STATUS_DIVERGED
    };
    result_handle(status, value)
}

#[no_mangle]
pub unsafe extern "C" fn ft_audit_ir_json(
    context: *mut FT_Context,
    input: *const c_char,
) -> *mut FT_Result {
    let formula = ft_formula_from_json(context, input);
    if formula.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: formula was just created and remains live until explicitly freed below.
    let formula_ref = unsafe { &*formula };
    let result = unresolved(
        "IR parsed and canonicalized; independent theory is required",
        to_tex(&formula_ref.core.document().payload),
    );
    ft_formula_free(formula);
    result
}

/// Audit a frontend-produced project IR bundle through the same native core.
#[no_mangle]
pub unsafe extern "C" fn ft_audit_project_ir_json(
    context: *mut FT_Context,
    input: *const c_char,
) -> *mut FT_Result {
    ft_audit_ir_json(context, input)
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_status(result: *const FT_Result) -> FT_Status {
    if result.is_null() {
        FT_Status::FT_STATUS_INVALID_ARGUMENT
    } else {
        /* SAFETY: caller provides a live result handle. */
        unsafe { (*result).status }
    }
}

fn string_result(value: String) -> *mut c_char {
    CString::new(value.replace('\0', "\\u0000"))
        .map(CString::into_raw)
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_to_json(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle.
    string_result(
        serde_json::to_string(unsafe { &(*result).value })
            .unwrap_or_else(|_| "{\"status\":\"UNRESOLVED\"}".into()),
    )
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_to_tex(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        ptr::null_mut()
    } else {
        /* SAFETY: caller provides a live result handle. */
        string_result(unsafe { (*result).value.to_tex() })
    }
}

/// Serialize an integrity-protected AuditBundle from the canonical result.
/// The three context arguments are optional JSON objects and never alter claims.
#[no_mangle]
pub unsafe extern "C" fn ft_result_to_audit_bundle_json(
    context: *mut FT_Context,
    result: *const FT_Result,
    source_context_json: *const c_char,
    environment_json: *const c_char,
    artifact_lineage_json: *const c_char,
) -> *mut c_char {
    if result.is_null() {
        set_error(context, "INVALID_ARGUMENT".into());
        return ptr::null_mut();
    }
    let parse_optional = |pointer: *const c_char| -> Result<Value, String> {
        if pointer.is_null() {
            return Ok(json!({}));
        }
        let text = c_input(pointer).map_err(|status| format!("{status:?}"))?;
        serde_json::from_str(text).map_err(|error| format!("INVALID_JSON: {error}"))
    };
    let operation = catch_unwind(AssertUnwindSafe(|| -> Result<String, String> {
        let source_context = parse_optional(source_context_json)?;
        let environment = parse_optional(environment_json)?;
        let artifact_lineage = parse_optional(artifact_lineage_json)?;
        // SAFETY: caller provides a live result handle for this synchronous clone.
        let value = unsafe { &(*result).value };
        value
            .to_audit_bundle(source_context, environment, artifact_lineage)
            .and_then(|bundle| bundle.to_json())
            .map_err(|error| error.to_string())
    }));
    match operation {
        Ok(Ok(value)) => string_result(value),
        Ok(Err(error)) => {
            set_error(context, error);
            ptr::null_mut()
        }
        Err(_) => {
            set_error(context, "PANIC_CONTAINED".into());
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_theory(result: *const FT_Result) -> *mut FT_SemanticObject {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous clone.
    unsafe { (*result).value.theory.clone() }
        .map(|value| Box::into_raw(Box::new(FT_SemanticObject { value })))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_implementation(
    result: *const FT_Result,
) -> *mut FT_SemanticObject {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous clone.
    unsafe { (*result).value.implementation.clone() }
        .map(|value| Box::into_raw(Box::new(FT_SemanticObject { value })))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_semantic_object_to_json(
    object: *const FT_SemanticObject,
) -> *mut c_char {
    if object.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live semantic-object handle.
        string_result(serde_json::to_string(unsafe { &(*object).value }).unwrap_or_default())
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_semantic_object_to_tex(
    object: *const FT_SemanticObject,
) -> *mut c_char {
    if object.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live semantic-object handle.
        string_result(unsafe { (*object).value.to_tex() })
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_semantic_object_free(object: *mut FT_SemanticObject) {
    if !object.is_null() {
        // SAFETY: ownership was returned by ft_result_theory/implementation and is released once.
        unsafe { drop(Box::from_raw(object)) };
    }
}

/// Construct an evaluable mathematical function from canonical Mathematical IR.
/// Metadata is optional JSON with assumptions/evidence/provenance fields.
#[no_mangle]
pub unsafe extern "C" fn ft_function_from_ir_json(
    context: *mut FT_Context,
    ir_json: *const c_char,
    metadata_json: *const c_char,
) -> *mut FT_Function {
    let operation = catch_unwind(AssertUnwindSafe(
        || -> Result<*mut FT_Function, FT_Status> {
            let expression: Value = serde_json::from_str(c_input(ir_json)?)
                .map_err(|_| FT_Status::FT_STATUS_INVALID_JSON)?;
            let metadata: Value = if metadata_json.is_null() {
                json!({})
            } else {
                serde_json::from_str(c_input(metadata_json)?)
                    .map_err(|_| FT_Status::FT_STATUS_INVALID_JSON)?
            };
            let assumptions = metadata
                .get("assumptions")
                .cloned()
                .map(serde_json::from_value)
                .transpose()
                .map_err(|_| FT_Status::FT_STATUS_INVALID_JSON)?
                .unwrap_or_default();
            let evidence = metadata
                .get("evidence")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let provenance = metadata.get("provenance").cloned();
            Ok(Box::into_raw(Box::new(FT_Function {
                value: MathematicalFunction::from_expression(
                    expression,
                    assumptions,
                    evidence,
                    provenance,
                ),
            })))
        },
    ));
    match operation {
        Ok(Ok(handle)) => handle,
        Ok(Err(status)) => {
            set_error(context, format!("{status:?}"));
            ptr::null_mut()
        }
        Err(_) => {
            set_error(context, "PANIC_CONTAINED".into());
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_from_json(
    context: *mut FT_Context,
    input: *const c_char,
) -> *mut FT_Function {
    let Ok(input) = c_input(input) else {
        set_error(context, "INVALID_ARGUMENT".into());
        return ptr::null_mut();
    };
    match serde_json::from_str::<MathematicalFunction>(input) {
        Ok(value) => Box::into_raw(Box::new(FT_Function { value })),
        Err(error) => {
            set_error(context, format!("INVALID_JSON: {error}"));
            ptr::null_mut()
        }
    }
}

fn result_function(result: &VerificationResult, object: &SemanticObject) -> *mut FT_Function {
    Box::into_raw(Box::new(FT_Function {
        value: object.as_function(
            result.assumptions.clone(),
            result.evidence.clone(),
            result.provenance.clone(),
        ),
    }))
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_theory_function(result: *const FT_Result) -> *mut FT_Function {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous clone.
    let result = unsafe { &(*result).value };
    result
        .theory
        .as_ref()
        .map(|object| result_function(result, object))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_implementation_function(
    result: *const FT_Result,
) -> *mut FT_Function {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous clone.
    let result = unsafe { &(*result).value };
    result
        .implementation
        .as_ref()
        .map(|object| result_function(result, object))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_error_function(result: *const FT_Result) -> *mut FT_Function {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous projection.
    unsafe { (*result).value.error_function() }
        .map(|value| Box::into_raw(Box::new(FT_Function { value })))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_range_lower_function(
    result: *const FT_Result,
) -> *mut FT_Function {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous projection.
    unsafe { (*result).value.range_lower_function() }
        .map(|value| Box::into_raw(Box::new(FT_Function { value })))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_range_upper_function(
    result: *const FT_Result,
) -> *mut FT_Function {
    if result.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live result handle for this synchronous projection.
    unsafe { (*result).value.range_upper_function() }
        .map(|value| Box::into_raw(Box::new(FT_Function { value })))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_evaluate_json(
    context: *mut FT_Context,
    function: *const FT_Function,
    inputs_json: *const c_char,
) -> *mut c_char {
    if function.is_null() {
        set_error(context, "INVALID_ARGUMENT".into());
        return ptr::null_mut();
    }
    let operation = catch_unwind(AssertUnwindSafe(|| {
        let inputs: BTreeMap<String, Value> = serde_json::from_str(c_input(inputs_json)?)
            .map_err(|_| FT_Status::FT_STATUS_INVALID_JSON)?;
        // SAFETY: the caller keeps the opaque function handle alive for this call.
        unsafe { (*function).value.evaluate_json(&inputs) }
            .map(|value| string_result(value.to_string()))
            .map_err(|_| FT_Status::FT_STATUS_UNRESOLVED)
    }));
    match operation {
        Ok(Ok(value)) => value,
        Ok(Err(status)) => {
            set_error(context, format!("{status:?}"));
            ptr::null_mut()
        }
        Err(_) => {
            set_error(context, "PANIC_CONTAINED".into());
            ptr::null_mut()
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_substitute_json(
    context: *mut FT_Context,
    function: *const FT_Function,
    values_json: *const c_char,
) -> *mut FT_Function {
    if function.is_null() {
        set_error(context, "INVALID_ARGUMENT".into());
        return ptr::null_mut();
    }
    let Ok(input) = c_input(values_json) else {
        set_error(context, "INVALID_ARGUMENT".into());
        return ptr::null_mut();
    };
    let Ok(values) = serde_json::from_str::<BTreeMap<String, Value>>(input) else {
        set_error(context, "INVALID_JSON".into());
        return ptr::null_mut();
    };
    // SAFETY: the caller keeps the opaque function handle alive for this call.
    let value = unsafe { (*function).value.substitute(&values) };
    Box::into_raw(Box::new(FT_Function { value }))
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_to_json(function: *const FT_Function) -> *mut c_char {
    if function.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live function handle.
        string_result(serde_json::to_string(unsafe { &(*function).value }).unwrap_or_default())
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_to_tex(function: *const FT_Function) -> *mut c_char {
    if function.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live function handle.
        string_result(unsafe { (*function).value.to_tex() })
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_inspect_json(function: *const FT_Function) -> *mut c_char {
    if function.is_null() {
        return ptr::null_mut();
    }
    // SAFETY: caller provides a live function handle.
    unsafe { (*function).value.inspect() }
        .ok()
        .map(|value| string_result(value.to_string()))
        .unwrap_or(ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "C" fn ft_function_free(function: *mut FT_Function) {
    if !function.is_null() {
        // SAFETY: ownership was returned by a function constructor and is released once.
        unsafe { drop(Box::from_raw(function)) };
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_diagnostics_json(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        ptr::null_mut()
    } else {
        /* SAFETY: caller provides a live result handle. */
        string_result(
            serde_json::to_string(unsafe { &(*result).value.diagnostics }).unwrap_or_default(),
        )
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_assumptions_json(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        ptr::null_mut()
    } else {
        /* SAFETY: caller provides a live result handle. */
        string_result(
            serde_json::to_string(unsafe { &(*result).value.assumptions }).unwrap_or_default(),
        )
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_evidence_json(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live result handle.
        string_result(
            serde_json::to_string(unsafe { &(*result).value.evidence }).unwrap_or_default(),
        )
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_error_json(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live result handle.
        string_result(serde_json::to_string(unsafe { &(*result).value.error }).unwrap_or_default())
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_range_json(result: *const FT_Result) -> *mut c_char {
    if result.is_null() {
        ptr::null_mut()
    } else {
        // SAFETY: caller provides a live result handle.
        string_result(serde_json::to_string(unsafe { &(*result).value.range }).unwrap_or_default())
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_result_free(result: *mut FT_Result) {
    if !result.is_null() {
        /* SAFETY: ownership was returned by an ft_* result function and is released once. */
        unsafe {
            drop(Box::from_raw(result));
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_string_free(value: *mut c_char) {
    if !value.is_null() {
        /* SAFETY: ownership was returned by an ft_* string function and is released once. */
        unsafe {
            drop(CString::from_raw(value));
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn ft_context_last_error(context: *const FT_Context) -> *mut c_char {
    if context.is_null() {
        ptr::null_mut()
    } else {
        /* SAFETY: caller provides a live context handle. */
        string_result(unsafe { (*context).last_error.clone().unwrap_or_default() })
    }
}

fn set_error(context: *mut FT_Context, error: String) {
    if !context.is_null() {
        /* SAFETY: caller provides an exclusive context for this synchronous call. */
        unsafe {
            (*context).last_error = Some(error);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn abi_version_is_stable() {
        assert_eq!(ft_abi_version(), 1);
    }
    #[test]
    fn exact_pair_uses_core_canonicalization() {
        // SAFETY: every pointer is created here, kept live, and released exactly once.
        unsafe {
            let context = ft_context_create();
            let a = CString::new(r#"{"op":"Constant","value":42,"radix":16}"#).unwrap();
            let b = CString::new(r#"{"op":"Constant","value":42,"radix":10}"#).unwrap();
            let fa = ft_formula_from_json(context, a.as_ptr());
            let fb = ft_formula_from_json(context, b.as_ptr());
            let result = ft_verify_pair(context, fa, fb);
            assert_eq!(
                ft_result_status(result),
                FT_Status::FT_STATUS_EXACT_EQUALITY
            );
            ft_result_free(result);
            ft_formula_free(fa);
            ft_formula_free(fb);
            ft_context_free(context);
        }
    }

    #[test]
    fn invalid_and_null_inputs_fail_closed_without_panicking() {
        // SAFETY: null handling is part of ABI v1; owned non-null handles are released once.
        unsafe {
            ft_context_free(ptr::null_mut());
            ft_formula_free(ptr::null_mut());
            ft_result_free(ptr::null_mut());
            ft_string_free(ptr::null_mut());
            assert_eq!(
                ft_result_status(ptr::null()),
                FT_Status::FT_STATUS_INVALID_ARGUMENT
            );
            let context = ft_context_create();
            let invalid = CString::new("{").unwrap();
            assert!(ft_formula_from_json(context, invalid.as_ptr()).is_null());
            let error = ft_context_last_error(context);
            assert!(!error.is_null());
            ft_string_free(error);
            ft_context_free(context);
        }
    }
}
