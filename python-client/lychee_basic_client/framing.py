import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Optional

MAX_BODY = 99999
DIAGNOSTIC_ENV = "LYCHEE_FRAME_DIAGNOSTICS"
DEFAULT_DIAGNOSTIC_PATH = "malformed_frames.jsonl"
DIAGNOSTIC_SAMPLE_BYTES = 200


class FrameDecodeError(ValueError):
    def __init__(
        self,
        message: str,
        diagnostic_path: str,
        partial_message: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_path = diagnostic_path
        self.partial_message = partial_message or {}


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
        diagnostic_path = _write_frame_diagnostic("invalid_prefix", prefix, None, b"", exc)
        raise FrameDecodeError(f"invalid frame prefix: {prefix!r}", diagnostic_path) from exc
    if length < 0 or length > MAX_BODY:
        diagnostic_path = _write_frame_diagnostic("invalid_length", prefix, length, b"", None)
        raise FrameDecodeError(f"invalid frame length: {length}", diagnostic_path)
    body = read_exact(sock, length)
    try:
        decoded = body.decode("utf-8")
        return json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        diagnostic_path = _write_frame_diagnostic("invalid_json", prefix, length, body, exc)
        partial_message = _extract_partial_message(body)
        raise FrameDecodeError(f"invalid frame JSON: {exc}", diagnostic_path, partial_message) from exc


def write_frame(sock: socket.socket, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_BODY:
        raise ValueError(f"message too large: {len(body)}")
    sock.sendall(f"{len(body):05d}".encode("ascii") + body)


def _write_frame_diagnostic(
    reason: str,
    prefix: bytes,
    length: Optional[int],
    body: bytes,
    error: Optional[BaseException],
) -> str:
    path = os.environ.get(DIAGNOSTIC_ENV, DEFAULT_DIAGNOSTIC_PATH)
    record = {
        "loggedAt": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "prefixAscii": prefix.decode("ascii", errors="replace"),
        "prefixRepr": repr(prefix),
        "declaredLength": length,
        "bodyBytes": len(body),
        "bodySha256": sha256(body).hexdigest() if body else "",
        "bodyHead": _sample_bytes(body[:DIAGNOSTIC_SAMPLE_BYTES]),
        "bodyTail": _sample_bytes(body[-DIAGNOSTIC_SAMPLE_BYTES:]) if body else "",
        "errorType": type(error).__name__ if error else "",
        "error": str(error) if error else "",
    }
    try:
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        print(f"failed to write malformed frame diagnostic {path}: {exc}", file=sys.stderr)
    return path


def _sample_bytes(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _extract_partial_message(body: bytes) -> dict[str, Any]:
    decoded = body.decode("utf-8", errors="replace")
    partial: dict[str, Any] = {}

    msg_name = _extract_string(decoded, "msg_name")
    if msg_name:
        partial["msg_name"] = msg_name

    match_id = _extract_string(decoded, "matchId")
    if match_id:
        partial["matchId"] = match_id

    round_no = _extract_int(decoded, "round")
    if round_no is not None:
        partial["round"] = round_no

    return partial


def _extract_string(decoded: str, key: str) -> Optional[str]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', decoded)
    return match.group(1) if match else None


def _extract_int(decoded: str, key: str) -> Optional[int]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+)', decoded)
    return int(match.group(1)) if match else None
