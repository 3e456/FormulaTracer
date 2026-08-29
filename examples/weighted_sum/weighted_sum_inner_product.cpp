#include <cstddef>
#include <numeric>
#include <span>

void weighted_sum_inner_product(std::span<const double> quantity,
                  std::span<const double> factor,
                  std::span<double> result,
                  std::size_t regions,
                  std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) {
    auto first = quantity.begin() + r * inputs;
    result[r] = std::inner_product(first, first + inputs, factor.begin(), 0.0);
  }
}
