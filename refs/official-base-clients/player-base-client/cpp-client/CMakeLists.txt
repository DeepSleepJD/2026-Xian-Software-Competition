cmake_minimum_required(VERSION 3.16)

project(lychee_basic_cpp_client VERSION 0.1.0 LANGUAGES CXX)

if(WIN32 AND NOT CYGWIN AND NOT MSYS)
  message(FATAL_ERROR "This client uses POSIX sockets. Build it on Linux, WSL2, Cygwin, or an MSYS POSIX environment.")
endif()

enable_testing()

add_library(lychee_basic_cpp_core
  src/basic_client.cpp
  src/config.cpp
  src/json_fields.cpp
  src/messages.cpp
  src/transport.cpp
)

target_include_directories(lychee_basic_cpp_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(lychee_basic_cpp_core PUBLIC cxx_std_17)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(lychee_basic_cpp_core PRIVATE -Wall -Wextra -pedantic)
endif()

add_executable(basic_cpp_client
  src/main.cpp
)

target_link_libraries(basic_cpp_client PRIVATE lychee_basic_cpp_core)

add_executable(basic_cpp_client_tests
  tests/basic_client_tests.cpp
)

target_link_libraries(basic_cpp_client_tests PRIVATE lychee_basic_cpp_core)

add_test(NAME basic_cpp_client_tests COMMAND basic_cpp_client_tests)
