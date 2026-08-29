#include "formulatracer.h"

#include <stdio.h>
#include <stdlib.h>

int main(void) {
  FT_Context *context = ft_context_create();
  if (!context || ft_abi_version() != FT_ABI_VERSION) return EXIT_FAILURE;
  FT_Formula *theory = ft_formula_from_json(context, "{\"op\":\"Constant\",\"value\":42,\"radix\":16}");
  FT_Formula *implementation = ft_formula_from_json(context, "{\"op\":\"Constant\",\"value\":42,\"radix\":10}");
  FT_Result *result = ft_verify_pair(context, theory, implementation);
  if (!result || ft_result_status(result) != FT_STATUS_EXACT_EQUALITY) return EXIT_FAILURE;
  char *json = ft_result_to_json(result);
  char *tex = ft_result_to_tex(result);
  puts(json); puts(tex);
  ft_string_free(json); ft_string_free(tex);
  ft_result_free(result); ft_formula_free(theory); ft_formula_free(implementation);
  ft_context_free(context);
  return EXIT_SUCCESS;
}
