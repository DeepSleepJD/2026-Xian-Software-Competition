cmake_minimum_required(VERSION 3.16)

project(lychee_basic_c_client VERSION 0.1.0 LANGUAGES C)

if(WIN32 AND NOT CYGWIN AND NOT MSYS)
  message(FATAL_ERROR "This client uses POSIX sockets. Build it on Linux, WSL2, Cygwin, or an MSYS POSIX environment.")
endif()

enable_testing()

add_library(lychee_basic_c_core
  src/client_session.c
  src/config.c
  src/json_fields.c
  src/messages.c
  src/transport.c
)

target_include_directories(lychee_basic_c_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(lychee_basic_c_core PUBLIC c_std_11)

if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(lychee_basic_c_core PRIVATE -Wall -Wextra -pedantic)
endif()

add_executable(basic_c_client
  src/basic_client.c
)

target_link_libraries(basic_c_client PRIVATE lychee_basic_c_core)

add_executable(basic_c_client_tests
  tests/basic_client_tests.c
)

target_link_libraries(basic_c_client_tests PRIVATE lychee_basic_c_core)

add_test(NAME basic_c_client_tests COMMAND basic_c_client_tests)
