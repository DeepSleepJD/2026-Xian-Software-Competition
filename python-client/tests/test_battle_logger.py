import json
import tempfile
import unittest
from pathlib import Path

from lychee_basic_client.battle_logger import BattleLogger


class BattleLoggerTests(unittest.TestCase):
    def test_log_round_writes_inquire_summary_and_client_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "battle_rounds.jsonl"
            logger = BattleLogger(player_id=1001, log_path=log_path)

            logger.log_round(
                {
                    "matchId": "match-1",
                    "round": 7,
                    "tick": 6,
                    "phase": "NORMAL",
                    "players": [
                        {
                            "playerId": 1001,
                            "teamId": "RED",
                            "state": "IDLE",
                            "currentNodeId": "S01",
                            "freshness": 95,
                            "goodFruit": 90,
                            "badFruit": 10,
                            "totalScore": 123,
                        },
                        {
                            "playerId": 2002,
                            "teamId": "BLUE",
                            "state": "MOVING",
                            "currentNodeId": "S02",
                        },
                    ],
                    "events": [{"type": "MOVE_PROGRESS"}],
                    "actionResults": [{"playerId": 1001, "accepted": True}],
                    "contests": [{"contestId": "C_001"}],
                    "tasks": [{"taskId": "T_001", "active": True}],
                    "scorePreview": {"RED": 123, "BLUE": 98},
                    "debug": {"localOnly": True},
                },
                {
                    "matchId": "match-1",
                    "round": 7,
                    "playerId": 1001,
                    "actions": [{"action": "MOVE", "targetNodeId": "S02"}],
                },
            )

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            entry = json.loads(lines[0])

            self.assertEqual("match-1", entry["matchId"])
            self.assertEqual(7, entry["round"])
            self.assertEqual([{"action": "MOVE", "targetNodeId": "S02"}], entry["clientAction"]["actions"])
            self.assertEqual("RED", entry["summary"]["ownPlayer"]["teamId"])
            self.assertEqual("BLUE", entry["summary"]["opponents"][0]["teamId"])
            self.assertEqual([{"contestId": "C_001"}], entry["summary"]["contests"])
            self.assertNotIn("debug", entry["inquire"])

    def test_log_message_records_start_and_over_without_debug(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "battle_rounds.jsonl"
            logger = BattleLogger(player_id=1001, log_path=log_path)

            logger.log_message("start", {"matchId": "m", "map": {"nodes": []}, "debug": {"x": 1}})
            logger.log_message("over", {"matchId": "m", "winnerPlayerId": 1001, "players": []})

            entries = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(["start", "over"], [e["type"] for e in entries])
            self.assertIn("map", entries[0]["payload"])
            self.assertNotIn("debug", entries[0]["payload"])
            self.assertEqual(1001, entries[1]["payload"]["winnerPlayerId"])


if __name__ == "__main__":
    unittest.main()
