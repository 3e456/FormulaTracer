#include "cpp_audit/ir.hpp"

#include <cassert>

int main() {
  const auto first = cpp_audit::stable_id("op", "multiply");
  assert(first == cpp_audit::stable_id("op", "multiply"));
  assert(first != cpp_audit::stable_id("op", "add"));
  assert(cpp_audit::is_permitted_scientific_effect(cpp_audit::Effect::Pure));
  assert(!cpp_audit::is_permitted_scientific_effect(cpp_audit::Effect::Unknown));
  cpp_audit::DependencyEdge edge;
  edge.kind = cpp_audit::DependencyEdgeKind::ValueDependsOn;
  edge.confidence = cpp_audit::DependencyConfidence::Resolved;
  edge.source_node_id = "load-x";
  edge.target_node_id = "multiply";
  assert(edge.source_node_id != edge.target_node_id);
}
