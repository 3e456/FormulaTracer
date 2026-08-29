#ifndef FORMULATRACER_HPP
#define FORMULATRACER_HPP

#include "formulatracer.h"
#include <stdexcept>
#include <string>
#include <utility>

namespace formulatracer {

class Context {
 public:
  Context() : handle_(ft_context_create()) { if (!handle_) throw std::runtime_error("ft_context_create failed"); }
  ~Context() { ft_context_free(handle_); }
  Context(const Context&) = delete;
  Context& operator=(const Context&) = delete;
  Context(Context&& other) noexcept : handle_(std::exchange(other.handle_, nullptr)) {}
  FT_Context* get() const noexcept { return handle_; }
 private: FT_Context* handle_;
};

inline std::string take_string(char* value) {
  if (!value) return {};
  std::string result(value); ft_string_free(value); return result;
}

class MathematicalFunction {
 public:
  MathematicalFunction(Context& context, FT_Function* value) : context_(context), handle_(value) {
    if (!handle_) throw std::runtime_error("MathematicalFunction construction failed");
  }
  ~MathematicalFunction() { ft_function_free(handle_); }
  MathematicalFunction(const MathematicalFunction&) = delete;
  MathematicalFunction& operator=(const MathematicalFunction&) = delete;
  MathematicalFunction(MathematicalFunction&& other) noexcept : context_(other.context_), handle_(std::exchange(other.handle_, nullptr)) {}
  std::string evaluate_json(const std::string& inputs_json) const {
    char* value = ft_function_evaluate_json(context_.get(), handle_, inputs_json.c_str());
    if (!value) throw std::runtime_error(take_string(ft_context_last_error(context_.get())));
    return take_string(value);
  }
  MathematicalFunction substitute_json(const std::string& values_json) const {
    return MathematicalFunction(context_, ft_function_substitute_json(context_.get(), handle_, values_json.c_str()));
  }
  std::string to_json() const { return take_string(ft_function_to_json(handle_)); }
  std::string to_tex() const { return take_string(ft_function_to_tex(handle_)); }
  std::string inspect_json() const { return take_string(ft_function_inspect_json(handle_)); }
 private:
  Context& context_; FT_Function* handle_;
};

class SemanticObject {
 public:
  explicit SemanticObject(FT_SemanticObject* value = nullptr) : handle_(value) {}
  ~SemanticObject() { ft_semantic_object_free(handle_); }
  SemanticObject(const SemanticObject&) = delete;
  SemanticObject& operator=(const SemanticObject&) = delete;
  SemanticObject(SemanticObject&& other) noexcept : handle_(std::exchange(other.handle_, nullptr)) {}
  SemanticObject& operator=(SemanticObject&& other) noexcept { if (this != &other) { ft_semantic_object_free(handle_); handle_ = std::exchange(other.handle_, nullptr); } return *this; }
  explicit operator bool() const noexcept { return handle_ != nullptr; }
  std::string to_json() const { return take_string(ft_semantic_object_to_json(handle_)); }
  std::string to_tex() const { return take_string(ft_semantic_object_to_tex(handle_)); }
 private: FT_SemanticObject* handle_;
};

class Result {
 public:
  explicit Result(Context& context, FT_Result* value = nullptr) : context_(context), handle_(value) {}
  ~Result() { ft_result_free(handle_); }
  Result(const Result&) = delete;
  Result& operator=(const Result&) = delete;
  Result(Result&& other) noexcept : context_(other.context_), handle_(std::exchange(other.handle_, nullptr)) {}
  Result& operator=(Result&& other) noexcept { if (this != &other) { ft_result_free(handle_); handle_ = std::exchange(other.handle_, nullptr); } return *this; }
  FT_Status status() const noexcept { return ft_result_status(handle_); }
  std::string to_json() const { return take_string(ft_result_to_json(handle_)); }
  std::string to_tex() const { return take_string(ft_result_to_tex(handle_)); }
  std::string diagnostics_json() const { return take_string(ft_result_diagnostics_json(handle_)); }
  std::string assumptions_json() const { return take_string(ft_result_assumptions_json(handle_)); }
  std::string evidence_json() const { return take_string(ft_result_evidence_json(handle_)); }
  std::string error_json() const { return take_string(ft_result_error_json(handle_)); }
  std::string range_json() const { return take_string(ft_result_range_json(handle_)); }
  SemanticObject theory() const { return SemanticObject(ft_result_theory(handle_)); }
  SemanticObject implementation() const { return SemanticObject(ft_result_implementation(handle_)); }
  MathematicalFunction theory_function() const { return MathematicalFunction(context_, ft_result_theory_function(handle_)); }
  MathematicalFunction implementation_function() const { return MathematicalFunction(context_, ft_result_implementation_function(handle_)); }
  MathematicalFunction error_function() const { return MathematicalFunction(context_, ft_result_error_function(handle_)); }
  MathematicalFunction range_lower_function() const { return MathematicalFunction(context_, ft_result_range_lower_function(handle_)); }
  MathematicalFunction range_upper_function() const { return MathematicalFunction(context_, ft_result_range_upper_function(handle_)); }
 private: Context& context_; FT_Result* handle_;
};

class Formula {
 public:
  static Formula from_tex(Context& context, const std::string& tex) { return Formula(context, ft_formula_from_tex(context.get(), tex.c_str())); }
  static Formula from_json(Context& context, const std::string& json) { return Formula(context, ft_formula_from_json(context.get(), json.c_str())); }
  ~Formula() { ft_formula_free(handle_); }
  Formula(const Formula&) = delete;
  Formula& operator=(const Formula&) = delete;
  Formula(Formula&& other) noexcept : context_(other.context_), handle_(std::exchange(other.handle_, nullptr)) {}
  Result verify() const { return Result(context_, ft_verify(context_.get(), handle_)); }
  Result verify_against(const Formula& implementation) const { return Result(context_, ft_verify_pair(context_.get(), handle_, implementation.handle_)); }
 private:
  Formula(Context& context, FT_Formula* handle) : context_(context), handle_(handle) { if (!handle_) throw std::runtime_error("Formula construction failed"); }
  Context& context_; FT_Formula* handle_;
};
}  // namespace formulatracer
#endif
