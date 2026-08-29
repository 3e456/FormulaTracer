#include <cstddef>
#include <span>

double sum_values(std::span<const double> x, double init, std::size_t n) {
  double acc = init;
  for (std::size_t i = 0; i < n; ++i) {
    acc += x[i];
  }
  return acc;
}
