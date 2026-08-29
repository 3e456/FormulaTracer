#include "cpp_audit/ir.hpp"

#include <clang/AST/ASTContext.h>
#include <clang/AST/ASTTypeTraits.h>
#include <clang/AST/Decl.h>
#include <clang/AST/Expr.h>
#include <clang/AST/ParentMapContext.h>
#include <clang/AST/RecursiveASTVisitor.h>
#include <clang/AST/Stmt.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Basic/Version.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Lex/Lexer.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/CompilationDatabase.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/ADT/StringExtras.h>
#include <llvm/Support/CommandLine.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/Path.h>
#include <llvm/Support/SHA256.h>
#include <llvm/Support/raw_ostream.h>

#include <algorithm>
#include <fstream>
#include <iterator>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace {

llvm::cl::OptionCategory category("cpp-audit Clang frontend options");
llvm::cl::opt<std::string> target_function(
    "function", llvm::cl::desc("Exact function name to extract"),
    llvm::cl::Required, llvm::cl::cat(category));

std::string source_hash(const std::string& path) {
  std::ifstream input(path, std::ios::binary);
  const std::string bytes((std::istreambuf_iterator<char>(input)), {});
  llvm::SHA256 sha;
  sha.update(llvm::StringRef(bytes));
  return llvm::toHex(sha.final(), true);
}

std::string join_command(const clang::tooling::CompileCommand& command) {
  std::string result;
  for (const auto& argument : command.CommandLine) {
    if (!result.empty()) result.push_back(' ');
    const bool quote = argument.find(' ') != std::string::npos;
    if (quote) result.push_back('"');
    result += argument;
    if (quote) result.push_back('"');
  }
  return result;
}

std::string normalize_standard_symbol(std::string name) {
  const bool standard = name.starts_with("std::");
  if (standard && name.find("inner_product") != std::string::npos) return "std::inner_product";
  if (standard && name.find("reduce") != std::string::npos) return "std::reduce";
  if (standard && name.find("accumulate") != std::string::npos) return "std::accumulate";
  if (standard && name.find("transform") != std::string::npos) return "std::transform";
  if (standard && name.find("sqrt") != std::string::npos) return "std::sqrt";
  if (standard && name.find("abs") != std::string::npos) return "std::abs";
  if (standard && name.find("span") != std::string::npos && name.ends_with("::begin")) return "std::span::begin";
  if (standard && name.find("span") != std::string::npos && name.ends_with("::size")) return "std::span::size";
  if (standard && name.find("span") != std::string::npos && name.find("operator[]") != std::string::npos)
    return "std::span::operator[]";
  return name;
}

class AuditVisitor final : public clang::RecursiveASTVisitor<AuditVisitor> {
 public:
  AuditVisitor(clang::ASTContext& context, clang::FunctionDecl& function)
      : context_(context), source_manager_(context.getSourceManager()),
        lang_(context.getLangOpts()), function_(function) {
    analysis_["alias_class"] = "named_contract:non_aliasing_spans";
  }

  void run() {
    add_decl_node("FunctionDecl", function_, "Pure",
                  function_.getQualifiedNameAsString());
    for (auto* parameter : function_.parameters()) {
      add_decl_node("ParmVarDecl", *parameter, "ReadMemory",
                    parameter->getQualifiedNameAsString());
    }
    TraverseStmt(function_.getBody());
    finish_analysis();
  }

  llvm::json::Array take_nodes() { return std::move(nodes_); }
  llvm::json::Array take_edges() { return std::move(edges_); }
  llvm::json::Object take_analysis() { return std::move(analysis_); }
  llvm::json::Array take_entities() {
    std::sort(used_entities_.begin(), used_entities_.end());
    used_entities_.erase(std::unique(used_entities_.begin(), used_entities_.end()),
                         used_entities_.end());
    llvm::json::Array result;
    for (const auto& item : used_entities_) result.push_back(item);
    return result;
  }
  llvm::json::Array take_diagnostics() { return std::move(diagnostics_); }

  bool VisitVarDecl(clang::VarDecl* declaration) {
    if (llvm::isa<clang::ParmVarDecl>(declaration)) {
      if (declaration->getDeclContext() != &function_)
        add_decl_node("ParmVarDecl", *declaration, "Pure", declaration->getQualifiedNameAsString());
      return true;
    }
    add_decl_node("VarDecl", *declaration, "Pure",
                  declaration->getQualifiedNameAsString());
    const auto name = declaration->getNameAsString();
    if (declaration->hasInit()) {
      const auto initial = text(declaration->getInit()->getSourceRange());
      if (name == "acc") analysis_["accumulator_initial"] = initial;
      if (name == "first") analysis_["row_begin"] = initial;
      add_expr_edge(*declaration->getInit(), decl_id(*declaration), "DEFINES", "initial_value");
    }
    return true;
  }

  bool VisitForStmt(clang::ForStmt* statement) {
    LoopFact fact;
    if (const auto* declaration_stmt =
            llvm::dyn_cast_or_null<clang::DeclStmt>(statement->getInit())) {
      if (declaration_stmt->isSingleDecl()) {
        if (const auto* variable =
                llvm::dyn_cast<clang::VarDecl>(declaration_stmt->getSingleDecl()))
          fact.index = variable->getNameAsString();
      }
    }
    if (const auto* condition =
            llvm::dyn_cast_or_null<clang::BinaryOperator>(statement->getCond())) {
      fact.operation = condition->getOpcodeStr().str();
      fact.bound = text(condition->getRHS()->getSourceRange());
    }
    std::vector<std::pair<std::string, std::string>> attributes{
        {"semantic_kind", "Loop"}, {"index", fact.index}, {"lower", "0"},
        {"upper", fact.bound}, {"comparison", fact.operation}};
    add_stmt_node("ForStmt", *statement, "Pure", std::move(attributes));
    const auto loop_id = id("ForStmt", statement->getSourceRange());
    if (const auto* declaration_stmt = llvm::dyn_cast_or_null<clang::DeclStmt>(statement->getInit())) {
      if (declaration_stmt->isSingleDecl()) {
        if (const auto* variable = llvm::dyn_cast<clang::VarDecl>(declaration_stmt->getSingleDecl())) {
          add_edge(decl_id(*variable), loop_id, "LOOP_BOUND_DEPENDS_ON", "index");
          if (variable->hasInit()) add_expr_edge(*variable->getInit(), loop_id, "LOOP_BOUND_DEPENDS_ON", "lower");
        }
      }
    }
    if (const auto* condition = llvm::dyn_cast_or_null<clang::BinaryOperator>(statement->getCond()))
      add_expr_edge(*condition->getRHS(), loop_id, "LOOP_BOUND_DEPENDS_ON", "upper");
    loops_.push_back(std::move(fact));
    return true;
  }

  bool VisitIfStmt(clang::IfStmt* statement) {
    add_stmt_node("IfStmt", *statement, "Pure", {{"semantic_kind", "Conditional"}});
    add_expr_edge(*statement->getCond(), id("IfStmt", statement->getSourceRange()),
                  "CONDITION_DEPENDS_ON", "condition");
    return true;
  }

  bool VisitReturnStmt(clang::ReturnStmt* statement) {
    if (inside_lambda(*statement)) return true;
    add_stmt_node("ReturnStmt", *statement, "Pure", {{"semantic_kind", "Return"}});
    if (statement->getRetValue())
      add_expr_edge(*statement->getRetValue(), id("ReturnStmt", statement->getSourceRange()),
                    "RESULT_OF", "return_value");
    return true;
  }

  bool VisitLambdaExpr(clang::LambdaExpr* expression) {
    add_expr_node("LambdaExpr", *expression, "Pure",
                  {{"semantic_kind", "FunctionValue"}});
    const auto target = id("LambdaExpr", expression->getSourceRange());
    if (const auto* body = expression->getCompoundStmtBody())
      for (const auto* child : body->body())
        if (const auto* returned = llvm::dyn_cast<clang::ReturnStmt>(child))
          if (returned->getRetValue()) add_expr_edge(*returned->getRetValue(), target, "RESULT_OF", "body");
    return true;
  }

  bool VisitBinaryOperator(clang::BinaryOperator* expression) {
    const bool assignment = expression->isAssignmentOp();
    std::vector<std::pair<std::string, std::string>> attributes{
        {"operator", expression->getOpcodeStr().str()},
        {"semantic_kind", assignment ? "Assignment" :
            (expression->isComparisonOp() ? "Comparison" : "BinaryOperation")},
        {"lhs_text", text(expression->getLHS()->getSourceRange())},
        {"rhs_text", text(expression->getRHS()->getSourceRange())}};
    if (assignment) append_store_attributes(*expression, attributes);
    add_expr_node("BinaryOperator", *expression,
                  assignment ? "WriteMemory" : "Pure",
                  std::move(attributes));
    const auto target = id("BinaryOperator", expression->getSourceRange());
    add_expr_edge(*expression->getLHS(), target, assignment ? "WRITES" : "VALUE_DEPENDS_ON", "lhs");
    add_expr_edge(*expression->getRHS(), target, "VALUE_DEPENDS_ON", assignment ? "value" : "rhs");
    add_control_edges(*expression, target);
    if (assignment) {
      const auto* lhs = expression->getLHS()->IgnoreParenImpCasts();
      if (const auto* ref = llvm::dyn_cast<clang::DeclRefExpr>(lhs))
        if (const auto* variable = llvm::dyn_cast<clang::VarDecl>(ref->getDecl())) {
          if (!llvm::isa<clang::ParmVarDecl>(variable)) {
            add_edge(target, decl_id(*variable), "DEFINES", "assigned_value");
            if (const auto* operation = llvm::dyn_cast<clang::BinaryOperator>(expression->getRHS()->IgnoreParenImpCasts()))
              for (const clang::Expr* operand : {operation->getLHS(), operation->getRHS()})
                if (const auto* previous = llvm::dyn_cast<clang::DeclRefExpr>(operand->IgnoreParenImpCasts()))
                  if (previous->getDecl()->getCanonicalDecl() == variable->getCanonicalDecl())
                    add_expr_edge(*operand, target, "PREVIOUS_ACCUMULATOR_VALUE", "accumulator");
          }
        }
    }
    if (assignment) inspect_store(*expression);
    return true;
  }

  bool VisitCompoundAssignOperator(clang::CompoundAssignOperator* expression) {
    add_expr_node("CompoundAssignOperator", *expression, "WriteMemory",
                  {{"operator", expression->getOpcodeStr().str()},
                   {"semantic_kind", "Assignment"},
                   {"lhs_text", text(expression->getLHS()->getSourceRange())},
                   {"rhs_text", text(expression->getRHS()->getSourceRange())}});
    const auto target = id("CompoundAssignOperator", expression->getSourceRange());
    add_expr_edge(*expression->getLHS(), target, "PREVIOUS_ACCUMULATOR_VALUE", "accumulator");
    add_expr_edge(*expression->getRHS(), target, "VALUE_DEPENDS_ON", "value");
    add_control_edges(*expression, target);
    const auto* lhs = expression->getLHS()->IgnoreParenImpCasts();
    if (const auto* ref = llvm::dyn_cast<clang::DeclRefExpr>(lhs))
      if (const auto* variable = llvm::dyn_cast<clang::VarDecl>(ref->getDecl()))
        if (!llvm::isa<clang::ParmVarDecl>(variable))
          add_edge(target, decl_id(*variable), "DEFINES", "assigned_value");
    if (expression->getOpcode() == clang::BO_AddAssign)
      analysis_["reduction_operation"] = "Add";
    const auto* rhs = expression->getRHS()->IgnoreParenImpCasts();
    if (const auto* binary = llvm::dyn_cast<clang::BinaryOperator>(rhs)) {
      analysis_["transform_operation"] =
          binary->getOpcode() == clang::BO_Mul ? "Multiply" :
          binary->getOpcode() == clang::BO_Add ? "Add" : "Unsupported";
      inspect_subscripts(*binary);
    }
    return true;
  }

  bool VisitArraySubscriptExpr(clang::ArraySubscriptExpr* expression) {
    add_expr_node("ArraySubscriptExpr", *expression, "ReadMemory",
                  {{"index", text(expression->getIdx()->getSourceRange())},
                   {"semantic_kind", "Load"},
                   {"base", text(expression->getBase()->getSourceRange())}});
    const auto target = id("ArraySubscriptExpr", expression->getSourceRange());
    add_expr_edge(*expression->getBase(), target, "READS", "base");
    add_expr_edge(*expression->getIdx(), target, "INDEX_DEPENDS_ON", "index");
    return true;
  }

  bool VisitCXXOperatorCallExpr(clang::CXXOperatorCallExpr* expression) {
    inspect_call(*expression, "CXXOperatorCallExpr");
    return true;
  }

  bool VisitCallExpr(clang::CallExpr* expression) {
    if (llvm::isa<clang::CXXOperatorCallExpr>(expression) ||
        llvm::isa<clang::CXXMemberCallExpr>(expression)) return true;
    inspect_call(*expression, "CallExpr");
    return true;
  }

  bool VisitCXXMemberCallExpr(clang::CXXMemberCallExpr* expression) {
    inspect_call(*expression, "CXXMemberCallExpr");
    return true;
  }

  bool VisitImplicitCastExpr(clang::ImplicitCastExpr* expression) {
    const bool narrowing = expression->getType()->isSpecificBuiltinType(clang::BuiltinType::Float) &&
                           expression->getSubExpr()->getType()->isSpecificBuiltinType(clang::BuiltinType::Double);
    add_expr_node("ImplicitCast", *expression, narrowing ? "Unknown" : "Pure",
                  {{"cast_kind", expression->getCastKindName()}, {"semantic_kind", "Cast"}});
    add_expr_edge(*expression->getSubExpr(), id("ImplicitCast", expression->getSourceRange()),
                  "VALUE_DEPENDS_ON", "operand");
    if (narrowing) {
      diagnostic("UNKNOWN_IMPLICIT_CAST", "implicit double-to-float narrowing", *expression);
    }
    return true;
  }

  bool VisitDeclRefExpr(clang::DeclRefExpr* expression) {
    const auto* declaration = llvm::cast<clang::ValueDecl>(
        expression->getDecl()->getCanonicalDecl());
    add_expr_node("DeclRefExpr", *expression, "Pure",
                  {{"resolved_symbol", declaration->getQualifiedNameAsString()},
                   {"semantic_kind", "Load"}, {"name", declaration->getNameAsString()}});
    if (const auto* referenced = llvm::dyn_cast<clang::VarDecl>(expression->getDecl()))
      add_edge(decl_id(*referenced), id("DeclRefExpr", expression->getSourceRange()),
               "READS", "value");
    return true;
  }

  bool VisitIntegerLiteral(clang::IntegerLiteral* expression) {
    add_expr_node("IntegerLiteral", *expression, "Pure",
                  {{"semantic_kind", "Literal"}, {"value", text(expression->getSourceRange())}});
    return true;
  }
  bool VisitFloatingLiteral(clang::FloatingLiteral* expression) {
    add_expr_node("FloatingLiteral", *expression, "Pure",
                  {{"semantic_kind", "Literal"}, {"value", text(expression->getSourceRange())}});
    return true;
  }
  bool VisitUnaryOperator(clang::UnaryOperator* expression) {
    const bool mutating = expression->isIncrementDecrementOp();
    add_expr_node("UnaryOperator", *expression, mutating ? "WriteMemory" : "Pure",
                  {{"operator", clang::UnaryOperator::getOpcodeStr(expression->getOpcode()).str()},
                   {"semantic_kind", "UnaryOperation"}});
    add_expr_edge(*expression->getSubExpr(), id("UnaryOperator", expression->getSourceRange()),
                  "VALUE_DEPENDS_ON", "operand");
    return true;
  }

 private:
  struct LoopFact { std::string index, bound, operation; };

  std::string text(clang::SourceRange range) const {
    if (range.isInvalid()) return {};
    return clang::Lexer::getSourceText(
               clang::CharSourceRange::getTokenRange(range), source_manager_, lang_)
        .str();
  }

  llvm::json::Object span(clang::SourceRange range) {
    llvm::json::Object object;
    const auto begin = source_manager_.getPresumedLoc(range.getBegin());
    const auto end = source_manager_.getPresumedLoc(range.getEnd());
    if (begin.isInvalid() || end.isInvalid()) return object;
    object["file"] = std::string(begin.getFilename());
    object["begin_line"] = static_cast<std::int64_t>(begin.getLine());
    object["begin_column"] = static_cast<std::int64_t>(begin.getColumn());
    object["end_line"] = static_cast<std::int64_t>(end.getLine());
    object["end_column"] = static_cast<std::int64_t>(end.getColumn());
    return object;
  }

  std::string id(llvm::StringRef kind, clang::SourceRange range) const {
    const auto begin = source_manager_.getFileOffset(range.getBegin());
    return cpp_audit::stable_id(kind.str(), function_.getQualifiedNameAsString() +
        "|" + std::to_string(begin) + "|" + text(range));
  }

  std::string decl_id(const clang::ValueDecl& declaration) const {
    return id(llvm::isa<clang::ParmVarDecl>(declaration) ? "ParmVarDecl" : "VarDecl",
              declaration.getSourceRange());
  }

  std::string expr_kind(const clang::Expr& raw) const {
    const auto* expression = raw.IgnoreParens();
    if (llvm::isa<clang::CompoundAssignOperator>(expression)) return "CompoundAssignOperator";
    if (llvm::isa<clang::BinaryOperator>(expression)) return "BinaryOperator";
    if (llvm::isa<clang::CXXOperatorCallExpr>(expression)) return "CXXOperatorCallExpr";
    if (llvm::isa<clang::CXXMemberCallExpr>(expression)) return "CXXMemberCallExpr";
    if (llvm::isa<clang::CallExpr>(expression)) return "CallExpr";
    if (llvm::isa<clang::ImplicitCastExpr>(expression)) return "ImplicitCast";
    if (llvm::isa<clang::DeclRefExpr>(expression)) return "DeclRefExpr";
    if (llvm::isa<clang::IntegerLiteral>(expression)) return "IntegerLiteral";
    if (llvm::isa<clang::FloatingLiteral>(expression)) return "FloatingLiteral";
    if (llvm::isa<clang::UnaryOperator>(expression)) return "UnaryOperator";
    if (llvm::isa<clang::ArraySubscriptExpr>(expression)) return "ArraySubscriptExpr";
    if (llvm::isa<clang::LambdaExpr>(expression)) return "LambdaExpr";
    return {};
  }

  void add_edge(std::string source, std::string target, llvm::StringRef kind,
                llvm::StringRef role) {
    if (source.empty() || target.empty()) return;
    llvm::json::Object edge;
    const auto payload = source + "|" + target + "|" + kind.str() + "|" + role.str();
    edge["edge_id"] = cpp_audit::stable_id("edge", payload);
    edge["kind"] = kind.str(); edge["source_node_id"] = std::move(source);
    edge["target_node_id"] = std::move(target); edge["argument_role"] = role.str();
    edge["source_span"] = span(function_.getSourceRange());
    edge["confidence"] = "RESOLVED"; edge["derivation"] = "clang_ast";
    edges_.push_back(std::move(edge));
  }

  void add_expr_edge(const clang::Expr& expression, const std::string& target,
                     llvm::StringRef kind, llvm::StringRef role) {
    const auto node_kind = expr_kind(expression);
    if (!node_kind.empty()) add_edge(id(node_kind, expression.IgnoreParens()->getSourceRange()), target, kind, role);
  }

  llvm::json::Object base_node(llvm::StringRef kind, clang::SourceRange range,
                               llvm::StringRef effect) {
    llvm::json::Object node;
    node["id"] = id(kind, range);
    node["kind"] = kind.str();
    node["source_span"] = span(range);
    node["effect"] = effect.str();
    node["attributes"] = llvm::json::Object();
    return node;
  }

  void add_decl_node(llvm::StringRef kind, const clang::ValueDecl& declaration,
                     llvm::StringRef effect, std::string symbol) {
    auto node = base_node(kind, declaration.getSourceRange(), effect);
    const auto type = declaration.getType().getAsString();
    node["cpp_type"] = type;
    node["value_category"] = "declaration";
    node["constness"] = declaration.getType().isConstQualified() ||
                                type.find("span<const") != std::string::npos
                            ? "const" : "mutable";
    node["resolved_symbol"] = std::move(symbol);
    llvm::json::Object attributes;
    attributes["semantic_kind"] = llvm::isa<clang::ParmVarDecl>(declaration) ?
                                    "FunctionParameter" : "LocalVariable";
    attributes["name"] = declaration.getNameAsString();
    if (const auto* variable = llvm::dyn_cast<clang::VarDecl>(&declaration))
      if (variable->hasInit()) attributes["initializer_text"] = text(variable->getInit()->getSourceRange());
    node["attributes"] = std::move(attributes);
    nodes_.push_back(std::move(node));
  }

  void add_stmt_node(llvm::StringRef kind, const clang::Stmt& statement,
                     llvm::StringRef effect,
                     std::vector<std::pair<std::string, std::string>> attributes = {}) {
    auto node = base_node(kind, statement.getSourceRange(), effect);
    node["cpp_type"] = "void";
    node["value_category"] = "statement";
    node["constness"] = "not_applicable";
    node["resolved_symbol"] = "";
    llvm::json::Object values;
    for (auto& [key, value] : attributes) values[key] = std::move(value);
    node["attributes"] = std::move(values);
    nodes_.push_back(std::move(node));
  }

  void add_expr_node(llvm::StringRef kind, const clang::Expr& expression,
                     llvm::StringRef effect,
                     std::vector<std::pair<std::string, std::string>> attributes = {}) {
    auto node = base_node(kind, expression.getSourceRange(), effect);
    node["cpp_type"] = expression.getType().getAsString();
    node["value_category"] = expression.isLValue() ? "lvalue" :
                              expression.isXValue() ? "xvalue" : "prvalue";
    node["constness"] = expression.getType().isConstQualified() ? "const" : "mutable";
    std::string resolved_symbol;
    llvm::json::Object values;
    for (auto& [key, value] : attributes) {
      if (key == "resolved_symbol") resolved_symbol = value;
      values[key] = std::move(value);
    }
    node["resolved_symbol"] = std::move(resolved_symbol);
    node["attributes"] = std::move(values);
    nodes_.push_back(std::move(node));
  }

  void diagnostic(llvm::StringRef code, llvm::StringRef message,
                  const clang::Stmt& statement) {
    llvm::json::Object item;
    item["code"] = code.str(); item["message"] = message.str();
    item["specification"] = "resolved supported C++ subset";
    item["implementation"] = text(statement.getSourceRange());
    if (const auto* expression = llvm::dyn_cast<clang::Expr>(&statement)) {
      const auto kind = expr_kind(*expression);
      if (!kind.empty()) item["node_id"] = id(kind, expression->IgnoreParens()->getSourceRange());
    }
    const auto location = source_manager_.getPresumedLoc(statement.getBeginLoc());
    item["source"] = location.isValid() ?
        std::string(location.getFilename()) + ":" + std::to_string(location.getLine()) : "<unknown>";
    diagnostics_.push_back(std::move(item));
  }

  void inspect_call(clang::CallExpr& expression, llvm::StringRef kind) {
    const auto* callee = expression.getDirectCallee();
    if (!callee) {
      add_expr_node(kind, expression, "Unknown");
      diagnostic("UNRESOLVED_CALL", "call has no resolved direct callee", expression);
      return;
    }
    const auto* canonical = callee->getCanonicalDecl();
    const auto qualified = canonical->getQualifiedNameAsString();
    auto normalized = normalize_standard_symbol(qualified);
    if (const auto* operator_call = llvm::dyn_cast<clang::CXXOperatorCallExpr>(&expression)) {
      if (operator_call->getOperator() == clang::OO_Plus)
        normalized = "cpp.iterator.operator+";
    }
    const bool standard = normalized.starts_with("std::");
    const bool supported = normalized == "std::inner_product" ||
                           normalized == "std::accumulate" ||
                           normalized == "std::transform" ||
                           normalized == "std::sqrt" || normalized == "std::abs" ||
                           normalized == "std::span::begin" ||
                           normalized == "std::span::size" ||
                           normalized == "std::span::operator[]" ||
                           normalized == "cpp.iterator.operator+";
    const auto effect = normalized == "std::transform" ? "WriteMemory" :
                        normalized == "std::span::begin" ||
                                normalized == "std::span::operator[]"
                            ? "ReadMemory" : supported ? "Pure" : "Unknown";
    std::vector<std::pair<std::string, std::string>> call_attributes{
                  {"resolved_symbol", normalized}, {"semantic_kind", "Call"},
                   {"canonical_signature", canonical->getType().getAsString()},
                   {"overload_resolution", "direct_canonical_declaration"},
                   {"template_specialization", canonical->isFunctionTemplateSpecialization() ? "true" : "false"}};
    for (unsigned index = 0; index < expression.getNumArgs(); ++index)
      call_attributes.emplace_back("arg" + std::to_string(index), text(expression.getArg(index)->getSourceRange()));
    if (const auto* member = llvm::dyn_cast<clang::CXXMemberCallExpr>(&expression))
      if (const auto* object = member->getImplicitObjectArgument())
        call_attributes.emplace_back("object", text(object->getSourceRange()));
    if (normalized == "std::transform" && expression.getNumArgs() >= 3)
      call_attributes.emplace_back("output_base", text(expression.getArg(2)->getSourceRange()));
    add_expr_node(kind, expression, effect, std::move(call_attributes));
    const auto call_id = id(kind, expression.getSourceRange());
    for (unsigned index = 0; index < expression.getNumArgs(); ++index)
      add_expr_edge(*expression.getArg(index), call_id, "VALUE_DEPENDS_ON", "arg" + std::to_string(index));
    if (const auto* member = llvm::dyn_cast<clang::CXXMemberCallExpr>(&expression))
      if (const auto* object = member->getImplicitObjectArgument())
        add_expr_edge(*object, call_id, "VALUE_DEPENDS_ON", "object");
    if (standard) used_entities_.push_back(normalized);
    if (!standard && !supported && callee != &function_)
      diagnostic("UNRESOLVED_CALL", "external call has no contract adapter", expression);
    if (standard && !supported)
      diagnostic("UNCLASSIFIED_STANDARD_ENTITY", "standard call is not classified by frontend", expression);
    if (normalized == "std::inner_product") {
      analysis_["style"] = "inner_product";
      analysis_["resolved_callee"] = normalized;
      if (expression.getNumArgs() >= 4) {
        analysis_["range_begin"] = text(expression.getArg(0)->getSourceRange());
        analysis_["range_end"] = text(expression.getArg(1)->getSourceRange());
        analysis_["factor_begin"] = text(expression.getArg(2)->getSourceRange());
        analysis_["initial_value"] = text(expression.getArg(3)->getSourceRange());
      }
    }
    if (callee->getNameAsString().starts_with("weighted_sum") &&
        expression.getNumArgs() >= 3) {
      const auto first = text(expression.getArg(0)->getSourceRange());
      const auto output = text(expression.getArg(2)->getSourceRange());
      if (first == output) analysis_["obvious_alias"] = first + " aliases output";
    }
  }

  void inspect_subscripts(const clang::BinaryOperator& expression) {
    for (const clang::Expr* operand : {expression.getLHS(), expression.getRHS()}) {
      operand = operand->IgnoreParenImpCasts();
      const auto* subscript = llvm::dyn_cast<clang::CXXOperatorCallExpr>(operand);
      if (!subscript || subscript->getNumArgs() < 2) continue;
      const auto base = text(subscript->getArg(0)->getSourceRange());
      const auto index = text(subscript->getArg(1)->getSourceRange());
      if (base == "quantity") analysis_["quantity_index"] = index;
      if (base == "factor") analysis_["factor_index"] = index;
    }
  }

  unsigned enclosing_loop_count(const clang::Stmt& statement) const {
    unsigned count = 0;
    clang::DynTypedNode current = clang::DynTypedNode::create(statement);
    while (true) {
      const auto parents = context_.getParents(current);
      if (parents.empty()) break;
      current = parents[0];
      if (current.get<clang::ForStmt>()) ++count;
      if (current.get<clang::FunctionDecl>()) break;
    }
    return count;
  }

  void inspect_store(const clang::BinaryOperator& expression) {
    const auto* lhs = expression.getLHS()->IgnoreParenImpCasts();
    const auto* call = llvm::dyn_cast<clang::CXXOperatorCallExpr>(lhs);
    if (!call || call->getNumArgs() < 2) return;
    if (text(call->getArg(0)->getSourceRange()) != "result") return;
    analysis_["result_index"] = text(call->getArg(1)->getSourceRange());
    analysis_["store_position"] = enclosing_loop_count(expression) == 1 ?
                                      "after_inner_loop" : "inside_inner_loop";
  }

  void append_store_attributes(const clang::BinaryOperator& expression,
      std::vector<std::pair<std::string, std::string>>& attributes) {
    const auto* lhs = expression.getLHS()->IgnoreParenImpCasts();
    const auto* call = llvm::dyn_cast<clang::CXXOperatorCallExpr>(lhs);
    if (call && call->getNumArgs() >= 2) {
      attributes.emplace_back("semantic_kind", "Store");
      attributes.emplace_back("output_base", text(call->getArg(0)->getSourceRange()));
      attributes.emplace_back("output_index", text(call->getArg(1)->getSourceRange()));
    } else if (const auto* ref = llvm::dyn_cast<clang::DeclRefExpr>(lhs)) {
      attributes.emplace_back("target_variable", ref->getDecl()->getNameAsString());
    }
  }

  void add_control_edges(const clang::Stmt& statement, const std::string& target) {
    clang::DynTypedNode current = clang::DynTypedNode::create(statement);
    while (true) {
      const auto parents = context_.getParents(current);
      if (parents.empty()) break;
      current = parents[0];
      if (const auto* loop = current.get<clang::ForStmt>())
        add_edge(id("ForStmt", loop->getSourceRange()), target, "CONTROL_GUARDS", "loop");
      if (const auto* branch = current.get<clang::IfStmt>()) {
        std::string role = "condition";
        if (branch->getThen() && contains(branch->getThen()->getSourceRange(), statement.getSourceRange())) role = "true_branch";
        else if (branch->getElse() && contains(branch->getElse()->getSourceRange(), statement.getSourceRange())) role = "false_branch";
        add_edge(id("IfStmt", branch->getSourceRange()), target, "CONTROL_GUARDS", role);
      }
      if (current.get<clang::FunctionDecl>()) break;
    }
  }

  bool contains(clang::SourceRange outer, clang::SourceRange inner) const {
    if (outer.isInvalid() || inner.isInvalid()) return false;
    const auto outer_begin = source_manager_.getFileOffset(outer.getBegin());
    const auto outer_end = source_manager_.getFileOffset(outer.getEnd());
    const auto inner_begin = source_manager_.getFileOffset(inner.getBegin());
    const auto inner_end = source_manager_.getFileOffset(inner.getEnd());
    return outer_begin <= inner_begin && inner_end <= outer_end;
  }

  bool inside_lambda(const clang::Stmt& statement) const {
    clang::DynTypedNode current = clang::DynTypedNode::create(statement);
    while (true) {
      const auto parents = context_.getParents(current);
      if (parents.empty()) return false;
      current = parents[0];
      if (current.get<clang::LambdaExpr>()) return true;
      if (current.get<clang::FunctionDecl>()) return false;
    }
  }

  void finish_analysis() {
    if (analysis_.find("style") == analysis_.end()) analysis_["style"] = "explicit_loop";
    if (loops_.size() >= 1) {
      analysis_["outer_index"] = loops_[0].index;
      analysis_["outer_bound"] = loops_[0].bound;
      analysis_["outer_condition"] = loops_[0].operation;
    }
    if (loops_.size() >= 2) {
      analysis_["inner_index"] = loops_[1].index;
      analysis_["inner_bound"] = loops_[1].bound;
      analysis_["inner_condition"] = loops_[1].operation;
    }
    if (!unsupported_control_flow_.empty()) {
      llvm::json::Array values;
      for (const auto& value : unsupported_control_flow_) values.push_back(value);
      analysis_["unsupported_control_flow"] = std::move(values);
    }
    if (analysis_.getString("style") == "inner_product") {
      analysis_["transform_operation"] = "Multiply";
      analysis_["reduction_operation"] = "Add";
      analysis_["store_position"] = "after_inner_loop";
    }
  }

  clang::ASTContext& context_;
  clang::SourceManager& source_manager_;
  const clang::LangOptions& lang_;
  clang::FunctionDecl& function_;
  llvm::json::Array nodes_, edges_, diagnostics_;
  llvm::json::Object analysis_;
  std::vector<std::string> used_entities_, unsupported_control_flow_;
  std::vector<LoopFact> loops_;
};

class AuditConsumer final : public clang::ASTConsumer {
 public:
  AuditConsumer(std::string compile_command, std::string database,
                std::string source)
      : compile_command_(std::move(compile_command)), database_(std::move(database)),
        source_(std::move(source)) {}

  void HandleTranslationUnit(clang::ASTContext& context) override {
    clang::FunctionDecl* selected = nullptr;
    for (const auto* declaration : context.getTranslationUnitDecl()->decls()) {
      auto* function = llvm::dyn_cast<clang::FunctionDecl>(const_cast<clang::Decl*>(declaration));
      if (function && function->hasBody() && function->getNameAsString() == target_function) {
        if (selected) {
          llvm::errs() << "unresolved overload: multiple definitions named " << target_function << "\n";
          return;
        }
        selected = function;
      }
    }
    if (!selected) { llvm::errs() << "function not found: " << target_function << "\n"; return; }
    AuditVisitor visitor(context, *selected);
    visitor.run();
    llvm::json::Object producer;
    producer["kind"] = "clang-libtooling";
    producer["clang_version"] = CLANG_VERSION_STRING;
    producer["compile_command"] = compile_command_;
    producer["compilation_database"] = database_;
    llvm::json::Object root;
    root["schema_version"] = "0.1";
    root["dependency_graph_version"] = "0.1";
    root["standard_version"] = context.getLangOpts().CPlusPlus20 ? "cpp20" : "cpp17";
    root["source_hash"] = source_hash(source_);
    root["function"] = target_function.getValue();
    root["translation_unit"] = source_;
    root["producer"] = std::move(producer);
    root["nodes"] = visitor.take_nodes();
    root["dependency_edges"] = visitor.take_edges();
    root["analysis"] = visitor.take_analysis();
    root["used_standard_entities"] = visitor.take_entities();
    root["diagnostics"] = visitor.take_diagnostics();
    llvm::outs() << llvm::formatv("{0:2}\n", llvm::json::Value(std::move(root)));
    emitted_ = true;
  }

  bool emitted() const { return emitted_; }

 private:
  std::string compile_command_, database_, source_;
  bool emitted_{false};
};

class ExtractAction final : public clang::ASTFrontendAction {
 public:
  ExtractAction(std::string command, std::string database, std::string source)
      : command_(std::move(command)), database_(std::move(database)), source_(std::move(source)) {}
  std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(
      clang::CompilerInstance&, llvm::StringRef) override {
    return std::make_unique<AuditConsumer>(command_, database_, source_);
  }
 private:
  std::string command_, database_, source_;
};

class ExtractFactory final : public clang::tooling::FrontendActionFactory {
 public:
  ExtractFactory(std::string command, std::string database, std::string source)
      : command_(std::move(command)), database_(std::move(database)), source_(std::move(source)) {}
  std::unique_ptr<clang::FrontendAction> create() override {
    return std::make_unique<ExtractAction>(command_, database_, source_);
  }
 private:
  std::string command_, database_, source_;
};

}  // namespace

int main(int argc, const char** argv) {
  auto parser = clang::tooling::CommonOptionsParser::create(argc, argv, category);
  if (!parser) { llvm::errs() << parser.takeError(); return 2; }
  const auto& sources = parser->getSourcePathList();
  if (sources.size() != 1) { llvm::errs() << "exactly one translation unit is required\n"; return 2; }
  const auto commands = parser->getCompilations().getCompileCommands(sources.front());
  if (commands.empty()) {
    llvm::errs() << "compile command is required; inferred flags are forbidden\n";
    return 2;
  }
  llvm::SmallString<256> database(commands.front().Directory);
  llvm::sys::path::append(database, "compile_commands.json");
  if (!llvm::sys::fs::exists(database)) {
    llvm::errs() << "compile_commands.json not found at " << database << "\n";
    return 2;
  }
  clang::tooling::ClangTool tool(parser->getCompilations(), sources);
  ExtractFactory factory(join_command(commands.front()), database.str().str(), sources.front());
  return tool.run(&factory);
}
