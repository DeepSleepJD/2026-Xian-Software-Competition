"""pathing 单测：官方样例地图上验证成本模型与选路。"""

import json
import unittest
from pathlib import Path

from lychee import pathing
from lychee.state import GameState

REFS = Path(__file__).resolve().parents[2] / "refs" / "debug-kit-v1"


def make_state() -> GameState:
    with open(REFS / "start消息.json", encoding="utf-8") as f:
        data = json.load(f)["msg_data"]
    state = GameState(1001)
    state.update_start(data)
    return state


class EdgeFramesTests(unittest.TestCase):
    def test_formula(self) -> None:
        # 到站需求 = ceil(30×1380) = 41400 → ceil(41400/1000) = 42 帧
        self.assertEqual(42, pathing.edge_frames(30, "ROAD"))
        self.assertEqual(38, pathing.edge_frames(30, "WATER"))

    def test_acceleration_reduces_frames(self) -> None:
        self.assertLess(pathing.edge_frames(30, "ROAD", 1200), pathing.edge_frames(30, "ROAD"))


class ShortestPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = make_state()

    def test_start_to_terminal_prefers_water(self) -> None:
        # 策略文档路线定量：水路(S04/S05)比官道(S03/S07)、山路(S06/S08)更快
        path = pathing.shortest_path(self.state, "S01", "S15")
        self.assertIsNotNone(path)
        self.assertEqual("S01", path[0])
        self.assertEqual("S15", path[-1])
        self.assertIn("S04", path)
        self.assertNotIn("S06", path)
        # 必经宫门
        self.assertIn("S14", path)

    def test_avoid_reroutes(self) -> None:
        base = pathing.shortest_path(self.state, "S01", "S15")
        detour = pathing.shortest_path(self.state, "S01", "S15", frozenset({"S04"}))
        self.assertIsNotNone(detour)
        self.assertNotIn("S04", detour)
        self.assertGreaterEqual(pathing.path_frames(self.state, detour),
                                pathing.path_frames(self.state, base))

    def test_unreachable_returns_none(self) -> None:
        self.assertIsNone(pathing.shortest_path(self.state, "S01", "NO_SUCH"))

    def test_whole_route_within_budget(self) -> None:
        # 策略文档：水路全程（含处理）约 400 帧出头，600 帧内充裕
        path = pathing.shortest_path(self.state, "S01", "S15")
        frames = pathing.path_frames(self.state, path)
        self.assertLess(frames, 500)
        self.assertGreater(frames, 200)


if __name__ == "__main__":
    unittest.main()
