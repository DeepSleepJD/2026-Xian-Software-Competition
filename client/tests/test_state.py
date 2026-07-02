"""GameState 解析单测：夹具为 refs/debug-kit-v1/ 官方样例消息（架构文档第三.4 节）。"""

import json
import unittest
from pathlib import Path

from lychee.state import GameState

REFS = Path(__file__).resolve().parents[2] / "refs" / "debug-kit-v1"
MY_ID = 1001  # 样例消息中的红方玩家


def load_msg_data(filename: str) -> dict:
    with open(REFS / filename, encoding="utf-8") as f:
        return json.load(f)["msg_data"]


class StartParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = GameState(MY_ID)
        cls.state.update_start(load_msg_data("start消息.json"))

    def test_match_meta(self) -> None:
        self.assertEqual("match_20260701_1001_vs_2002_sample", self.state.match_id)
        self.assertEqual(600, self.state.duration_round)

    def test_camp_identification(self) -> None:
        self.assertEqual("RED", self.state.my_team_id)
        self.assertEqual(2002, self.state.opponent_id)

    def test_map_graph(self) -> None:
        self.assertEqual(15, len(self.state.nodes))
        self.assertEqual(21, len(self.state.edges))
        s01 = self.state.nodes["S01"]
        self.assertTrue(s01.is_start)
        self.assertEqual("START", s01.node_type)
        e01 = self.state.edges["E01"]
        self.assertEqual(("S01", "S02", "ROAD", 30), (e01.from_node, e01.to_node, e01.route_type, e01.distance))

    def test_roles(self) -> None:
        self.assertEqual("S01", self.state.roles.start_node_id)
        self.assertIn("S15", self.state.roles.terminal_node_ids)
        self.assertEqual("S14", self.state.roles.gate_node_id)

    def test_resources_fallback_to_gameplay(self) -> None:
        # 样例顶层 resources 为空列表，必须回退到 map.gameplay.resources
        self.assertEqual(20, len(self.state.resource_specs))
        self.assertTrue(all(r.node_id and r.resource_type for r in self.state.resource_specs))

    def test_gameplay_tables(self) -> None:
        self.assertEqual(6, len(self.state.process_nodes))
        self.assertEqual("TRANSFER", self.state.process_nodes["S02"].process_type)
        self.assertEqual(9, len(self.state.task_candidates))
        self.assertEqual(3, len(self.state.route_task_buckets))
        self.assertIn("ROAD", self.state.route_task_buckets)
        self.assertEqual(4, len(self.state.obstacle_candidate_node_ids))

    def test_neighbors(self) -> None:
        neighbors = self.state.neighbors("S01")
        self.assertTrue(neighbors)
        for node_id, edge in neighbors:
            self.assertIn(node_id, self.state.nodes)
            self.assertIn(edge.edge_id, self.state.edges)


class InquireParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = GameState(MY_ID)
        cls.state.update_start(load_msg_data("start消息.json"))
        cls.state.update_inquire(load_msg_data("inquire消息.json"))

    def test_frame_meta(self) -> None:
        self.assertEqual(142, self.state.round)
        self.assertEqual("NORMAL", self.state.phase)

    def test_me_and_opponent(self) -> None:
        me = self.state.me
        self.assertEqual(MY_ID, me.player_id)
        self.assertEqual("PROCESSING", me.state)
        self.assertEqual("S07", me.current_node_id)
        self.assertAlmostEqual(82.36, me.freshness)
        self.assertEqual(88, me.good_fruit)
        self.assertEqual(1, me.resources.get("ICE_BOX"))
        self.assertEqual(2002, self.state.opponent.player_id)

    def test_current_process(self) -> None:
        cp = self.state.me.current_process
        self.assertIsNotNone(cp)
        self.assertEqual("CLAIM_TASK", cp.action)
        self.assertEqual("T_003", cp.task_id)
        self.assertEqual(2, cp.remain_round)

    def test_buffs(self) -> None:
        buffs = {b.type: b for b in self.state.me.buffs}
        self.assertIn("RUSH_SPEED", buffs)
        self.assertAlmostEqual(0.7, buffs["RUSH_SPEED"].move_multiplier)

    def test_node_states(self) -> None:
        self.assertEqual(15, len(self.state.node_states))
        self.assertIn("S01", self.state.node_states)
        self.assertEqual(1, self.state.node_states["S10"].key_pass_combat_count)

    def test_guard_active_derived_when_absent(self) -> None:
        # 样例 guard 不带 active 字段，须按附录 C 口径推导：S08 归属 RED 且 defense=3 > 0 → 活跃
        g = self.state.node_states["S08"].guard
        self.assertIsNotNone(g)
        self.assertEqual(("RED", 3), (g.owner_team_id, g.defense))
        self.assertTrue(g.active)

    def test_score_detail(self) -> None:
        self.assertEqual(319, self.state.me.score_detail.get("total"))
        self.assertEqual(-4, self.state.me.score_detail.get("penalty"))

    def test_tasks(self) -> None:
        self.assertEqual(3, len(self.state.tasks))
        t = self.state.tasks[0]
        self.assertEqual("T_003", t.task_id)
        self.assertEqual(15, t.score)
        self.assertEqual(MY_ID, t.protection_player_id)

    def test_contests(self) -> None:
        self.assertEqual(3, len(self.state.contests))
        c = self.state.contests[0]
        self.assertEqual("RESOURCE", c.contest_type)
        self.assertTrue(c.involves(MY_ID))
        # my_contests 过滤已结算/被抑制窗口
        for mc in self.state.my_contests():
            self.assertFalse(mc.resolved)
            self.assertNotEqual("SUPPRESSED", mc.status)

    def test_weather(self) -> None:
        self.assertTrue(self.state.weather_active or self.state.weather_forecast)

    def test_my_filters(self) -> None:
        for r in self.state.my_action_results():
            self.assertEqual(MY_ID, r.player_id)
        for e in self.state.my_events():
            self.assertEqual(MY_ID, e.payload.get("playerId"))

    def test_score_preview(self) -> None:
        self.assertIn("RED", self.state.score_preview)

    def test_edges_fallback_when_missing(self) -> None:
        state = GameState(MY_ID)
        state.update_start(load_msg_data("start消息.json"))
        edges_before = dict(state.edges)
        state.update_inquire({"round": 5})  # 该帧无 edges 字段
        self.assertEqual(edges_before.keys(), state.edges.keys())

    def test_malformed_inquire_does_not_raise(self) -> None:
        state = GameState(MY_ID)
        state.update_inquire({"round": 1, "players": [{}], "nodes": [{}], "tasks": [{}],
                              "contests": [{}], "events": [{}], "actionResults": [{}],
                              "weather": {}, "bounties": [{}]})
        self.assertEqual(1, state.round)

    def test_null_fields_do_not_raise(self) -> None:
        # 协议明确停靠/无处理时字段显式为 null（附录 B/C），解析层必须容错
        state = GameState(MY_ID)
        state.update_inquire({
            "round": 2,
            "players": [{"playerId": MY_ID, "nextNodeId": None, "routeEdgeId": None,
                         "routeType": None, "moveDirection": None, "currentProcess": None,
                         "buffs": None, "resources": None, "scoreDetail": None}],
            "nodes": [{"nodeId": "S01", "processType": None, "obstacleType": None,
                       "guard": {"ownerTeamId": None, "defense": None},
                       "obstacleResidue": None, "resourceStock": None, "scouted": None}],
        })
        self.assertEqual("", state.me.next_node_id)
        self.assertIsNone(state.me.current_process)
        g = state.node_states["S01"].guard
        self.assertIsNotNone(g)
        self.assertFalse(g.active)  # 无归属/无防守 → 推导为不活跃


if __name__ == "__main__":
    unittest.main()
