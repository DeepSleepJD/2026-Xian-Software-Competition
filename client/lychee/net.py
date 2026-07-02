"""TCP 连接与分帧：5 位十进制长度前缀 + UTF-8 JSON body。

framing 移植自官方参考件（refs/official-base-clients/.../framing.py，已验证可靠）：
read_exact 循环收满字节，天然处理半包；每帧按长度前缀读取，天然处理粘包。
"""

import json
import socket
import time
from typing import Any

MAX_BODY = 99999


def read_exact(sock: socket.socket, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise EOFError("connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket) -> dict:
    prefix = read_exact(sock, 5)
    try:
        length = int(prefix.decode("ascii"))
    except ValueError as exc:
        raise ValueError(f"invalid frame prefix: {prefix!r}") from exc
    if length < 0 or length > MAX_BODY:
        raise ValueError(f"invalid frame length: {length}")
    body = read_exact(sock, length)
    return json.loads(body.decode("utf-8"))


def write_frame(sock: socket.socket, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BODY:
        raise ValueError(f"message too large: {len(body)}")
    sock.sendall(f"{len(body):05d}".encode("ascii") + body)


class Connection:
    """带重试的 TCP 连接封装。runtime 只依赖 read()/write()/close() 三个方法（可用假对象替换做测试）。"""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    @classmethod
    def open(cls, host: str, port: int, connect_wait: float = 15.0, io_timeout: float = 120.0) -> "Connection":
        """连接服务端。客户端可能先于服务端就绪，故在 connect_wait 秒内重试。"""
        deadline = time.monotonic() + connect_wait
        while True:
            try:
                sock = socket.create_connection((host, port), timeout=5.0)
                sock.settimeout(io_timeout)
                return cls(sock)
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

    def read(self) -> dict:
        return read_frame(self._sock)

    def write(self, message: dict[str, Any]) -> None:
        write_frame(self._sock, message)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
