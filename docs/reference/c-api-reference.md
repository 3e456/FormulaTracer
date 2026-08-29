# C ABI v1 Function Reference

FormulaTracer 0.1.0 / generated from the public headers and native source.

Internal items are excluded. Experimental entries are listed but are not stability promises.

| Symbol | Stability | Signature | Ownership / failure |
|---|---|---|---|
| `ft_abi_version` | PUBLIC_STABLE | `uint32_t ft_abi_version(void);` | borrowed/scalar or consumes no ownership |
| `ft_kernel_execute_json` | PUBLIC_STABLE | `char* ft_kernel_execute_json(FT_Context*, const char* request_json);` | owned; caller must free with ft_string_free |
| `ft_context_create` | PUBLIC_STABLE | `FT_Context* ft_context_create(void);` | owned; caller must free with ft_context_free |
| `ft_context_free` | PUBLIC_STABLE | `void ft_context_free(FT_Context*);` | borrowed/scalar or consumes no ownership |
| `ft_context_last_error` | PUBLIC_STABLE | `char* ft_context_last_error(const FT_Context*);` | owned; caller must free with ft_string_free |
| `ft_formula_from_json` | PUBLIC_STABLE | `FT_Formula* ft_formula_from_json(FT_Context*, const char* json);` | owned; caller must free with matching *_free function |
| `ft_formula_from_tex` | PUBLIC_STABLE | `FT_Formula* ft_formula_from_tex(FT_Context*, const char* tex);` | owned; caller must free with matching *_free function |
| `ft_formula_free` | PUBLIC_STABLE | `void ft_formula_free(FT_Formula*);` | borrowed/scalar or consumes no ownership |
| `ft_verify` | PUBLIC_STABLE | `FT_Result* ft_verify(FT_Context*, const FT_Formula*);` | owned; caller must free with matching *_free function |
| `ft_verify_pair` | PUBLIC_STABLE | `FT_Result* ft_verify_pair(FT_Context*, const FT_Formula* theory, const FT_Formula* implementation);` | owned; caller must free with matching *_free function |
| `ft_audit_ir_json` | PUBLIC_STABLE | `FT_Result* ft_audit_ir_json(FT_Context*, const char* json);` | owned; caller must free with matching *_free function |
| `ft_audit_project_ir_json` | PUBLIC_STABLE | `FT_Result* ft_audit_project_ir_json(FT_Context*, const char* json);` | owned; caller must free with matching *_free function |
| `ft_result_status` | PUBLIC_STABLE | `FT_Status ft_result_status(const FT_Result*);` | borrowed/scalar or consumes no ownership |
| `ft_result_to_json` | PUBLIC_STABLE | `char* ft_result_to_json(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_to_tex` | PUBLIC_STABLE | `char* ft_result_to_tex(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_to_audit_bundle_json` | PUBLIC_STABLE | `char* ft_result_to_audit_bundle_json(FT_Context*, const FT_Result*, const char* source_context_json, const char* environment_json, const char* artifact_lineage_json);` | owned; caller must free with ft_string_free |
| `ft_result_theory` | PUBLIC_STABLE | `FT_SemanticObject* ft_result_theory(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_result_implementation` | PUBLIC_STABLE | `FT_SemanticObject* ft_result_implementation(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_semantic_object_to_json` | PUBLIC_STABLE | `char* ft_semantic_object_to_json(const FT_SemanticObject*);` | owned; caller must free with ft_string_free |
| `ft_semantic_object_to_tex` | PUBLIC_STABLE | `char* ft_semantic_object_to_tex(const FT_SemanticObject*);` | owned; caller must free with ft_string_free |
| `ft_semantic_object_free` | PUBLIC_STABLE | `void ft_semantic_object_free(FT_SemanticObject*);` | borrowed/scalar or consumes no ownership |
| `ft_function_from_ir_json` | PUBLIC_STABLE | `FT_Function* ft_function_from_ir_json(FT_Context*, const char* ir_json, const char* metadata_json);` | owned; caller must free with matching *_free function |
| `ft_function_from_json` | PUBLIC_STABLE | `FT_Function* ft_function_from_json(FT_Context*, const char* function_json);` | owned; caller must free with matching *_free function |
| `ft_result_theory_function` | PUBLIC_STABLE | `FT_Function* ft_result_theory_function(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_result_implementation_function` | PUBLIC_STABLE | `FT_Function* ft_result_implementation_function(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_result_error_function` | PUBLIC_STABLE | `FT_Function* ft_result_error_function(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_result_range_lower_function` | PUBLIC_STABLE | `FT_Function* ft_result_range_lower_function(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_result_range_upper_function` | PUBLIC_STABLE | `FT_Function* ft_result_range_upper_function(const FT_Result*);` | owned; caller must free with matching *_free function |
| `ft_function_evaluate_json` | PUBLIC_STABLE | `char* ft_function_evaluate_json(FT_Context*, const FT_Function*, const char* inputs_json);` | owned; caller must free with ft_string_free |
| `ft_function_substitute_json` | PUBLIC_STABLE | `FT_Function* ft_function_substitute_json(FT_Context*, const FT_Function*, const char* values_json);` | owned; caller must free with matching *_free function |
| `ft_function_to_json` | PUBLIC_STABLE | `char* ft_function_to_json(const FT_Function*);` | owned; caller must free with ft_string_free |
| `ft_function_to_tex` | PUBLIC_STABLE | `char* ft_function_to_tex(const FT_Function*);` | owned; caller must free with ft_string_free |
| `ft_function_inspect_json` | PUBLIC_STABLE | `char* ft_function_inspect_json(const FT_Function*);` | owned; caller must free with ft_string_free |
| `ft_function_free` | PUBLIC_STABLE | `void ft_function_free(FT_Function*);` | borrowed/scalar or consumes no ownership |
| `ft_result_diagnostics_json` | PUBLIC_STABLE | `char* ft_result_diagnostics_json(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_assumptions_json` | PUBLIC_STABLE | `char* ft_result_assumptions_json(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_evidence_json` | PUBLIC_STABLE | `char* ft_result_evidence_json(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_error_json` | PUBLIC_STABLE | `char* ft_result_error_json(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_range_json` | PUBLIC_STABLE | `char* ft_result_range_json(const FT_Result*);` | owned; caller must free with ft_string_free |
| `ft_result_free` | PUBLIC_STABLE | `void ft_result_free(FT_Result*);` | borrowed/scalar or consumes no ownership |
| `ft_string_free` | PUBLIC_STABLE | `void ft_string_free(char*);` | borrowed/scalar or consumes no ownership |
