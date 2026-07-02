"""CombatStrategy 单测：攻坚破卡与窗口出牌。"""

import unittest

from lychee.arbiter import merge_intents
from lychee.state import GameState
from lychee.strategy import Intent
from lychee.strategy.combat import (
    CombatStrategy, PRIORITY_COMBAT_MAIN, PRIORITY_SET_GUARD, PRIORITY_SQUAD_SCOUT,
)

MY_ID = 1001
OPP_ID = 2002

START = {
    "matchId": "combat-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "S09", "nodeType": "STATION"},
        {"nodeId": "S10", "nodeType": "KEY_PASS"},
        {"nodeId": "S15", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S09", "toNodeId": "S10",
         "routeType": "ROAD", "distance": 30, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S10", "toNodeId": "S15",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
}


def inquire(round_no: int, *, node: str = "S09", state: str = "IDLE",
            good: int = 98, bad: int = 2, freshness: float = 85.0,
            guard_points: int = 4, contests: list | None = None,
            nodes: list | None = None, phase: str = "NORMAL",
            next_node: str = "", move_dir: str = "", squad_available: int = 8,
            squad_in_flight: int = 0, opp_node: str = "S10",
            resources: dict | None = None, events: list | None = None) -> dict:
    return {
        "round": round_no,
        "phase": phase,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "moveDirection": move_dir,
                     "goodFruit": good, "badFruit": bad,
                     "freshness": freshness, "guardActionPoint": guard_points,
                     "squadAvailable": squad_available,
                     "squadInFlight": squad_in_flight,
                     "resources": resources or {}},
                    {"playerId": OPP_ID, "teamId": "BLUE", "state": "IDLE",
                     "currentNodeId": opp_node}],
        "nodes": nodes or [],
        "contests": contests or [],
        "events": events or [],
    }


def guard_s10(defense: int = 6) -> list[dict]:
    return [{"nodeId": "S10", "guard": {"active": True, "ownerTeamId": "BLUE",
                                         "defense": defense, "initialDefense": defense,
                                         "maxDefense": 7}}]


def obstacle_s10() -> list[dict]:
    return [{"nodeId": "S10", "hasObstacle": True, "obstacleType": "LANDSLIDE"}]


def friendly_guard(node_id: str) -> dict:
    return {"nodeId": node_id, "guard": {"active": True, "ownerTeamId": "RED",
                                         "defense": 6, "initialDefense": 6,
                                         "maxDefense": 7}}


SCOUT_START = {
    "matchId": "scout-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
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
        "processNodes": [
            {"nodeId": "B", "processType": "TRANSFER", "processRound": 5,
             "canWindow": True},
        ],
    }},
}


class CombatStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = CombatStrategy()

    def intents(self, inq: dict) -> list[Intent]:
        self.state.update_inquire(inq)
        return self.strategy.propose(self.state)

    def actions(self, inq: dict) -> list[dict]:
        return [a for it in self.intents(inq) for a in it.actions]

    def test_breaks_adjacent_enemy_guard_with_bad_fruit_first(self) -> None:
        intents = self.intents(inquire(320, nodes=guard_s10()))
        main = [it for it in intents if it.kind == "combat"][0]
        self.assertEqual(PRIORITY_COMBAT_MAIN, main.priority)
        self.assertEqual({"action": "BREAK_GUARD", "targetNodeId": "S10",
                          "goodFruit": 0, "badFruit": 2}, main.actions[0])

    def test_break_guard_does_not_overkill_with_bad_fruit(self) -> None:
        acts = self.actions(inquire(320, nodes=guard_s10(defense=1)))
        self.assertIn({"action": "BREAK_GUARD", "targetNodeId": "S10",
                       "goodFruit": 0, "badFruit": 1}, acts)

    def test_combat_break_suppresses_delivery_move_in_arbiter(self) -> None:
        intents = self.intents(inquire(320, nodes=guard_s10()))
        intents.append(Intent(kind="delivery", priority=100,
                              actions=[{"action": "MOVE", "targetNodeId": "S10"}]))
        actions = merge_intents(intents)
        self.assertIn({"action": "BREAK_GUARD", "targetNodeId": "S10",
                       "goodFruit": 0, "badFruit": 2}, actions)
        self.assertNotIn({"action": "MOVE", "targetNodeId": "S10"}, actions)

    def test_does_not_break_while_moving(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_no_ammo_does_not_emit_high_priority_wait(self) -> None:
        acts = self.actions(inquire(320, nodes=guard_s10(), good=0, bad=0))
        self.assertEqual([], [a for a in acts if a["action"] in ("BREAK_GUARD", "WAIT")])

    def test_sets_guard_on_opponent_choke_when_ahead(self) -> None:
        intents = self.intents(inquire(200, node="S10", opp_node="S09"))
        guard = [it for it in intents if it.kind == "combat.guard"][0]
        self.assertEqual(PRIORITY_SET_GUARD, guard.priority)
        self.assertEqual({"action": "SET_GUARD", "targetNodeId": "S10",
                          "extraGoodFruit": 2}, guard.actions[0])

    def test_does_not_set_guard_at_terminal(self) -> None:
        acts = self.actions(inquire(200, node="S15", opp_node="S09"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_when_not_ahead(self) -> None:
        acts = self.actions(inquire(200, node="S10", opp_node="S10"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_when_two_friendly_guards_active(self) -> None:
        nodes = [friendly_guard("S09"), friendly_guard("S15")]
        acts = self.actions(inquire(200, node="S10", opp_node="S09", nodes=nodes))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_over_existing_guard(self) -> None:
        acts = self.actions(inquire(200, node="S10", opp_node="S09",
                                    nodes=[friendly_guard("S10")]))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_below_good_fruit_floor(self) -> None:
        acts = self.actions(inquire(200, node="S10", opp_node="S09", good=91))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_break_guard_blocked_when_paused_mid_edge(self) -> None:
        # P4d 死锁根因①：半路被守卫暂停（WAITING+PAUSED+nextNodeId 保留）不是可攻坚状态，
        # 发 BREAK_GUARD 必被判 MOVING_ACTION_FORBIDDEN（任务书 8.2）
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_break_guard_blocked_mid_edge_without_pause_flag(self) -> None:
        # nextNodeId 非空即在边上，即使字段变体缺 PAUSED 标记也不得攻坚
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_break_guard_still_fires_when_docked_waiting(self) -> None:
        # 防回归锚点：真停靠节点（nextNodeId 空、非 PAUSED）的 WAITING 仍可攻坚
        acts = self.actions(inquire(320, state="WAITING", nodes=guard_s10()))
        self.assertIn({"action": "BREAK_GUARD", "targetNodeId": "S10",
                       "goodFruit": 0, "badFruit": 2}, acts)

    def test_squad_weaken_keeps_dispatching_when_paused(self) -> None:
        # P4d 死锁根因②：被暂停成 WAITING 后削卡不能熄火——它是唯一快速清卡手段
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10()))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_squad_weaken_paused_stops_when_enough_in_flight(self) -> None:
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(),
                                    squad_in_flight=3))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_squad_weaken_paused_respects_squad_floor(self) -> None:
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(),
                                    squad_available=1))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_squad_weakens_next_node_guard_while_moving(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", next_node="S10", nodes=guard_s10()))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_squad_weaken_stops_when_enough_in_flight(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", next_node="S10",
                                    nodes=guard_s10(), squad_in_flight=3))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_clears_obstacle_on_terminal_path_next_hop(self) -> None:
        # P4d 实测：咽喉道路障碍无人清 = MOVE 永拒 = 卡死未送达（任务书 2.4.4）
        intents = self.intents(inquire(100, nodes=obstacle_s10()))
        clear = [it for it in intents if it.kind == "combat.clear"][0]
        self.assertEqual(PRIORITY_COMBAT_MAIN, clear.priority)
        self.assertEqual({"action": "CLEAR", "targetNodeId": "S10"}, clear.actions[0])

    def test_clear_beats_delivery_move_in_arbiter(self) -> None:
        intents = self.intents(inquire(100, nodes=obstacle_s10()))
        intents.append(Intent(kind="delivery", priority=100,
                              actions=[{"action": "MOVE", "targetNodeId": "S10"}]))
        actions = merge_intents(intents)
        self.assertIn({"action": "CLEAR", "targetNodeId": "S10"}, actions)
        self.assertNotIn({"action": "MOVE", "targetNodeId": "S10"}, actions)

    def test_no_clear_when_mid_edge(self) -> None:
        # 清障是主车队停靠动作，半路（含被暂停）不得提交
        acts = self.actions(inquire(100, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=obstacle_s10()))
        self.assertNotIn("CLEAR", [a["action"] for a in acts])

    def test_no_clear_without_obstacle(self) -> None:
        acts = self.actions(inquire(100))
        self.assertNotIn("CLEAR", [a["action"] for a in acts])

    def test_no_set_guard_when_must_rush(self) -> None:
        # P4d 送达优先：S10 到终点 3 帧，590+3+60 ≥ 600，设卡（纯刷分）让路
        acts = self.actions(inquire(590, node="S10", opp_node="S09"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_break_guard_unaffected_by_must_rush(self) -> None:
        # 攻坚打的是终点路径上的卡，是送达的一部分，不受送达优先约束
        acts = self.actions(inquire(550, nodes=guard_s10()))
        self.assertIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_plays_bing_zheng_first_for_relevant_window(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}, acts)

    def test_plays_bing_zheng_when_not_fresh_enough_for_xian_gong(self) -> None:
        contests = [{"contestId": "C1", "contestType": "PASS", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, freshness=70.0))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}, acts)

    def test_only_one_relevant_window_card_per_frame(self) -> None:
        contests = [
            {"contestId": "C1", "contestType": "RESOURCE", "targetNodeId": "",
             "redPlayerId": MY_ID, "bluePlayerId": OPP_ID},
            {"contestId": "C2", "contestType": "PASS", "targetNodeId": "S10",
             "redPlayerId": MY_ID, "bluePlayerId": OPP_ID},
        ]
        acts = [a for a in self.actions(inquire(44, contests=contests))
                if a["action"] == "WINDOW_CARD"]
        self.assertEqual([{"action": "WINDOW_CARD", "contestId": "C2", "card": "BING_ZHENG"}], acts)

    def test_irrelevant_window_gets_no_explicit_abstain(self) -> None:
        contests = [{"contestId": "C1", "contestType": "RESOURCE", "targetNodeId": "",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertNotIn("WINDOW_CARD", [a["action"] for a in acts])

    def test_plays_yan_die_from_document_resource_without_use_resource(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, freshness=70.0,
                                    guard_points=1, resources={"PASS_TOKEN": 1}))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "YAN_DIE"}, acts)
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_gate_window_spends_last_guard_point(self) -> None:
        contests = [{"contestId": "C1", "contestType": "GATE", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, freshness=70.0, guard_points=1))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}, acts)

    def test_plays_xian_gong_against_bing_zheng_tendency(self) -> None:
        contests = [{"contestId": "C3", "contestType": "PASS", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        reveals = [
            {"eventId": "R1", "type": "WINDOW_CARD_REVEAL", "round": 40,
             "payload": {"contestId": "C1", "roundIndex": 1,
                         "redCard": "YAN_DIE", "blueCard": "BING_ZHENG"}},
            {"eventId": "R2", "type": "WINDOW_CARD_REVEAL", "round": 41,
             "payload": {"contestId": "C2", "roundIndex": 1,
                         "redCard": "YAN_DIE", "blueCard": "BING_ZHENG"}},
        ]
        acts = self.actions(inquire(44, contests=contests, events=reveals))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C3", "card": "XIAN_GONG"}, acts)

    def test_squad_scouts_upcoming_process_node(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        intents = self.intents(inquire(10, node="A", opp_node="C"))
        scout = [it for it in intents if it.actions[0]["action"] == "SQUAD_SCOUT"][0]
        self.assertEqual(PRIORITY_SQUAD_SCOUT, scout.priority)
        self.assertEqual({"action": "SQUAD_SCOUT", "targetNodeId": "B"}, scout.actions[0])

    def test_squad_scout_dedupes_pending_and_marker(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"},
                      self.actions(inquire(10, node="A", opp_node="C")))
        self.assertNotIn("SQUAD_SCOUT",
                         [a["action"] for a in self.actions(inquire(11, node="A", opp_node="C"))])

        add = [{"eventId": "S1", "type": "SCOUT_MARKER_ADD", "round": 12,
                "payload": {"playerId": MY_ID, "targetNodeId": "B", "expireRound": 50}}]
        self.assertNotIn("SQUAD_SCOUT",
                         [a["action"] for a in self.actions(inquire(12, node="A", opp_node="C",
                                                                    events=add))])
        consume = [{"eventId": "S2", "type": "SCOUT_MARKER_CONSUME", "round": 13,
                    "payload": {"playerId": MY_ID, "targetNodeId": "B"}}]
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"},
                      self.actions(inquire(13, node="A", opp_node="C", events=consume)))

    def test_squad_scout_reserves_weaken_budget(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(10, node="A", squad_available=4, opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_weaken_wins_over_scout(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        nodes = [{"nodeId": "B", "guard": {"active": True, "ownerTeamId": "BLUE",
                                            "defense": 6, "initialDefense": 6}}]
        acts = self.actions(inquire(10, node="A", state="MOVING", next_node="B",
                                    nodes=nodes, opp_node="C"))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "B"}, acts)
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])


if __name__ == "__main__":
    unittest.main()
