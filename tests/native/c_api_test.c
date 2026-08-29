#include "formulatracer.h"
#include <assert.h>
#include <string.h>

int main(void) {
  assert(ft_abi_version() == FT_ABI_VERSION);
  FT_Context* context = ft_context_create();
  char* reconstruction = ft_kernel_execute_json(context,
      "{\"schema_version\":\"1.0\",\"kernel\":\"F\",\"operation\":\"RECONSTRUCT\","
      "\"request\":{\"original_theory\":{\"op\":\"Constant\",\"value\":2},"
      "\"reconstructed_theory\":{\"op\":\"Constant\",\"value\":2},"
      "\"structural_facts\":{},\"temporaries\":[],\"safety\":{},\"relation_chain\":[],"
      "\"assumptions\":[],\"proof_obligations\":[],\"exact_egraph_verified\":false}}" );
  assert(reconstruction != 0 && strstr(reconstruction, "\"status\":\"EXACT\"") != 0);
  ft_string_free(reconstruction);
  FT_Formula* a = ft_formula_from_json(context, "{\"op\":\"Constant\",\"value\":42,\"radix\":16}");
  FT_Formula* b = ft_formula_from_json(context, "{\"op\":\"Constant\",\"value\":42,\"radix\":10}");
  FT_Result* result = ft_verify_pair(context, a, b);
  assert(ft_result_status(result) == FT_STATUS_EXACT_EQUALITY);
  char* text = ft_result_to_json(result);
  assert(text != 0); ft_string_free(text);
  FT_Function* function = ft_result_theory_function(result);
  char* value = ft_function_evaluate_json(context, function, "{}");
  assert(value != 0); ft_string_free(value); ft_function_free(function);
  ft_result_free(result); ft_formula_free(a); ft_formula_free(b); ft_context_free(context);
  return 0;
}
