#ifndef LYCHEE_MESSAGES_H
#define LYCHEE_MESSAGES_H

#include "config.h"

int send_registration(int fd, const Config *config);
int send_ready(int fd, const char *match_id, int round, int player_id);
int send_action_heartbeat(int fd, const char *match_id, int round, int player_id);
int send_move_action(int fd, const char *match_id, int round, int player_id, const char *target_node_id);

#endif
