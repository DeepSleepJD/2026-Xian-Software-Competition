#include "transport.hpp"

#include <arpa/inet.h>
#include <netdb.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <stdexcept>

namespace {

constexpr int kMaxBody = 99999;

void write_all(int fd, const std::string &data) {
    std::size_t written = 0;
    while (written < data.size()) {
        ssize_t n = send(fd, data.data() + written, data.size() - written, 0);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(std::string("send failed: ") + std::strerror(errno));
        }
        if (n == 0) {
            throw std::runtime_error("socket closed while sending");
        }
        written += static_cast<std::size_t>(n);
    }
}

bool read_exact(int fd, char *buffer, std::size_t len) {
    std::size_t read_len = 0;
    while (read_len < len) {
        ssize_t n = recv(fd, buffer + read_len, len - read_len, 0);
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(std::string("recv failed: ") + std::strerror(errno));
        }
        if (n == 0) {
            return false;
        }
        read_len += static_cast<std::size_t>(n);
    }
    return true;
}

}  // namespace

int connect_tcp(const std::string &host, const std::string &port) {
    addrinfo hints {};
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    addrinfo *result = nullptr;
    int err = getaddrinfo(host.c_str(), port.c_str(), &hints, &result);
    if (err != 0) {
        throw std::runtime_error(gai_strerror(err));
    }

    int fd = -1;
    for (addrinfo *rp = result; rp != nullptr; rp = rp->ai_next) {
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
    if (fd < 0) {
        throw std::runtime_error("connect failed");
    }
    return fd;
}

void send_frame(int fd, const std::string &json) {
    if (json.size() > kMaxBody) {
        throw std::runtime_error("message too large");
    }
    char prefix[6];
    std::snprintf(prefix, sizeof(prefix), "%05zu", json.size());
    write_all(fd, std::string(prefix, 5));
    write_all(fd, json);
}

std::optional<std::string> read_frame(int fd) {
    char prefix[6] {};
    if (!read_exact(fd, prefix, 5)) {
        return std::nullopt;
    }
    int len = std::stoi(std::string(prefix, 5));
    if (len < 0 || len > kMaxBody) {
        throw std::runtime_error("invalid frame length");
    }
    std::string body(static_cast<std::size_t>(len), '\0');
    if (!read_exact(fd, body.data(), body.size())) {
        return std::nullopt;
    }
    return body;
}
