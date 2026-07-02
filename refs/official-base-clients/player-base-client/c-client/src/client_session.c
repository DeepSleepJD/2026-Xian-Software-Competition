#include "client_session.h"

#include "json_fields.h"
#include "messages.h"
#include "transport.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int handle_start_message(ClientSession *session, const char *msg_data) {
    int round = 1;
    extract_direct_string_field(msg_data, "matchId", session->match_id, sizeof(session->match_id));
    extract_direct_int_field(msg_data, "round", &round);
    printf("start match=%s round=%d\n", session->match_id, round);
    if (send_ready(session->fd, session->match_id, round, session->config->player_id) != 0) {
        perror("send ready");
        return -1;
    }
    return 1;
}

static int handle_inquire_message(ClientSession *session, const char *msg_data) {
    int round = 0;
    extract_direct_int_field(msg_data, "round", &round);
    printf("inquire round=%d -> heartbeat\n", round);
    if (send_action_heartbeat(session->fd, session->match_id, round, session->config->player_id) != 0) {
        perror("send action");
        return -1;
    }
    return 1;
}

static int handle_frame(ClientSession *session, const char *frame) {
    char msg_name[64] = {0};
    extract_string_field(frame, "msg_name", msg_name, sizeof(msg_name));
    const char *msg_data = find_object_field(frame, "msg_data");
    if (msg_data == NULL) {
        msg_data = frame;
    }

    if (strcmp(msg_name, "start") == 0) {
        return handle_start_message(session, msg_data);
    }
    if (strcmp(msg_name, "inquire") == 0) {
        return handle_inquire_message(session, msg_data);
    }
    if (strcmp(msg_name, "over") == 0) {
        printf("over received\n");
        return 0;
    }
    if (strcmp(msg_name, "error") == 0) {
        fprintf(stderr, "error received: %s\n", frame);
        return -1;
    }

    printf("ignored msg_name=%s\n", msg_name);
    return 1;
}

int run_client(ClientSession *session) {
    while (1) {
        char *frame = read_frame(session->fd);
        if (frame == NULL) {
            printf("connection closed\n");
            return 0;
        }

        int status = handle_frame(session, frame);
        free(frame);
        if (status <= 0) {
            return status == 0 ? 0 : 1;
        }
    }
}
