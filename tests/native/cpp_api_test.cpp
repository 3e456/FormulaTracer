#include "formulatracer.hpp"
#include <cassert>
#include <string>

int main() {
  FT_Context* raw_context = ft_context_create();
  char* raw_reconstruction = ft_kernel_execute_json(raw_context,
      R"({"schema_version":"1.0","kernel":"F","operation":"RECONSTRUCT","request":{"original_theory":{"op":"Constant","value":2},"reconstructed_theory":{"op":"Constant","value":2},"structural_facts":{},"temporaries":[],"safety":{},"relation_chain":[],"assumptions":[],"proof_obligations":[],"exact_egraph_verified":false}})" );
  assert(raw_reconstruction != nullptr);
  assert(std::string(raw_reconstruction).find("\"status\":\"EXACT\"") != std::string::npos);
  ft_string_free(raw_reconstruction); ft_context_free(raw_context);
  formulatracer::Context context;
  auto theory = formulatracer::Formula::from_json(context, R"({"op":"Constant","value":42,"radix":16})");
  auto implementation = formulatracer::Formula::from_json(context, R"({"op":"Constant","value":42,"radix":10})");
  auto result = theory.verify_against(implementation);
  assert(result.status() == FT_STATUS_EXACT_EQUALITY);
  assert(result.to_tex().find("FormulaTracer Verification Certificate") != std::string::npos);
  assert(result.assumptions_json() == "[]");
  assert(result.error_json() == "null");
  assert(result.range_json() == "null");
  assert(result.evidence_json().find("NATIVE_SEMANTIC_COMPARISON") != std::string::npos);
  auto theory_object = result.theory();
  auto implementation_object = result.implementation();
  assert(theory_object && implementation_object);
  assert(theory_object.to_tex() == "42");
  assert(implementation_object.to_json().find("semantic_hash") != std::string::npos);
  auto function = result.theory_function();
  assert(function.evaluate_json("{}") == "42");
  assert(function.inspect_json().find("variables") != std::string::npos);
  return 0;
}
