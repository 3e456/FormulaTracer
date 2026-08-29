#include "../include/model.hpp"

#include <fstream>

int main() {
  double quantity[] = {1.0, 2.0};
  double factor[] = {3.0, 4.0};
  const double result = calculate_total(quantity, factor, 2);
  std::ofstream report("result.txt");
  report << result;
  return 0;
}
