#ifndef FORMULATRACER_H
#define FORMULATRACER_H

#include <stdint.h>

#ifdef _WIN32
#  ifdef FORMULATRACER_BUILD
#    define FT_API __declspec(dllexport)
#  else
#    define FT_API __declspec(dllimport)
#  endif
#else
#  define FT_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define FT_ABI_VERSION 1u

typedef struct FT_Context FT_Context;
typedef struct FT_Formula FT_Formula;
typedef struct FT_Result FT_Result;
typedef struct FT_SemanticObject FT_SemanticObject;
typedef struct FT_Function FT_Function;

typedef enum FT_Status {
  FT_STATUS_OK = 0,
  FT_STATUS_EXACT_EQUALITY = 1,
  FT_STATUS_DIVERGED = 2,
  FT_STATUS_UNRESOLVED = 3,
  FT_STATUS_UNSUPPORTED = 4,
  FT_STATUS_NATIVE_COMPONENT_INCOMPLETE = 5,
  FT_STATUS_INVALID_ARGUMENT = 100,
  FT_STATUS_INVALID_JSON = 101,
  FT_STATUS_PANIC_CONTAINED = 199
} FT_Status;

FT_API uint32_t ft_abi_version(void);
FT_API char* ft_kernel_execute_json(FT_Context*, const char* request_json);
FT_API FT_Context* ft_context_create(void);
FT_API void ft_context_free(FT_Context*);
FT_API char* ft_context_last_error(const FT_Context*);
FT_API FT_Formula* ft_formula_from_json(FT_Context*, const char* json);
FT_API FT_Formula* ft_formula_from_tex(FT_Context*, const char* tex);
FT_API void ft_formula_free(FT_Formula*);
FT_API FT_Result* ft_verify(FT_Context*, const FT_Formula*);
FT_API FT_Result* ft_verify_pair(FT_Context*, const FT_Formula* theory, const FT_Formula* implementation);
FT_API FT_Result* ft_audit_ir_json(FT_Context*, const char* json);
FT_API FT_Result* ft_audit_project_ir_json(FT_Context*, const char* json);
FT_API FT_Status ft_result_status(const FT_Result*);
FT_API char* ft_result_to_json(const FT_Result*);
FT_API char* ft_result_to_tex(const FT_Result*);
FT_API char* ft_result_to_audit_bundle_json(FT_Context*, const FT_Result*, const char* source_context_json,
                                            const char* environment_json, const char* artifact_lineage_json);
FT_API FT_SemanticObject* ft_result_theory(const FT_Result*);
FT_API FT_SemanticObject* ft_result_implementation(const FT_Result*);
FT_API char* ft_semantic_object_to_json(const FT_SemanticObject*);
FT_API char* ft_semantic_object_to_tex(const FT_SemanticObject*);
FT_API void ft_semantic_object_free(FT_SemanticObject*);
FT_API FT_Function* ft_function_from_ir_json(FT_Context*, const char* ir_json, const char* metadata_json);
FT_API FT_Function* ft_function_from_json(FT_Context*, const char* function_json);
FT_API FT_Function* ft_result_theory_function(const FT_Result*);
FT_API FT_Function* ft_result_implementation_function(const FT_Result*);
FT_API FT_Function* ft_result_error_function(const FT_Result*);
FT_API FT_Function* ft_result_range_lower_function(const FT_Result*);
FT_API FT_Function* ft_result_range_upper_function(const FT_Result*);
FT_API char* ft_function_evaluate_json(FT_Context*, const FT_Function*, const char* inputs_json);
FT_API FT_Function* ft_function_substitute_json(FT_Context*, const FT_Function*, const char* values_json);
FT_API char* ft_function_to_json(const FT_Function*);
FT_API char* ft_function_to_tex(const FT_Function*);
FT_API char* ft_function_inspect_json(const FT_Function*);
FT_API void ft_function_free(FT_Function*);
FT_API char* ft_result_diagnostics_json(const FT_Result*);
FT_API char* ft_result_assumptions_json(const FT_Result*);
FT_API char* ft_result_evidence_json(const FT_Result*);
FT_API char* ft_result_error_json(const FT_Result*);
FT_API char* ft_result_range_json(const FT_Result*);
FT_API void ft_result_free(FT_Result*);
FT_API void ft_string_free(char*);

#ifdef __cplusplus
}
#endif
#endif
