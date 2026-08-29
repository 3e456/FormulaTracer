#include <cstddef>
#include <span>

void weighted_sum_loop(std::span<const double> quantity,
                       std::span<const double> factor,
                       std::span<double> result,
                       std::size_t regions,
                       std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) {
    double acc = 0.0;
    for (std::size_t i = 0; i < inputs; ++i) {
      acc += quantity[r * inputs + i] * factor[i];
    }
    result[r] = acc;
  }
}
