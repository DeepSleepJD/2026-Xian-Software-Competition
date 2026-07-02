#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DEFAULT_HOST "127.0.0.1"
#define DEFAULT_PORT "30000"
#define DEFAULT_PLAYER_ID 1001
#define DEFAULT_PLAYER_NAME "BasicC"
#define DEFAULT_VERSION "0.1"

static void usage(const char *program) {
    fprintf(stderr,
            "Usage: %s [--host HOST] [--port PORT] [--player-id ID] "
            "[--player-name NAME] [--version VERSION]\n",
            program);
}

Config parse_args(int argc, char **argv) {
    Config config = {DEFAULT_HOST, DEFAULT_PORT, DEFAULT_PLAYER_ID,
                     DEFAULT_PLAYER_NAME, DEFAULT_VERSION};
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--host") == 0 && i + 1 < argc) {
            config.host = argv[++i];
        } else if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            config.port = argv[++i];
        } else if (strcmp(argv[i], "--player-id") == 0 && i + 1 < argc) {
            config.player_id = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--player-name") == 0 && i + 1 < argc) {
            config.player_name = argv[++i];
        } else if (strcmp(argv[i], "--version") == 0 && i + 1 < argc) {
            config.version = argv[++i];
        } else if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            exit(0);
        } else {
            usage(argv[0]);
            exit(2);
        }
    }
    return config;
}
