#include "formulatracer.hpp"

#include <iostream>

int main() {
  formulatracer::Context context;
  auto theory = formulatracer::Formula::from_json(
      context, R"({"op":"Constant","value":42,"radix":16})");
  auto implementation = formulatracer::Formula::from_json(
      context, R"({"op":"Constant","value":42,"radix":10})");
  auto result = theory.verify_against(implementation);
  if (result.status() != FT_STATUS_EXACT_EQUALITY) return 1;
  std::cout << result.to_json() << '\n' << result.to_tex() << '\n';
  return 0;
}
