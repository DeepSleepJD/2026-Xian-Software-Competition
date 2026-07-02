CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -pedantic -O2

BUILD_DIR := build
TARGET := $(BUILD_DIR)/basic_c_client
TEST_TARGET := $(BUILD_DIR)/basic_c_client_tests
CORE_SOURCES := \
	src/client_session.c \
	src/config.c \
	src/json_fields.c \
	src/messages.c \
	src/transport.c
SOURCES := src/basic_client.c $(CORE_SOURCES)
TEST_SOURCES := tests/basic_client_tests.c $(CORE_SOURCES)

.PHONY: all clean test

all: $(TARGET)

$(TARGET): $(SOURCES)
	mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -Isrc $(SOURCES) -o $@

$(TEST_TARGET): $(TEST_SOURCES)
	mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) -Isrc $(TEST_SOURCES) -o $@

test: $(TEST_TARGET)
	$(TEST_TARGET)

clean:
	rm -rf $(BUILD_DIR)
