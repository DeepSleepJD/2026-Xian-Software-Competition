#ifndef LYCHEE_MESSAGES_HPP
#define LYCHEE_MESSAGES_HPP

#include "config.hpp"

#include <string>

std::string registration_json(const Config &config);
std::string ready_json(const std::string &match_id, int round, int player_id);
std::string action_json(const std::string &match_id, int round, int player_id);
std::string move_action_json(const std::string &match_id, int round, int player_id, const std::string &target_node_id);

#endif
