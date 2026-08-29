#include <cstddef>
#include <span>

void positive_clamp(std::span<const double> x, std::span<double> y,
                    std::size_t n) {
  for (std::size_t i = 0; i < n; ++i) {
    if (x[i] > 0.0) {
      y[i] = x[i];
    } else {
      y[i] = 0.0;
    }
  }
}
