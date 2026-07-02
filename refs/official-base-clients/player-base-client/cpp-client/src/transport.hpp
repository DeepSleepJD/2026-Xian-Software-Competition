#ifndef LYCHEE_TRANSPORT_HPP
#define LYCHEE_TRANSPORT_HPP

#include <optional>
#include <string>

int connect_tcp(const std::string &host, const std::string &port);
void send_frame(int fd, const std::string &json);
std::optional<std::string> read_frame(int fd);

#endif
