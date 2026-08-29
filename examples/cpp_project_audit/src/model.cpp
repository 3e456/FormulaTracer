#include "../include/model.hpp"
#include "../include/constants.hpp"

#include <numeric>

double calculate_total(std::span<const double> quantity,
                       std::span<const double> factor,
                       std::size_t inputs) {
  double total = 0.0;
  for (std::size_t i = 0; i < inputs; ++i) {
    total += quantity[i] * factor[i];
  }
  return total * TON_SCALE;
}

double reordered_total(std::span<const double> quantity,
                       std::span<const double> factor) {
  return std::reduce(quantity.begin(), quantity.end(), 0.0);
}
