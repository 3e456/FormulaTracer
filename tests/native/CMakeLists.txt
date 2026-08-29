cmake_minimum_required(VERSION 3.24)
project(FormulaTracerNativeApiTests LANGUAGES C CXX)

enable_testing()

add_library(formulatracer_native SHARED IMPORTED GLOBAL)
if(WIN32)
  set_target_properties(formulatracer_native PROPERTIES
    IMPORTED_IMPLIB "${CMAKE_SOURCE_DIR}/../../target/debug/formulatracer_c_api.dll.lib"
    IMPORTED_LOCATION "${CMAKE_SOURCE_DIR}/../../target/debug/formulatracer_c_api.dll")
else()
  set_target_properties(formulatracer_native PROPERTIES
    IMPORTED_LOCATION "${CMAKE_SOURCE_DIR}/../../target/debug/libformulatracer_c_api.so")
endif()

add_executable(formulatracer_c_api_test c_api_test.c)
target_include_directories(formulatracer_c_api_test PRIVATE "${CMAKE_SOURCE_DIR}/../../include")
target_link_libraries(formulatracer_c_api_test PRIVATE formulatracer_native)
add_test(NAME formulatracer_c_api_test COMMAND formulatracer_c_api_test)

add_executable(formulatracer_cpp_api_test cpp_api_test.cpp)
target_compile_features(formulatracer_cpp_api_test PRIVATE cxx_std_20)
target_include_directories(formulatracer_cpp_api_test PRIVATE "${CMAKE_SOURCE_DIR}/../../include")
target_link_libraries(formulatracer_cpp_api_test PRIVATE formulatracer_native)
add_test(NAME formulatracer_cpp_api_test COMMAND formulatracer_cpp_api_test)
