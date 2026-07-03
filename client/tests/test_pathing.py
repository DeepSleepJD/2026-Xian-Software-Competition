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

    def test_choke_nodes_from_start_to_terminal(self) -> None:
        chokepoints = pathing.choke_nodes(self.state, "S01", "S15")
        self.assertIn("S10", chokepoints)
        self.assertIn("S14", chokepoints)
        self.assertNotIn("S04", chokepoints)

    def test_enemy_guard_adds_path_penalty(self) -> None:
        base_path = ["S09", "S10", "S11", "S12", "S13", "S14", "S15"]
        base = pathing.path_frames(self.state, base_path)

        guarded = make_state()
        guarded.update_inquire({
            "round": 320,
            "players": [{"playerId": 1001, "teamId": "RED", "state": "IDLE",
                         "currentNodeId": "S09", "goodFruit": 90, "badFruit": 2}],
            "nodes": [{"nodeId": "S10", "guard": {"active": True, "ownerTeamId": "BLUE",
                                                   "defense": 6, "initialDefense": 6,
                                                   "ageRound": 0}}],
        })
        self.assertEqual(base + 1, pathing.path_frames(guarded, base_path))

    def test_hot_weather_increases_freshness_cost_without_slowing_road(self) -> None:
        base_fresh, base_frames = pathing.path_cost(self.state, ["S09", "S10"])
        hot = make_state()
        hot.update_inquire({"round": 100, "weather": {
            "active": [{"weatherId": "W1", "type": "HOT", "region": "ALL",
                        "remainRound": 20}]}})
        fresh, frames = pathing.path_cost(hot, ["S09", "S10"])
        self.assertEqual(base_frames, frames)
        self.assertGreater(fresh, base_fresh)

    def test_heavy_rain_slows_water_edges(self) -> None:
        base = pathing.path_frames(self.state, ["S04", "S05"])
        rainy = make_state()
        rainy.update_inquire({"round": 100, "weather": {
            "active": [{"weatherId": "W2", "type": "HEAVY_RAIN", "region": "WATER",
                        "remainRound": 20}]}})
        self.assertGreater(pathing.path_frames(rainy, ["S04", "S05"]), base)

    def test_mountain_fog_slows_mountain_edges(self) -> None:
        base = pathing.path_frames(self.state, ["S06", "S08"])
        foggy = make_state()
        foggy.update_inquire({"round": 100, "weather": {
            "active": [{"weatherId": "W3", "type": "MOUNTAIN_FOG", "region": "MOUNTAIN",
                        "remainRound": 20}]}})
        self.assertGreater(pathing.path_frames(foggy, ["S06", "S08"]), base)

    def test_forecast_weather_penalizes_imminent_matching_edge(self) -> None:
        base = pathing.path_frames(self.state, ["S04", "S05"])
        rainy = make_state()
        rainy.update_inquire({"round": 100, "weather": {
            "forecast": [{"weatherId": "W4", "type": "HEAVY_RAIN", "region": "WATER",
                          "startRound": 120, "durationRound": 60}]}})
        self.assertGreater(pathing.path_frames(rainy, ["S04", "S05"]), base)


# 直线图 A —(ROAD d=2, 3帧)— B(处理站 pr=5) — C，帧数可手算
MIN_FRAMES_START = {
    "matchId": "minframes-test",
    "durationRound": 600,
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
    "map": {"gameplay": {
        "roles": {"startNodeId": "A", "terminalNodeIds": ["C"]},
        "processNodes": [{"nodeId": "B", "processType": "TRANSFER", "processRound": 5}],
    }},
}


class MinFramesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(1001)
        self.state.update_start(MIN_FRAMES_START)

    def test_linear_graph_frames_include_processing(self) -> None:
        # A→B 移动 3 帧 + B 处理 5 帧 + B→C 移动 3 帧 = 11
        self.assertEqual(11, pathing.min_frames(self.state, "A", "C"))
        # 到中途处理站 B：3 移动 + 5 处理
        self.assertEqual(8, pathing.min_frames(self.state, "A", "B"))

    def test_zero_and_unreachable(self) -> None:
        self.assertEqual(0, pathing.min_frames(self.state, "A", "A"))
        self.assertEqual(pathing.INF_FRAMES, pathing.min_frames(self.state, "A", "NOPE"))
        self.assertEqual(pathing.INF_FRAMES, pathing.min_frames(self.state, "NOPE", "C"))

    def test_min_frames_from_single_source(self) -> None:
        allf = pathing.min_frames_from(self.state, "A")
        self.assertEqual(0, allf["A"])
        self.assertEqual(8, allf["B"])
        self.assertEqual(11, allf["C"])


class MinFramesVsShortestPathTests(unittest.TestCase):
    """帧数线可能选出不同于鲜度线的路（设计 test #2）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.state = make_state()

    def test_frames_first_can_beat_freshness_path_frames(self) -> None:
        # 鲜度优先路（水路）帧数不是全局最少；纯帧数线更短
        fresh_path = pathing.shortest_path(self.state, "S01", "S15")
        fresh_frames = pathing.path_frames(self.state, fresh_path)
        frames_first = pathing.min_frames(self.state, "S01", "S15")
        self.assertLess(frames_first, fresh_frames)

    def test_horse_move_per_frame_reduces_frames(self) -> None:
        # 长路程上马匹（1200/帧）显著减少帧数
        base = pathing.min_frames(self.state, "S01", "S15")
        fast = pathing.min_frames(self.state, "S01", "S15", 1200)
        self.assertLess(fast, base)


if __name__ == "__main__":
    unittest.main()
