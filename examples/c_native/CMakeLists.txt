cmake_minimum_required(VERSION 3.20)
project(formulatracer_c_consumer LANGUAGES C)

if(NOT DEFINED FORMULATRACER_ROOT)
  message(FATAL_ERROR "Set FORMULATRACER_ROOT to a FormulaTracer source or native release root")
endif()
find_library(FORMULATRACER_LIBRARY NAMES formulatracer_c_api libformulatracer_c_api
  PATHS "${FORMULATRACER_ROOT}/lib" "${FORMULATRACER_ROOT}/target/release" REQUIRED NO_DEFAULT_PATH)
add_executable(formulatracer_c_example main.c)
target_include_directories(formulatracer_c_example PRIVATE "${FORMULATRACER_ROOT}/include")
target_link_libraries(formulatracer_c_example PRIVATE "${FORMULATRACER_LIBRARY}")
