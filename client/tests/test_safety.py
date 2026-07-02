"""safety 单测：「送达优先」硬约束的到终点帧数与触发边界。

地图：A —(ROAD d=2, 3帧)— B —(ROAD d=2, 3帧)— C(终点)，无处理节点，
A 到终点 = 6 帧整，边界数字可手算。
"""

import unittest

from lychee.state import GameState
from lychee.strategy import safety

MY_ID = 1001

START = {
    "matchId": "safety-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "STATION"},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "A", "terminalNodeIds": ["C"]}}},
}


def inquire(round_no: int, *, node: str = "A", state: str = "IDLE",
            next_node: str = "", move_dir: str = "",
            progress_ms: int = 0, total_ms: int = 0) -> dict:
    return {
        "round": round_no,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "moveDirection": move_dir,
                     "edgeProgressMs": progress_ms, "edgeTotalMs": total_ms}],
    }


class SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)

    def load(self, inq: dict) -> GameState:
        self.state.update_inquire(inq)
        return self.state

    def test_frames_to_terminal_docked(self) -> None:
        state = self.load(inquire(10, node="A"))
        self.assertEqual(6, safety.frames_to_terminal(state))

    def test_frames_to_terminal_mid_edge(self) -> None:
        # A→B 边走掉 760/2760ms：剩 2000ms = 2 帧，再加 B→C 3 帧
        state = self.load(inquire(10, node="A", state="MOVING", next_node="B",
                                  progress_ms=760, total_ms=2760))
        self.assertEqual(5, safety.frames_to_terminal(state))

    def test_frames_to_terminal_paused_mid_edge(self) -> None:
        # 被守卫暂停（WAITING+PAUSED）与移动中同账：从 next_node_id 起算
        state = self.load(inquire(10, node="A", state="WAITING", next_node="B",
                                  move_dir="PAUSED", progress_ms=760, total_ms=2760))
        self.assertEqual(5, safety.frames_to_terminal(state))

    def test_must_rush_boundary(self) -> None:
        # A 到终点 6 帧 + 余量 60：533+6+60=599 < 600 不触发，534 起触发
        self.assertFalse(safety.must_rush(self.load(inquire(533, node="A"))))
        self.assertTrue(safety.must_rush(self.load(inquire(534, node="A"))))

    def test_must_rush_when_position_unknown(self) -> None:
        # 位置缺失/不可达 → 视同时间不够，停止一切绕路
        self.assertTrue(safety.must_rush(self.load(inquire(10, node=""))))


if __name__ == "__main__":
    unittest.main()
