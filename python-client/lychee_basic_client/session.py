import json
import socket
import sys
from typing import Any, Optional

from .config import Config
from .framing import read_frame, write_frame
from . import messages as M
from .strategy import Strategy


class ClientSession:
    def __init__(self, sock: socket.socket, config: Config) -> None:
        self._sock = sock
        self._config = config
        self._match_id = ""
        self._strategy = Strategy(config.player_id)

    def run(self) -> int:
        self._send_registration()

        while True:
            try:
                message = read_frame(self._sock)
            except EOFError:
                print("connection closed")
                return 0

            result = self._handle_message(message)
            if result is not None:
                return result

    def _send_registration(self) -> None:
        write_frame(self._sock, M.registration_message(self._config))

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
        self._strategy.ingest_start(data)
        print(f"start match={self._match_id} round={round_no}")
        write_frame(self._sock, M.ready_message(self._match_id, round_no, self._config.player_id))

    def _handle_inquire(self, data: dict[str, Any]) -> None:
        round_no = data["round"]
        actions = self._strategy.decide(data)
        self._log_state(round_no, data, actions)
        write_frame(
            self._sock,
            M.action_message(self._match_id, round_no, self._config.player_id, actions),
        )

    def _log_state(self, round_no: int, data: dict[str, Any], actions: list) -> None:
        me = None
        for p in data.get("players", []):
            if p.get("playerId") == self._config.player_id:
                me = p
                break
        if me is None:
            return
        # surface any rejected/failed action results so we can debug fast
        for r in data.get("actionResults", []):
            if r.get("playerId") == self._config.player_id and not r.get("accepted", True):
                print(
                    f"  [rej r{r.get('round')}] {r.get('action')} -> {r.get('result')}",
                    file=sys.stderr,
                )
        act = actions[0]["action"] if actions else "HEARTBEAT"
        if round_no % 25 == 0 or act not in ("MOVE", "HEARTBEAT"):
            fresh = me.get("freshness", 0.0)
            print(
                f"r{round_no} phase={data.get('phase')} node={me.get('currentNodeId')} "
                f"state={me.get('state')} fresh={fresh:.1f} "
                f"good={me.get('goodFruit')} verified={me.get('verified')} "
                f"taskbase={self._strategy.task_base} -> {act}"
            )
