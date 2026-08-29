#pragma once

#include <span>

double calculate_total(std::span<const double> quantity,
                       std::span<const double> factor,
                       std::size_t inputs);
double reordered_total(std::span<const double> quantity,
                       std::span<const double> factor);
