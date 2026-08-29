#include <cstddef>
#include <span>

void affine_map(
    std::span<const double> x,
    std::span<double> y,
    double a,
    double b) {
  for (std::size_t i = 0; i < x.size(); ++i) {
    y[i] = a * x[i] + b;
  }
}
