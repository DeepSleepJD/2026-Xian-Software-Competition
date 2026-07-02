#ifndef LYCHEE_CLIENT_SESSION_H
#define LYCHEE_CLIENT_SESSION_H

#include "config.h"

typedef struct {
    int fd;
    const Config *config;
    char match_id[128];
} ClientSession;

int run_client(ClientSession *session);

#endif
