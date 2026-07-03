import json
import socket
import sys
from typing import Any, Optional

from .battle_logger import BattleLogger
from .config import Config
from .framing import FrameDecodeError, read_frame, write_frame
from .messages import action_message, heartbeat_action, ready_message, registration_message
from .strategy import MovementStrategy

MAX_CONSECUTIVE_MALFORMED_FRAMES = 3


class ClientSession:
    def __init__(self, sock: socket.socket, config: Config) -> None:
        self._sock = sock
        self._config = config
        self._match_id = ""
        self._strategy = MovementStrategy(config.player_id)
        self._battle_logger = BattleLogger(config.player_id)

    def run(self) -> int:
        self._send_registration()
        malformed_frames = 0

        while True:
            try:
                message = read_frame(self._sock)
            except EOFError:
                print("connection closed")
                return 0
            except FrameDecodeError as exc:
                if self._send_recovery_heartbeat(exc):
                    malformed_frames = 0
                    continue
                malformed_frames += 1
                self._report_malformed_frame(exc, malformed_frames)
                if malformed_frames >= MAX_CONSECUTIVE_MALFORMED_FRAMES:
                    return 1
                continue
            malformed_frames = 0

            result = self._handle_message(message)
            if result is not None:
                return result

    def _send_registration(self) -> None:
        write_frame(self._sock, registration_message(self._config))

    def _handle_message(self, message: dict[str, Any]) -> Optional[int]:
        msg_name = message.get("msg_name")
        data = message.get("msg_data") or {}

        if msg_name == "start":
            self._handle_start(data)
        elif msg_name == "inquire":
            self._handle_inquire(data)
        elif msg_name == "over":
            print("over received")
            return 0
        elif msg_name == "error":
            print(f"error received: {json.dumps(message, ensure_ascii=False)}", file=sys.stderr)
            return 1
        else:
            print(f"ignored msg_name={msg_name}")
        return None

    def _handle_start(self, data: dict[str, Any]) -> None:
        self._match_id = data["matchId"]
        round_no = data["round"]
        self._strategy.update_start(data)
        print(f"start match={self._match_id} round={round_no}")
        write_frame(self._sock, ready_message(self._match_id, round_no, self._config.player_id))

    def _handle_inquire(self, data: dict[str, Any]) -> None:
        round_no = data["round"]
        actions = self._strategy.choose_action(data)
        if actions:
            print(f"inquire round={round_no} -> {actions[0]['action']}")
            message = action_message(self._match_id, round_no, self._config.player_id, actions)
            self._battle_logger.log_round(data, message["msg_data"])
            write_frame(self._sock, message)
            return

        print(f"inquire round={round_no} -> heartbeat")
        message = heartbeat_action(self._match_id, round_no, self._config.player_id)
        self._battle_logger.log_round(data, message["msg_data"])
        write_frame(self._sock, message)

    def _send_recovery_heartbeat(self, exc: FrameDecodeError) -> bool:
        partial = exc.partial_message
        if partial.get("msg_name") != "inquire":
            return False
        round_no = partial.get("round")
        if not isinstance(round_no, int):
            return False
        match_id = partial.get("matchId") if isinstance(partial.get("matchId"), str) else self._match_id
        if not match_id:
            return False

        print(
            f"malformed inquire recovered with heartbeat: round={round_no}; diagnostic={exc.diagnostic_path}",
            file=sys.stderr,
        )
        write_frame(self._sock, heartbeat_action(match_id, round_no, self._config.player_id))
        return True

    def _report_malformed_frame(self, exc: FrameDecodeError, malformed_frames: int) -> None:
        print(
            f"malformed frame skipped ({malformed_frames}/{MAX_CONSECUTIVE_MALFORMED_FRAMES}): "
            f"{exc}; diagnostic={exc.diagnostic_path}",
            file=sys.stderr,
        )
