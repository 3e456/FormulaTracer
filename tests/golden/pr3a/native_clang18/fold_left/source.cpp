#include <cstddef>
#include <span>

double sum_values(std::span<const double> x) {
  double acc = 2.0;
  for (std::size_t i = 0; i < x.size(); ++i) {
    acc += x[i];
  }
  return acc;
}
