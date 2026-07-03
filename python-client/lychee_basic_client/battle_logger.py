import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "battle_rounds.jsonl"
_LOG_DIR = DEFAULT_LOG_PATH.parent


class BattleLogger:
    def __init__(self, player_id: int, log_path: Path = None) -> None:
        self._player_id = player_id
        # per-player filename so two clients on one box (e.g. the sparring harness)
        # don't fight over the same file and stall each other into a timeout.
        self._log_path = log_path or (_LOG_DIR / f"battle_rounds_{player_id}.jsonl")
        self._enabled = True

    @property
    def log_path(self) -> Path:
        return self._log_path

    def log_message(self, message_type: str, payload: dict[str, Any]) -> None:
        """Record a full non-inquire message verbatim (start / over / error) so the
        log is self-contained: start carries the whole map, over the authoritative
        final scores (which the per-round preview never credits for the last
        deliverer). Keeps the log complete for offline analysis."""
        if not self._enabled:
            return
        self._append_entry(
            {
                "loggedAt": datetime.now(timezone.utc).isoformat(),
                "type": message_type,
                "playerId": self._player_id,
                "payload": self._strip_local_debug(payload),
            }
        )

    def log_round(self, inquire_data: dict[str, Any], action_payload: dict[str, Any]) -> None:
        if not self._enabled:
            return

        entry = {
            "loggedAt": datetime.now(timezone.utc).isoformat(),
            "type": "round",
            "matchId": inquire_data.get("matchId"),
            "round": inquire_data.get("round"),
            "tick": inquire_data.get("tick"),
            "phase": inquire_data.get("phase"),
            "playerId": self._player_id,
            "clientAction": action_payload,
            "summary": self._summary(inquire_data),
            "inquire": self._strip_local_debug(inquire_data),
        }
        self._append_entry(entry)

    def _append_entry(self, entry: dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        except OSError as exc:
            self._enabled = False
            print(f"battle logger disabled: {exc}", file=sys.stderr)

    def _summary(self, data: dict[str, Any]) -> dict[str, Any]:
        players = data.get("players", []) or []
        own_player = self._find_own_player(players)
        return {
            "ownPlayer": self._player_summary(own_player),
            "opponents": [
                self._player_summary(player)
                for player in players
                if isinstance(player, dict) and player.get("playerId") != self._player_id
            ],
            "scorePreview": data.get("scorePreview", {}),
            "weather": data.get("weather", {}),
            "events": data.get("events", []) or [],
            "actionResults": data.get("actionResults", []) or [],
            "contests": data.get("contests", []) or [],
            "activeTasks": [
                task
                for task in data.get("tasks", []) or []
                if isinstance(task, dict) and task.get("active") is not False
            ],
        }

    def _find_own_player(self, players: list[Any]) -> dict[str, Any]:
        for player in players:
            if isinstance(player, dict) and player.get("playerId") == self._player_id:
                return player
        return {}

    def _player_summary(self, player: dict[str, Any]) -> dict[str, Any]:
        return {
            "playerId": player.get("playerId"),
            "teamId": player.get("teamId"),
            "state": player.get("state"),
            "currentNodeId": player.get("currentNodeId"),
            "nextNodeId": player.get("nextNodeId"),
            "routeEdgeId": player.get("routeEdgeId"),
            "moveProgress": player.get("moveProgress"),
            "freshness": player.get("freshness"),
            "goodFruit": player.get("goodFruit"),
            "badFruit": player.get("badFruit"),
            "verified": player.get("verified"),
            "delivered": player.get("delivered"),
            "resources": player.get("resources", {}),
            "buffs": player.get("buffs", []),
            "totalScore": player.get("totalScore"),
            "taskScore": player.get("taskScore"),
            "bountyScore": player.get("bountyScore"),
            "scoreDetail": player.get("scoreDetail", {}),
            "illegalActionCount": player.get("illegalActionCount"),
            "penaltyScore": player.get("penaltyScore"),
        }

    def _strip_local_debug(self, data: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in data.items() if key != "debug"}
