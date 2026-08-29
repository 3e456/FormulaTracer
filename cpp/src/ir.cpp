#include "cpp_audit/ir.hpp"

#include <cstdint>
#include <iomanip>
#include <sstream>

namespace cpp_audit {

std::string stable_id(std::string_view kind, std::string_view payload) {
  // Stable FNV-1a is used only as an identity fingerprint, not for security.
  std::uint64_t hash = 14695981039346656037ULL;
  for (const char value : payload) {
    hash ^= static_cast<unsigned char>(value);
    hash *= 1099511628211ULL;
  }
  std::ostringstream out;
  out << kind << '-' << std::hex << std::setfill('0') << std::setw(16) << hash;
  return out.str();
}

bool is_permitted_scientific_effect(Effect effect) noexcept {
  return effect == Effect::Pure || effect == Effect::ReadMemory ||
         effect == Effect::WriteMemory;
}

}  // namespace cpp_audit
