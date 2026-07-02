import json
import os
import tempfile
import unittest

from lychee_basic_client.analyze import analyze_file, format_report


def _line(obj):
    return json.dumps(obj, ensure_ascii=False) + "\n"


class AnalyzeTests(unittest.TestCase):
    def _write_recording(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_line({"kind": "meta", "playerId": 1001, "matchId": "m"}))
            fh.write(_line({
                "kind": "inquire", "round": 1, "matchId": "m",
                "weather": {"active": []}, "tasks": [], "actionResults": [],
                "players": [
                    {"playerId": 1001, "state": "MOVING", "routeType": "ROAD",
                     "freshness": 100.0, "goodFruit": 100, "delivered": False,
                     "buffs": [], "scoreDetail": {"total": 0}},
                    {"playerId": 2002, "state": "MOVING", "routeType": "WATER",
                     "freshness": 100.0, "goodFruit": 100, "delivered": False,
                     "buffs": [], "scoreDetail": {"total": 0}},
                ],
            }))
            fh.write(_line({
                "kind": "inquire", "round": 2, "matchId": "m",
                "weather": {"active": []},
                "tasks": [{"taskId": "T1", "completed": True, "ownerPlayerId": 1001, "score": 30}],
                "actionResults": [
                    {"playerId": 2002, "action": "MOVE", "accepted": False, "result": "REJ"},
                ],
                "players": [
                    {"playerId": 1001, "state": "PROCESSING", "freshness": 99.0,
                     "goodFruit": 100, "delivered": False, "buffs": [], "scoreDetail": {"total": 0}},
                    {"playerId": 2002, "state": "RESTING", "freshness": 98.0,
                     "goodFruit": 100, "delivered": False, "buffs": [], "scoreDetail": {"total": 0}},
                ],
            }))
            fh.write(_line({
                "kind": "over", "matchId": "m", "resultType": "NORMAL",
                "overReason": "ALL_DELIVERED", "winnerPlayerId": 1001,
                "players": [
                    {"playerId": 1001, "delivered": True, "deliverRound": 400,
                     "freshness": 70.0, "goodFruit": 90, "totalScore": 500,
                     "scoreDetail": {"delivery": 240, "tasks": 120, "goodFruit": 162,
                                     "freshness": 126, "time": 40, "bounty": 0,
                                     "penalty": 0, "total": 500}},
                    {"playerId": 2002, "delivered": True, "deliverRound": 380,
                     "freshness": 72.0, "goodFruit": 88, "totalScore": 560,
                     "scoreDetail": {"delivery": 240, "tasks": 60, "goodFruit": 158,
                                     "freshness": 130, "time": 52, "bounty": 0,
                                     "penalty": 0, "total": 560}},
                ],
            }))
        return path

    def test_analyze_uses_over_and_breaks_down_frames(self) -> None:
        path = self._write_recording()
        try:
            a = analyze_file(path)
        finally:
            os.remove(path)

        self.assertEqual(1001, a["my_id"])
        self.assertEqual(2002, a["opp_id"])
        self.assertEqual(1001, a["winner_id"])
        # final scores come from `over`
        self.assertEqual(500, a["my_detail"]["total"])
        self.assertEqual(560, a["opp_detail"]["total"])
        # delivery info from `over`
        self.assertEqual(400, a["my_delivery"]["round"])
        # task tally
        self.assertEqual((1, 30), a["task_done"][1001])
        # opponent's rejected action counted
        self.assertIn(2002, a["rejects"])
        self.assertTrue(a["rejects"][2002])
        # frame breakdown: I moved on ROAD once + processed once; opp moved WATER + rested
        my_bd = a["breakdown"][1001]
        self.assertEqual(1, my_bd["move_by_rt"].get("ROAD"))
        self.assertEqual(1, my_bd["buckets"]["process"])
        self.assertEqual(1, a["breakdown"][2002]["buckets"]["waste"])

    def test_reads_battle_logger_format(self) -> None:
        # BattleLogger format: {"type":"round"/"start"/"over", ...}
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_line({"type": "start", "playerId": 1001, "payload": {"matchId": "m"}}))
            fh.write(_line({
                "type": "round", "playerId": 1001, "round": 1,
                "clientAction": {"actions": []},
                "inquire": {
                    "round": 1, "weather": {"active": []}, "tasks": [],
                    "players": [
                        {"playerId": 1001, "state": "MOVING", "routeType": "ROAD",
                         "freshness": 100.0, "goodFruit": 100, "delivered": False},
                        {"playerId": 2002, "state": "MOVING", "freshness": 100.0,
                         "goodFruit": 100, "delivered": False},
                    ],
                    "events": [{"type": "RUSH_TACTIC_USE",
                                "payload": {"playerId": 1001, "rushTactic": "RUSH_PROTECT"}}],
                },
            }))
            fh.write(_line({"type": "over", "payload": {
                "matchId": "m", "resultType": "NORMAL", "winnerPlayerId": 1001,
                "players": [
                    {"playerId": 1001, "delivered": True, "scoreDetail": {"total": 500}},
                    {"playerId": 2002, "delivered": True, "scoreDetail": {"total": 400}},
                ],
            }}))
        try:
            a = analyze_file(path)
        finally:
            os.remove(path)
        self.assertEqual(1001, a["my_id"])
        self.assertEqual(1001, a["winner_id"])
        self.assertEqual(500, a["my_detail"]["total"])
        self.assertEqual("RUSH_PROTECT", a["tactics"]["rush_tactic"])

    def test_format_report_runs(self) -> None:
        path = self._write_recording()
        try:
            report = format_report(analyze_file(path))
        finally:
            os.remove(path)
        self.assertIn("失分点", report)
        self.assertIn("L2", report)


if __name__ == "__main__":
    unittest.main()
