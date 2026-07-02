"""CombatStrategy 单测：攻坚破卡与窗口出牌。"""

import unittest

from lychee.arbiter import merge_intents
from lychee.state import GameState
from lychee.strategy import Intent
from lychee.strategy.combat import CombatStrategy, PRIORITY_COMBAT_MAIN

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
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S10", "toNodeId": "S15",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
}


def inquire(round_no: int, *, node: str = "S09", state: str = "IDLE",
            good: int = 98, bad: int = 2, freshness: float = 85.0,
            guard_points: int = 4, contests: list | None = None,
            nodes: list | None = None, phase: str = "NORMAL",
            next_node: str = "", squad_available: int = 8,
            squad_in_flight: int = 0) -> dict:
    return {
        "round": round_no,
        "phase": phase,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "goodFruit": good, "badFruit": bad,
                     "freshness": freshness, "guardActionPoint": guard_points,
                     "squadAvailable": squad_available,
                     "squadInFlight": squad_in_flight},
                    {"playerId": OPP_ID, "teamId": "BLUE", "state": "IDLE",
                     "currentNodeId": "S10"}],
        "nodes": nodes or [],
        "contests": contests or [],
    }


def guard_s10(defense: int = 6) -> list[dict]:
    return [{"nodeId": "S10", "guard": {"active": True, "ownerTeamId": "BLUE",
                                         "defense": defense, "initialDefense": defense,
                                         "maxDefense": 7}}]


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

    def test_squad_weakens_next_node_guard_while_moving(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", next_node="S10", nodes=guard_s10()))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_squad_weaken_stops_when_enough_in_flight(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", next_node="S10",
                                    nodes=guard_s10(), squad_in_flight=3))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_plays_xian_gong_for_relevant_window_when_fresh(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}, acts)

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
        self.assertEqual([{"action": "WINDOW_CARD", "contestId": "C2", "card": "XIAN_GONG"}], acts)

    def test_irrelevant_window_gets_no_explicit_abstain(self) -> None:
        contests = [{"contestId": "C1", "contestType": "RESOURCE", "targetNodeId": "",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertNotIn("WINDOW_CARD", [a["action"] for a in acts])


if __name__ == "__main__":
    unittest.main()
