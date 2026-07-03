import json
import socket
import sys
from typing import Any, Optional

from . import __version__
from .battle_logger import BattleLogger
from .config import Config
from .framing import read_frame, write_frame
from . import messages as M
from .recorder import MatchRecorder
from .strategy import Strategy


def _make_strategy(config: Config) -> Strategy:
    if config.strategy == "aggressive":
        from .sparring import AggressiveStrategy
        return AggressiveStrategy(config.player_id)
    return Strategy(config.player_id)


class ClientSession:
    def __init__(self, sock: socket.socket, config: Config) -> None:
        self._sock = sock
        self._config = config
        self._match_id = ""
        self._strategy = _make_strategy(config)
        self._battle_logger = BattleLogger(config.player_id)
        self._recorder = (
            MatchRecorder(config.record_dir, config.player_id)
            if config.record_dir
            else None
        )

    def run(self) -> int:
        self._send_registration()

        while True:
            try:
                message = read_frame(self._sock)
            except EOFError:
                print("connection closed")
                self._close_recorder()
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
            self._battle_logger.log_message("over", data)
            if self._recorder is not None:
                self._recorder.record_over(data)
            self._close_recorder()
            return 0
        elif msg_name == "error":
            # non-fatal: an error about one action must NOT make us disconnect
            # (disconnect = offline = retire). Log it and keep playing; if the
            # server really drops us, read_frame will EOF and we exit cleanly.
            print(f"error received: {json.dumps(message, ensure_ascii=False)}", file=sys.stderr)
            self._battle_logger.log_message("error", data)
        else:
            print(f"ignored msg_name={msg_name}")
        return None

    def _handle_start(self, data: dict[str, Any]) -> None:
        self._match_id = data["matchId"]
        round_no = data["round"]
        # stamp the build into the log so any report/inspect can name the version
        self._battle_logger.log_message(
            "client", {"version": __version__, "playerId": self._config.player_id}
        )
        self._battle_logger.log_message("start", data)
        self._strategy.ingest_start(data)
        print(f"start match={self._match_id} round={round_no}")
        write_frame(self._sock, M.ready_message(self._match_id, round_no, self._config.player_id))

    def _handle_inquire(self, data: dict[str, Any]) -> None:
        round_no = data["round"]
        if self._recorder is not None:
            self._recorder.record_inquire(data)
        actions = self._strategy.decide(data)
        self._log_state(round_no, data, actions)
        message = M.action_message(self._match_id, round_no, self._config.player_id, actions)
        self._battle_logger.log_round(data, message["msg_data"])
        write_frame(self._sock, message)

    def _close_recorder(self) -> None:
        if self._recorder is not None:
            self._recorder.close()
            if self._recorder.path:
                print(f"recorded {self._recorder.rounds} rounds -> {self._recorder.path}")
            self._recorder = None

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
                f"good={me.get('goodFruit')} verified={me.get('verified')} -> {act}"
            )
