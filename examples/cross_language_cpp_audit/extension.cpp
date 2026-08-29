#include <pybind11/pybind11.h>

double scale(double value, double factor) {
  return value * factor;
}

PYBIND11_MODULE(local_cpp, module) {
  module.def("scale", &scale);
}
