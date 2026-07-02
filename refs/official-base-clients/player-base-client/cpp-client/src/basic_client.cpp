#include "basic_client.hpp"

#include "json_fields.hpp"
#include "messages.hpp"
#include "transport.hpp"

#include <iostream>
#include <utility>

BasicClient::BasicClient(int fd, Config config) : fd_(fd), config_(std::move(config)) {}

int BasicClient::run() {
    send_frame(fd_, registration_json(config_));
    while (true) {
        auto frame = read_frame(fd_);
        if (!frame.has_value()) {
            std::cout << "connection closed\n";
            return 0;
        }

        int status = handle_frame(*frame);
        if (status <= 0) {
            return status == 0 ? 0 : 1;
        }
    }
}

int BasicClient::handle_frame(const std::string &frame) {
    std::string msg_name = extract_string_field(frame, "msg_name").value_or("");
    std::string msg_data = extract_object_field(frame, "msg_data").value_or(frame);

    if (msg_name == "start") {
        handle_start(msg_data);
    } else if (msg_name == "inquire") {
        handle_inquire(msg_data);
    } else if (msg_name == "over") {
        std::cout << "over received\n";
        return 0;
    } else if (msg_name == "error") {
        std::cerr << "error received: " << frame << '\n';
        return -1;
    } else {
        std::cout << "ignored msg_name=" << msg_name << '\n';
    }
    return 1;
}

void BasicClient::handle_start(const std::string &msg_data) {
    match_id_ = extract_direct_string_field(msg_data, "matchId").value_or("");
    int round = extract_direct_int_field(msg_data, "round").value_or(1);
    std::cout << "start match=" << match_id_ << " round=" << round << '\n';
    send_frame(fd_, ready_json(match_id_, round, config_.player_id));
}

void BasicClient::handle_inquire(const std::string &msg_data) {
    int round = extract_direct_int_field(msg_data, "round").value_or(0);
    std::cout << "inquire round=" << round << " -> heartbeat\n";
    send_frame(fd_, action_json(match_id_, round, config_.player_id));
}
