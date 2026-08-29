#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace cpp_audit {

enum class Effect { Pure, ReadMemory, WriteMemory, Allocate, Deallocate, Throw,
                    IO, FileSystem, Clock, Random, Thread, Atomic, Synchronize,
                    Environment, Unknown };

struct SourceSpan {
  std::string file;
  unsigned begin_line{};
  unsigned begin_column{};
  unsigned end_line{};
  unsigned end_column{};
};

struct ValueNode {
  std::string id;
  std::string kind;
  std::string cpp_type;
  SourceSpan source_span;
};

struct OperationNode {
  std::string id;
  std::string kind;
  Effect effect{Effect::Unknown};
  SourceSpan source_span;
};

enum class DependencyEdgeKind {
  Defines, Reads, Writes, ValueDependsOn, IndexDependsOn,
  ConditionDependsOn, LoopBoundDependsOn, PreviousAccumulatorValue,
  ControlGuards, ResultOf
};

enum class DependencyConfidence { Resolved, Unresolved };

struct DependencyEdge {
  std::string id;
  DependencyEdgeKind kind{DependencyEdgeKind::ValueDependsOn};
  std::string source_node_id;
  std::string target_node_id;
  std::string argument_role;
  SourceSpan source_span;
  DependencyConfidence confidence{DependencyConfidence::Unresolved};
  std::string derivation;
};

struct ImplementationIR {
  std::string schema_version{"0.1"};
  std::string standard_version;
  std::string function_name;
  std::vector<ValueNode> values;
  std::vector<OperationNode> operations;
  std::vector<DependencyEdge> dependency_edges;
};

[[nodiscard]] std::string stable_id(std::string_view kind,
                                    std::string_view canonical_payload);
[[nodiscard]] bool is_permitted_scientific_effect(Effect effect) noexcept;

}  // namespace cpp_audit
