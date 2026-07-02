CXX ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -pedantic -O2

BUILD_DIR := build
TARGET := $(BUILD_DIR)/basic_cpp_client
TEST_TARGET := $(BUILD_DIR)/basic_cpp_client_tests
CORE_SOURCES := \
	src/basic_client.cpp \
	src/config.cpp \
	src/json_fields.cpp \
	src/messages.cpp \
	src/transport.cpp
SOURCES := src/main.cpp $(CORE_SOURCES)
TEST_SOURCES := tests/basic_client_tests.cpp $(CORE_SOURCES)

.PHONY: all clean test

all: $(TARGET)

$(TARGET): $(SOURCES)
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -Isrc $(SOURCES) -o $@

$(TEST_TARGET): $(TEST_SOURCES)
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -Isrc $(TEST_SOURCES) -o $@

test: $(TEST_TARGET)
	$(TEST_TARGET)

clean:
	rm -rf $(BUILD_DIR)
