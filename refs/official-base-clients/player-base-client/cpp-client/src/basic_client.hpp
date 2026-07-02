#ifndef LYCHEE_BASIC_CLIENT_HPP
#define LYCHEE_BASIC_CLIENT_HPP

#include "config.hpp"

#include <string>

class BasicClient {
public:
    BasicClient(int fd, Config config);

    int run();

private:
    int handle_frame(const std::string &frame);
    void handle_start(const std::string &msg_data);
    void handle_inquire(const std::string &msg_data);

    int fd_;
    Config config_;
    std::string match_id_;
};

#endif
