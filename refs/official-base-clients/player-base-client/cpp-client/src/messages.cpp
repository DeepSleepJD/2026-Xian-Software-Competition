#include "messages.hpp"

#include "json_fields.hpp"

#include <sstream>

std::string registration_json(const Config &config) {
    std::ostringstream out;
    out << "{\"msg_name\":\"registration\",\"msg_data\":{\"playerId\":"
        << config.player_id << ",\"playerName\":\"" << json_escape(config.player_name)
        << "\",\"version\":\"" << json_escape(config.version) << "\"}}";
    return out.str();
}

std::string ready_json(const std::string &match_id, int round, int player_id) {
    std::ostringstream out;
    out << "{\"msg_name\":\"ready\",\"msg_data\":{\"matchId\":\"" << json_escape(match_id)
        << "\",\"round\":" << round << ",\"playerId\":" << player_id << "}}";
    return out.str();
}

std::string action_json(const std::string &match_id, int round, int player_id) {
    std::ostringstream out;
    out << "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"" << json_escape(match_id)
        << "\",\"round\":" << round << ",\"playerId\":" << player_id
        << ",\"actions\":[]}}";
    return out.str();
}

std::string move_action_json(const std::string &match_id, int round, int player_id, const std::string &target_node_id) {
    std::ostringstream out;
    out << "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"" << json_escape(match_id)
        << "\",\"round\":" << round << ",\"playerId\":" << player_id
        << ",\"actions\":[{\"action\":\"MOVE\",\"targetNodeId\":\""
        << json_escape(target_node_id) << "\"}]}}";
    return out.str();
}
