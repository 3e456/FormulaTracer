#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <span>
#include <string_view>
#include <vector>

void weighted_sum_loop(std::span<const double>, std::span<const double>,
                       std::span<double>, std::size_t, std::size_t);
void weighted_sum_inner_product(std::span<const double>, std::span<const double>,
                                std::span<double>, std::size_t, std::size_t);

namespace {
std::vector<double> human_reference(std::span<const double> quantity,
                                    std::span<const double> factor,
                                    std::size_t regions, std::size_t inputs) {
  std::vector<double> result(regions);
  for (std::size_t r = 0; r < regions; ++r)
    for (std::size_t i = 0; i < inputs; ++i)
      result[r] += quantity[r * inputs + i] * factor[i];
  return result;
}

void emit(std::string_view case_name, std::span<const double> quantity,
          std::span<const double> factor, std::size_t regions,
          std::size_t inputs) {
  std::vector<double> loop(regions), inner(regions);
  weighted_sum_loop(quantity, factor, loop, regions, inputs);
  weighted_sum_inner_product(quantity, factor, inner, regions, inputs);
  const auto expected = human_reference(quantity, factor, regions, inputs);
  for (std::size_t r = 0; r < regions; ++r) {
    const auto loop_bits = std::bit_cast<std::uint64_t>(loop[r]);
    const auto inner_bits = std::bit_cast<std::uint64_t>(inner[r]);
    const double absolute = std::abs(loop[r] - expected[r]);
    const double relative = expected[r] == 0.0 ? absolute : absolute / std::abs(expected[r]);
    std::cout << "{\"case\":\"" << case_name << "\",\"region\":" << r
              << ",\"loop\":" << std::setprecision(17) << loop[r]
              << ",\"inner_product\":" << inner[r]
              << ",\"human\":" << expected[r]
              << ",\"loop_bits\":\"0x" << std::hex << std::setw(16)
              << std::setfill('0') << loop_bits << "\",\"inner_bits\":\"0x"
              << std::setw(16) << inner_bits << std::dec << "\",\"absolute_difference\":"
              << absolute << ",\"relative_difference\":" << relative << "}\n";
    if (loop_bits != inner_bits || loop_bits != std::bit_cast<std::uint64_t>(expected[r]))
      std::exit(1);
  }
}
}  // namespace

int main() {
#if defined(__clang__)
  constexpr std::string_view compiler = "Clang";
  constexpr std::string_view compiler_version = __clang_version__;
#elif defined(__GNUC__)
  constexpr std::string_view compiler = "GCC";
  constexpr std::string_view compiler_version = __VERSION__;
#elif defined(_MSC_VER)
  constexpr std::string_view compiler = "MSVC";
  constexpr std::string_view compiler_version = "19.x";
#else
  constexpr std::string_view compiler = "unknown";
  constexpr std::string_view compiler_version = "unknown";
#endif
#if defined(__x86_64__) || defined(_M_X64)
  constexpr std::string_view target = "x86_64";
#elif defined(__aarch64__) || defined(_M_ARM64)
  constexpr std::string_view target = "aarch64";
#else
  constexpr std::string_view target = "unknown";
#endif
#if defined(NDEBUG)
  constexpr std::string_view optimization = "release-optimized";
#else
  constexpr std::string_view optimization = "debug-or-unoptimized";
#endif
  std::cout << "{\"metadata\":true,\"compiler\":\"" << compiler
            << "\",\"compiler_version\":\"" << compiler_version
            << "\",\"optimization\":\"" << optimization
            << "\",\"target\":\"" << target << "\"}\n";
  const std::vector<double> exact_quantity{1, 2, 3, 4, 5, 6};
  const std::vector<double> exact_factor{7, 8, 9};
  emit("exact", exact_quantity, exact_factor, 2, 3);

  std::uint32_t state = 0x5eed1234U;
  for (int test = 0; test < 32; ++test) {
    std::vector<double> quantity(20), factor(5);
    auto next = [&] { state = state * 1664525U + 1013904223U; return static_cast<double>(static_cast<int>(state % 33U) - 16); };
    for (auto& value : quantity) value = next();
    for (auto& value : factor) value = next();
    emit("generated", quantity, factor, 4, 5);
  }
}
