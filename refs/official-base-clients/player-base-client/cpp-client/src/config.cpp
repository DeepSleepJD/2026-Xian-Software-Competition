#include "config.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>

namespace {

void usage(const char *program) {
    std::cerr << "Usage: " << program
              << " [--host HOST] [--port PORT] [--player-id ID]"
              << " [--player-name NAME] [--version VERSION]\n";
}

}  // namespace

Config parse_args(int argc, char **argv) {
    Config config;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto need_value = [&](const std::string &name) -> std::string {
            if (i + 1 >= argc) {
                usage(argv[0]);
                throw std::runtime_error("missing value for " + name);
            }
            return argv[++i];
        };
        if (arg == "--host") {
            config.host = need_value(arg);
        } else if (arg == "--port") {
            config.port = need_value(arg);
        } else if (arg == "--player-id") {
            config.player_id = std::stoi(need_value(arg));
        } else if (arg == "--player-name") {
            config.player_name = need_value(arg);
        } else if (arg == "--version") {
            config.version = need_value(arg);
        } else if (arg == "--help") {
            usage(argv[0]);
            std::exit(0);
        } else {
            usage(argv[0]);
            throw std::runtime_error("unknown argument: " + arg);
        }
    }
    return config;
}
