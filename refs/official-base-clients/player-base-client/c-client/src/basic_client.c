#include "client_session.h"
#include "config.h"
#include "messages.h"
#include "transport.h"

#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv) {
    Config config = parse_args(argc, argv);
    int fd = connect_tcp(config.host, config.port);
    if (fd < 0) {
        perror("connect");
        return 1;
    }

    printf("connected to %s:%s as player %d\n", config.host, config.port, config.player_id);
    if (send_registration(fd, &config) != 0) {
        perror("send registration");
        close(fd);
        return 1;
    }

    ClientSession session = {fd, &config, {0}};
    int exit_code = run_client(&session);
    close(fd);
    return exit_code;
}
