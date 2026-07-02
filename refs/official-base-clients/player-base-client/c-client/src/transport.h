#ifndef LYCHEE_TRANSPORT_H
#define LYCHEE_TRANSPORT_H

int connect_tcp(const char *host, const char *port);
int send_frame(int fd, const char *json);
char *read_frame(int fd);

#endif
