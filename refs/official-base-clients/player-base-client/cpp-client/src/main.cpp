#include "basic_client.hpp"
#include "config.hpp"
#include "transport.hpp"

#include <unistd.h>

#include <exception>
#include <iostream>

int main(int argc, char **argv) {
    try {
        Config config = parse_args(argc, argv);
        int fd = connect_tcp(config.host, config.port);
        std::cout << "connected to " << config.host << ':' << config.port
                  << " as player " << config.player_id << '\n';
        int exit_code = BasicClient(fd, config).run();
        close(fd);
        return exit_code;
    } catch (const std::exception &ex) {
        std::cerr << ex.what() << '\n';
        return 1;
    }
}
