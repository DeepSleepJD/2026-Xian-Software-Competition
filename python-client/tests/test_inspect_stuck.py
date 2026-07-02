import json
import os
import tempfile
import unittest

from lychee_basic_client.inspect_stuck import build_report


def _line(obj):
    return json.dumps(obj, ensure_ascii=False) + "\n"


class InspectStuckTests(unittest.TestCase):
    def _write(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_line({"type": "start", "playerId": 1001, "payload": {"matchId": "m"}}))
            # a clean round
            fh.write(_line({
                "type": "round", "playerId": 1001,
                "clientAction": {"actions": [{"action": "MOVE", "targetNodeId": "S02"}]},
                "inquire": {
                    "round": 1, "nodes": [], "events": [],
                    "players": [{"playerId": 1001, "state": "MOVING", "currentNodeId": "S01"}],
                    "actionResults": [{"playerId": 1001, "action": "MOVE", "accepted": True}],
                },
            }))
            # a stuck round: our FORCED_PASS rejected, guard event present
            fh.write(_line({
                "type": "round", "playerId": 1001,
                "clientAction": {"actions": [{"action": "FORCED_PASS", "targetNodeId": "S10"}]},
                "inquire": {
                    "round": 2,
                    "nodes": [{"nodeId": "S10", "guardBlockCount": 1}],
                    "events": [{"type": "GUARD_SET", "payload": {"playerId": 2002, "nodeId": "S10"}}],
                    "players": [{"playerId": 1001, "state": "MOVING",
                                 "currentNodeId": "S09", "nextNodeId": "S10", "routeEdgeId": "E1"}],
                    "actionResults": [{"playerId": 1001, "action": "FORCED_PASS",
                                       "accepted": False, "result": "ACTION_REJECTED",
                                       "errorCode": "MOVING_ACTION_FORBIDDEN"}],
                },
            }))
        return path

    def test_finds_stuck_region_and_guard(self) -> None:
        path = self._write()
        try:
            report = build_report(path, before=3, after=8)
        finally:
            os.remove(path)
        self.assertIn("me_id = 1001", report)
        self.assertIn("stuck_idx = 1", report)          # second round (index 1) is stuck
        self.assertIn("MOVING_ACTION_FORBIDDEN", report)
        self.assertIn("GUARD_SET", report)
        self.assertIn("guardBlockCount", report)         # target node fields dumped


if __name__ == "__main__":
    unittest.main()
