#ifndef LYCHEE_CONFIG_H
#define LYCHEE_CONFIG_H

typedef struct {
    const char *host;
    const char *port;
    int player_id;
    const char *player_name;
    const char *version;
} Config;

Config parse_args(int argc, char **argv);

#endif
