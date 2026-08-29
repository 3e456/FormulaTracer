#include <cstddef>
#include <numeric>
#include <span>

double unknown_external(double);
double inner_product(double);
void weighted_sum_loop(std::span<const double>, std::span<const double>,
                       std::span<double>, std::size_t, std::size_t);

void weighted_sum_unknown_external(std::span<const double> quantity,
                                   std::span<const double>,
                                   std::span<double> result,
                                   std::size_t, std::size_t) {
  result[0] = unknown_external(quantity[0]);
}

void weighted_sum_wrong_overload(std::span<const double> quantity,
                                 std::span<const double>,
                                 std::span<double> result,
                                 std::size_t, std::size_t) {
  result[0] = inner_product(quantity[0]);
}

void weighted_sum_narrowing(std::span<const double> quantity,
                            std::span<const double> factor,
                            std::span<double> result,
                            std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) {
    float acc = 0.0;
    for (std::size_t i = 0; i < inputs; ++i)
      acc += quantity[r * inputs + i] * factor[i];
    result[r] = acc;
  }
}

void weighted_sum_obvious_alias(std::span<double> buffer,
                                std::span<const double> factor) {
  weighted_sum_loop(buffer, factor, buffer, 1, factor.size());
}

void weighted_sum_short_bound(std::span<const double> quantity, std::span<const double> factor,
                              std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0;
    for (std::size_t i = 0; i < inputs - 1; ++i) acc += quantity[r * inputs + i] * factor[i];
    result[r] = acc; }
}

void weighted_sum_inclusive_bound(std::span<const double> quantity, std::span<const double> factor,
                                  std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0;
    for (std::size_t i = 0; i <= inputs; ++i) acc += quantity[r * inputs + i] * factor[i];
    result[r] = acc; }
}

void weighted_sum_factor_r(std::span<const double> quantity, std::span<const double> factor,
                           std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0;
    for (std::size_t i = 0; i < inputs; ++i) acc += quantity[r * inputs + i] * factor[r];
    result[r] = acc; }
}

void weighted_sum_transposed(std::span<const double> quantity, std::span<const double> factor,
                             std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0;
    for (std::size_t i = 0; i < inputs; ++i) acc += quantity[i * regions + r] * factor[i];
    result[r] = acc; }
}

void weighted_sum_initial_one(std::span<const double> quantity, std::span<const double> factor,
                              std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 1.0;
    for (std::size_t i = 0; i < inputs; ++i) acc += quantity[r * inputs + i] * factor[i];
    result[r] = acc; }
}

void weighted_sum_addition(std::span<const double> quantity, std::span<const double> factor,
                           std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0;
    for (std::size_t i = 0; i < inputs; ++i) acc += quantity[r * inputs + i] + factor[i];
    result[r] = acc; }
}

void weighted_sum_result_i(std::span<const double> quantity, std::span<const double> factor,
                           std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0; std::size_t i = 0;
    for (; i < inputs; ++i) acc += quantity[r * inputs + i] * factor[i];
    result[i] = acc; }
}

void weighted_sum_store_inside(std::span<const double> quantity, std::span<const double> factor,
                               std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { double acc = 0.0;
    for (std::size_t i = 0; i < inputs; ++i) { acc += quantity[r * inputs + i] * factor[i]; result[r] = acc; } }
}

void weighted_sum_reduce(std::span<const double> quantity, std::span<const double>,
                         std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { auto first = quantity.begin() + r * inputs;
    result[r] = std::reduce(first, first + inputs, 0.0); }
}

void weighted_sum_invalid_end(std::span<const double> quantity, std::span<const double> factor,
                              std::span<double> result, std::size_t regions, std::size_t inputs) {
  for (std::size_t r = 0; r < regions; ++r) { auto first = quantity.begin() + r * inputs;
    result[r] = std::inner_product(first, first + inputs + 1, factor.begin(), 0.0); }
}
