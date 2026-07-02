#include "transport.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_BODY 99999

int connect_tcp(const char *host, const char *port) {
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    int err = getaddrinfo(host, port, &hints, &result);
    if (err != 0) {
        fprintf(stderr, "getaddrinfo: %s\n", gai_strerror(err));
        return -1;
    }

    int fd = -1;
    for (struct addrinfo *rp = result; rp != NULL; rp = rp->ai_next) {
        fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (fd == -1) {
            continue;
        }
        if (connect(fd, rp->ai_addr, rp->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    return fd;
}

static int write_all(int fd, const char *data, size_t len) {
    size_t written = 0;
    while (written < len) {
        ssize_t n = send(fd, data + written, len - written, 0);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (n == 0) {
            return -1;
        }
        written += (size_t)n;
    }
    return 0;
}

static int read_exact(int fd, char *buffer, size_t len) {
    size_t read_len = 0;
    while (read_len < len) {
        ssize_t n = recv(fd, buffer + read_len, len - read_len, 0);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (n == 0) {
            return 0;
        }
        read_len += (size_t)n;
    }
    return 1;
}

int send_frame(int fd, const char *json) {
    size_t len = strlen(json);
    if (len > MAX_BODY) {
        fprintf(stderr, "message too large: %zu\n", len);
        return -1;
    }
    char prefix[6];
    snprintf(prefix, sizeof(prefix), "%05zu", len);
    if (write_all(fd, prefix, 5) != 0) {
        return -1;
    }
    return write_all(fd, json, len);
}

char *read_frame(int fd) {
    char prefix[6] = {0};
    int status = read_exact(fd, prefix, 5);
    if (status <= 0) {
        return NULL;
    }
    int len = atoi(prefix);
    if (len < 0 || len > MAX_BODY) {
        fprintf(stderr, "invalid frame length: %s\n", prefix);
        return NULL;
    }
    char *body = (char *)calloc((size_t)len + 1, 1);
    if (body == NULL) {
        return NULL;
    }
    status = read_exact(fd, body, (size_t)len);
    if (status <= 0) {
        free(body);
        return NULL;
    }
    body[len] = '\0';
    return body;
}
