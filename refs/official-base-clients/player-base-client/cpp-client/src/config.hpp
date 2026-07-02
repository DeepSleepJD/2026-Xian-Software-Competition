#ifndef LYCHEE_CONFIG_HPP
#define LYCHEE_CONFIG_HPP

#include <string>

struct Config {
    std::string host = "127.0.0.1";
    std::string port = "30000";
    int player_id = 1002;
    std::string player_name = "BasicCpp";
    std::string version = "0.1";
};

Config parse_args(int argc, char **argv);

#endif
