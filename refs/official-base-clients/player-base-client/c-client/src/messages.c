#include "messages.h"

#include "json_fields.h"
#include "transport.h"

#include <stdio.h>

int send_registration(int fd, const Config *config) {
    char escaped_name[256];
    char escaped_version[64];
    char json[512];
    json_escape(config->player_name, escaped_name, sizeof(escaped_name));
    json_escape(config->version, escaped_version, sizeof(escaped_version));
    snprintf(json, sizeof(json),
             "{\"msg_name\":\"registration\",\"msg_data\":{\"playerId\":%d,"
             "\"playerName\":\"%s\",\"version\":\"%s\"}}",
             config->player_id, escaped_name, escaped_version);
    return send_frame(fd, json);
}

int send_ready(int fd, const char *match_id, int round, int player_id) {
    char escaped_match_id[128];
    char json[512];
    json_escape(match_id, escaped_match_id, sizeof(escaped_match_id));
    snprintf(json, sizeof(json),
             "{\"msg_name\":\"ready\",\"msg_data\":{\"matchId\":\"%s\","
             "\"round\":%d,\"playerId\":%d}}",
             escaped_match_id, round, player_id);
    return send_frame(fd, json);
}

int send_action_heartbeat(int fd, const char *match_id, int round, int player_id) {
    char escaped_match_id[128];
    char json[512];
    json_escape(match_id, escaped_match_id, sizeof(escaped_match_id));
    snprintf(json, sizeof(json),
             "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"%s\","
             "\"round\":%d,\"playerId\":%d,\"actions\":[]}}",
             escaped_match_id, round, player_id);
    return send_frame(fd, json);
}

int send_move_action(int fd, const char *match_id, int round, int player_id, const char *target_node_id) {
    char escaped_match_id[128];
    char escaped_target_node_id[128];
    char json[512];
    json_escape(match_id, escaped_match_id, sizeof(escaped_match_id));
    json_escape(target_node_id, escaped_target_node_id, sizeof(escaped_target_node_id));
    snprintf(json, sizeof(json),
             "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"%s\","
             "\"round\":%d,\"playerId\":%d,\"actions\":[{\"action\":\"MOVE\","
             "\"targetNodeId\":\"%s\"}]}}",
             escaped_match_id, round, player_id, escaped_target_node_id);
    return send_frame(fd, json);
}
