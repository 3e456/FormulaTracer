cmake_minimum_required(VERSION 3.20)
project(formulatracer_cpp_consumer LANGUAGES CXX)

if(NOT DEFINED FORMULATRACER_ROOT)
  message(FATAL_ERROR "Set FORMULATRACER_ROOT to a FormulaTracer source or native release root")
endif()
find_library(FORMULATRACER_LIBRARY NAMES formulatracer_c_api libformulatracer_c_api
  PATHS "${FORMULATRACER_ROOT}/lib" "${FORMULATRACER_ROOT}/target/release" REQUIRED NO_DEFAULT_PATH)
add_executable(formulatracer_cpp_example main.cpp)
target_compile_features(formulatracer_cpp_example PRIVATE cxx_std_20)
target_include_directories(formulatracer_cpp_example PRIVATE "${FORMULATRACER_ROOT}/include")
target_link_libraries(formulatracer_cpp_example PRIVATE "${FORMULATRACER_LIBRARY}")
