cmake_minimum_required(VERSION 3.20)
project(cpp_algorithm_audit VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(CPP_AUDIT_BUILD_CLANG_FRONTEND "Build the Clang LibTooling extractor" ON)
option(CPP_AUDIT_BUILD_TESTS "Build C++ tests" ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(cpp_audit_ir cpp/src/ir.cpp)
target_include_directories(cpp_audit_ir PUBLIC cpp/include)
target_compile_features(cpp_audit_ir PUBLIC cxx_std_20)

if(CPP_AUDIT_BUILD_CLANG_FRONTEND)
  # LLVM's generated ConfigVersion requires an exact major.minor pair, so a
  # request for bare "18" rejects valid 18.1.x packages. Discover first and
  # enforce the supported major explicitly below.
  find_package(LLVM REQUIRED CONFIG)
  find_package(Clang REQUIRED CONFIG)
  if(NOT LLVM_VERSION_MAJOR EQUAL 18 OR NOT Clang_VERSION MATCHES "^18(\\.|$)")
    message(FATAL_ERROR
      "LLVM_VERSION_MISMATCH: LLVM ${LLVM_PACKAGE_VERSION}, Clang ${Clang_VERSION}; major 18 is required")
  endif()
  foreach(CPP_AUDIT_REQUIRED_DIR IN ITEMS
      "${LLVM_INCLUDE_DIRS}/llvm" "${LLVM_INCLUDE_DIRS}/clang")
    if(NOT EXISTS "${CPP_AUDIT_REQUIRED_DIR}")
      message(FATAL_ERROR
        "LLVM_EXECUTABLES_FOUND_BUT_LIBTOOLING_DEVELOPMENT_PACKAGE_MISSING: ${CPP_AUDIT_REQUIRED_DIR}")
    endif()
  endforeach()
  add_executable(cpp-audit-clang cpp/src/clang_frontend.cpp)
  target_include_directories(cpp-audit-clang PRIVATE ${LLVM_INCLUDE_DIRS} ${CLANG_INCLUDE_DIRS})
  llvm_map_components_to_libnames(CPP_AUDIT_LLVM_LIBS Support)
  if(TARGET clang-cpp)
    target_link_libraries(cpp-audit-clang PRIVATE cpp_audit_ir clang-cpp LLVM)
  else()
    target_link_libraries(cpp-audit-clang PRIVATE cpp_audit_ir clangTooling clangFrontend clangSerialization clangASTMatchers clangAST clangLex clangBasic ${CPP_AUDIT_LLVM_LIBS})
  endif()
  target_compile_definitions(cpp-audit-clang PRIVATE ${LLVM_DEFINITIONS})
endif()

if(CPP_AUDIT_BUILD_TESTS)
  enable_testing()
  add_executable(cpp_audit_ir_test cpp/tests/ir_test.cpp)
  target_link_libraries(cpp_audit_ir_test PRIVATE cpp_audit_ir)
  add_test(NAME cpp_audit_ir_test COMMAND cpp_audit_ir_test)
  add_executable(weighted_sum_runtime
    cpp/tests/weighted_sum_runtime.cpp
    examples/weighted_sum/weighted_sum_loop.cpp
    examples/weighted_sum/weighted_sum_inner_product.cpp)
  target_compile_features(weighted_sum_runtime PRIVATE cxx_std_20)
  add_test(NAME weighted_sum_runtime COMMAND weighted_sum_runtime)
  add_library(weighted_sum_negative_sources OBJECT tests/negative/frontend_fail_closed.cpp)
  target_compile_features(weighted_sum_negative_sources PRIVATE cxx_std_20)
endif()
