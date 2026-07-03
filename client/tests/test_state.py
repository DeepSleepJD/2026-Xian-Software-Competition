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

    def test_process_node_required_resources(self) -> None:
        state = GameState(MY_ID)
        state.update_start({
            "players": [{"playerId": MY_ID, "teamId": "RED"}],
            "map": {"gameplay": {"processNodes": [
                {"nodeId": "S04", "processType": "BOARD", "processRound": 7,
                 "requiredResourceTypes": ["BOAT_RIGHT"]},
            ]}},
        })
        self.assertEqual(["BOAT_RIGHT"], state.process_nodes["S04"].required_resource_types)

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


COMBAT_START = {
    "matchId": "combat-state-test",
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": 2002, "teamId": "BLUE", "name": "op"}],
    "nodes": [{"nodeId": "S09"}, {"nodeId": "S10"}, {"nodeId": "S15", "terminal": True}],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD", "distance": 1},
        {"edgeId": "E2", "fromNodeId": "S10", "toNodeId": "S15", "routeType": "ROAD", "distance": 1},
    ],
    "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
}


class CombatHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(COMBAT_START)

    def test_enemy_guard_and_blocked_target_helpers(self) -> None:
        self.state.update_inquire({
            "round": 352,
            "players": [{"playerId": MY_ID, "teamId": "RED", "state": "IDLE",
                         "currentNodeId": "S09", "goodFruit": 98, "badFruit": 2,
                         "guardActionPoint": 4},
                        {"playerId": 2002, "teamId": "BLUE", "state": "IDLE",
                         "currentNodeId": "S10"}],
            "nodes": [{"nodeId": "S10", "guard": {"active": True, "ownerTeamId": "BLUE",
                                                   "defense": 6, "initialDefense": 6}}],
            "events": [{"eventId": "E", "type": "ACTION_REJECTED", "round": 351,
                        "payload": {"playerId": MY_ID, "errorCode": "MOVE_BLOCKED_BY_GUARD"}}],
            "actionResults": [{"round": 351, "playerId": MY_ID, "action": "MOVE",
                               "accepted": False, "errorCode": "MOVE_BLOCKED_BY_GUARD"}],
        })
        guard = self.state.enemy_guard_at("S10")
        self.assertIsNotNone(guard)
        self.assertEqual(6, guard.defense)
        self.assertEqual("S10", self.state.blocked_by_guard())
        self.assertEqual("IDLE", self.state.my_state())
        self.assertEqual(4, self.state.my_guard_points)
        self.assertEqual(98, self.state.my_good)
        self.assertEqual(2, self.state.my_bad)

    def test_my_open_contests_filters_resolved_and_suppressed(self) -> None:
        self.state.update_inquire({
            "round": 10,
            "players": [{"playerId": MY_ID, "teamId": "RED", "state": "CONTESTING"}],
            "contests": [
                {"contestId": "C1", "redPlayerId": MY_ID, "bluePlayerId": 2002},
                {"contestId": "C2", "redPlayerId": MY_ID, "bluePlayerId": 2002,
                 "resolved": True},
                {"contestId": "C3", "redPlayerId": MY_ID, "bluePlayerId": 2002,
                 "status": "SUPPRESSED"},
            ],
        })
        self.assertEqual(["C1"], [c.contest_id for c in self.state.my_open_contests()])


class SynthContestTests(unittest.TestCase):
    """本地裁判 contests 只发空壳 [{}] → 事件流合成窗口（现网字段全量时合成不重复）。"""

    PLAYERS = [{"playerId": MY_ID, "teamId": "RED", "state": "CONTESTING"},
               {"playerId": 2002, "teamId": "BLUE", "state": "CONTESTING"}]

    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(COMBAT_START)

    def _start_window(self, rnd: int = 44) -> None:
        self.state.update_inquire({
            "round": rnd, "players": self.PLAYERS, "contests": [{}],
            "events": [{"eventId": "EV1", "type": "WINDOW_CONTEST_START", "round": rnd - 1,
                        "payload": {"contestId": "C_043_001", "contestType": "DOCK",
                                    "targetNodeId": "S02"}}],
        })

    def test_synth_from_start_event_when_field_is_empty_shell(self) -> None:
        self._start_window()
        contests = self.state.my_open_contests()
        self.assertEqual(1, len(contests))
        c = contests[0]
        self.assertEqual(("C_043_001", "DOCK", "S02", 1), (c.contest_id, c.contest_type,
                                                           c.target_node_id, c.round_index))
        # 事件缺 playerId：按 teamId 回填，破对称 switcher 依赖
        self.assertEqual((MY_ID, 2002), (c.red_player_id, c.blue_player_id))

    def test_reveals_advance_round_index_then_close(self) -> None:
        self._start_window()
        reveal = lambda idx, rnd: {"round": rnd, "players": self.PLAYERS, "contests": [{}],
                                   "events": [{"eventId": f"R{idx}", "type": "WINDOW_CARD_REVEAL",
                                               "round": rnd - 1,
                                               "payload": {"contestId": "C_043_001",
                                                           "roundIndex": idx,
                                                           "redCard": "ABSTAIN",
                                                           "blueCard": "ABSTAIN"}}]}
        self.state.update_inquire(reveal(1, 45))
        self.assertEqual(2, self.state.my_open_contests()[0].round_index)
        self.state.update_inquire(reveal(2, 46))
        self.assertEqual(3, self.state.my_open_contests()[0].round_index)
        self.state.update_inquire(reveal(3, 47))   # 第 3 拍揭示 → 窗口结束
        self.assertEqual([], self.state.my_open_contests())

    def test_end_event_closes_window(self) -> None:
        self._start_window()
        self.state.update_inquire({
            "round": 45, "players": self.PLAYERS, "contests": [{}],
            "events": [{"eventId": "E2", "type": "WINDOW_CONTEST_END", "round": 44,
                        "payload": {"contestId": "C_043_001"}}],
        })
        self.assertEqual([], self.state.my_open_contests())

    def test_field_contest_shadows_synth_duplicate(self) -> None:
        self._start_window()
        # 现网形态：字段带同 id 全量对象（roundIndex=2）→ 用字段版，不重复
        self.state.update_inquire({
            "round": 45, "players": self.PLAYERS,
            "contests": [{"contestId": "C_043_001", "contestType": "DOCK",
                          "redPlayerId": MY_ID, "bluePlayerId": 2002, "roundIndex": 2}],
        })
        contests = self.state.my_open_contests()
        self.assertEqual(1, len(contests))
        self.assertEqual(2, contests[0].round_index)

    def test_stale_synth_contest_garbage_collected(self) -> None:
        self._start_window(rnd=44)
        self.state.update_inquire({"round": 60, "players": self.PLAYERS, "contests": [{}]})
        self.assertEqual([], self.state.my_open_contests())


if __name__ == "__main__":
    unittest.main()
