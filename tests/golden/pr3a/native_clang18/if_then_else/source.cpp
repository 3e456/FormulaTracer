#include <cstddef>
#include <span>

void positive_part(
    std::span<const double> x,
    std::span<double> y) {
  for (std::size_t i = 0; i < x.size(); ++i) {
    if (x[i] > 0.0) {
      y[i] = x[i];
    } else {
      y[i] = 0.0;
    }
  }
}
