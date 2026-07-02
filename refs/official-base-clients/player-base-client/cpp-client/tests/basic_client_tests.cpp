#include "config.hpp"
#include "json_fields.hpp"
#include "messages.hpp"
#include "transport.hpp"

#include <cassert>
#include <string>
#include <sys/socket.h>
#include <unistd.h>

namespace {

std::string read_sent_frame(const std::string &json) {
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    send_frame(sockets[0], json);
    auto body = read_frame(sockets[1]);
    close(sockets[0]);
    close(sockets[1]);
    assert(body.has_value());
    return *body;
}

void test_registration_json() {
    Config config;
    config.player_id = 1002;
    config.player_name = "BasicCpp";
    config.version = "0.1";

    const std::string json = registration_json(config);
    assert(json.find("\"msg_name\":\"registration\"") != std::string::npos);
    assert(json.find("\"playerId\":1002") != std::string::npos);
    assert(json.find("\"playerName\":\"BasicCpp\"") != std::string::npos);
}

void test_action_frame_round_trip() {
    const std::string json = action_json("match-1", 7, 1002);
    const std::string body = read_sent_frame(json);
    assert(body == "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"match-1\","
                   "\"round\":7,\"playerId\":1002,\"actions\":[]}}");
}

void test_move_action_uses_target_node_id() {
    const std::string json = move_action_json("match-1", 7, 1002, "S10");
    const std::string body = read_sent_frame(json);
    assert(body == "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"match-1\","
                   "\"round\":7,\"playerId\":1002,\"actions\":[{\"action\":\"MOVE\","
                   "\"targetNodeId\":\"S10\"}]}}");
}

void test_json_escape_control_characters() {
    assert(json_escape("line\n\"\\") == "line\\n\\\"\\\\");
}

void test_json_string_reader_decodes_escapes() {
    auto value = extract_direct_string_field("{\"name\":\"Agent\\n\\\"A\\\"\\u0042\"}", "name");
    assert(value.has_value());
    assert(*value == "Agent\n\"A\"B");
}

}  // namespace

int main() {
    test_registration_json();
    test_action_frame_round_trip();
    test_move_action_uses_target_node_id();
    test_json_escape_control_characters();
    test_json_string_reader_decodes_escapes();
    return 0;
}
