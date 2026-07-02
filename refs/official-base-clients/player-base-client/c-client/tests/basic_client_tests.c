#include "config.h"
#include "json_fields.h"
#include "messages.h"
#include "transport.h"

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static char *read_sent_message(int (*send_message)(int, const Config *), const Config *config) {
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    assert(send_message(sockets[0], config) == 0);
    char *body = read_frame(sockets[1]);
    close(sockets[0]);
    close(sockets[1]);
    return body;
}

static void test_registration_message(void) {
    Config config = {
        .host = "127.0.0.1",
        .port = "30000",
        .player_id = 1001,
        .player_name = "BasicC",
        .version = "0.1",
    };
    char *body = read_sent_message(send_registration, &config);
    assert(body != NULL);
    assert(strstr(body, "\"msg_name\":\"registration\"") != NULL);
    assert(strstr(body, "\"playerId\":1001") != NULL);
    assert(strstr(body, "\"playerName\":\"BasicC\"") != NULL);
    free(body);
}

static void test_action_heartbeat_message(void) {
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    assert(send_action_heartbeat(sockets[0], "match-1", 7, 1001) == 0);
    char *body = read_frame(sockets[1]);
    close(sockets[0]);
    close(sockets[1]);
    assert(body != NULL);
    assert(strcmp(body,
                  "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"match-1\","
                  "\"round\":7,\"playerId\":1001,\"actions\":[]}}") == 0);
    free(body);
}

static void test_move_action_uses_target_node_id(void) {
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    assert(send_move_action(sockets[0], "match-1", 7, 1001, "S10") == 0);
    char *body = read_frame(sockets[1]);
    close(sockets[0]);
    close(sockets[1]);
    assert(body != NULL);
    assert(strcmp(body,
                  "{\"msg_name\":\"action\",\"msg_data\":{\"matchId\":\"match-1\","
                  "\"round\":7,\"playerId\":1001,\"actions\":[{\"action\":\"MOVE\","
                  "\"targetNodeId\":\"S10\"}]}}") == 0);
    free(body);
}

static void test_json_escape_control_characters(void) {
    char escaped[64];
    json_escape("line\n\"\\", escaped, sizeof(escaped));
    assert(strcmp(escaped, "line\\n\\\"\\\\") == 0);
}

static void test_json_string_reader_decodes_escapes(void) {
    char out[64];
    assert(extract_direct_string_field("{\"name\":\"Agent\\n\\\"A\\\"\\u0042\"}", "name",
                                       out, sizeof(out)) == 1);
    assert(strcmp(out, "Agent\n\"A\"B") == 0);
}

int main(void) {
    test_registration_message();
    test_action_heartbeat_message();
    test_move_action_uses_target_node_id();
    test_json_escape_control_characters();
    test_json_string_reader_decodes_escapes();
    return 0;
}
