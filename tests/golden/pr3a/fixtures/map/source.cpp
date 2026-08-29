#include <cstddef>
#include <span>

void affine_map(std::span<const double> x, std::span<double> y,
                double a, double b, std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    y[i] = a * x[i] + b;
  }
}
