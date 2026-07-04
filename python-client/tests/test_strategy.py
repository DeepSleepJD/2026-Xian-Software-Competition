import unittest

from lychee_basic_client.strategy import Strategy, TOTAL_ROUNDS


def _line_strategy(gate="S05"):
    # S01 - S02 - S03 - S04 - S05 (a single funnel: every inner node is a choke)
    s = Strategy(1001)
    s.graph.load_edges([
        {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": 10,
         "bidirectional": True}
        for a, b in [("S01", "S02"), ("S02", "S03"), ("S03", "S04"), ("S04", "S05")]
    ])
    s.start_node, s.gate_node, s.terminal_node = "S01", gate, "S05"
    s.chokes = s.graph.choke_points("S01", gate)
    s._my_team = "RED"
    return s


def _me(node, **kw):
    d = {"playerId": 1001, "teamId": "RED", "currentNodeId": node, "state": "IDLE",
         "nextNodeId": None, "routeEdgeId": None, "resources": {}, "goodFruit": 20,
         "freshness": 90.0, "verified": False, "delivered": False, "retired": False}
    d.update(kw)
    return d


def _opp(node, **kw):
    d = {"playerId": 2002, "teamId": "BLUE", "currentNodeId": node, "state": "IDLE",
         "nextNodeId": None, "routeEdgeId": None}
    d.update(kw)
    return d


def _inq(round_no, me, opp, nodes=None, phase="NORMAL", tasks=None):
    ns = nodes or []
    return {"round": round_no, "phase": phase, "players": [me, opp],
            "nodes": ns, "tasks": tasks or [], "contests": [], "events": []}


class ChokeSetupTests(unittest.TestCase):
    def test_finds_chokes_on_a_funnel(self) -> None:
        s = _line_strategy(gate="S04")
        # S02, S03 are cut-vertices between S01 and S04
        self.assertIn("S02", s.chokes)
        self.assertIn("S03", s.chokes)


class BlockadeTests(unittest.TestCase):
    def test_races_to_the_choke_first(self) -> None:
        s = _line_strategy(gate="S04")  # chokes S02(near gate first?)/S03
        act = s.decide(_inq(10, _me("S01"), _opp("S01")))
        # heads deeper toward the choke, not idling
        self.assertEqual("MOVE", act[0]["action"])

    def test_freezes_when_opponent_commits_onto_edge(self) -> None:
        s = _line_strategy(gate="S04")  # chokes S02, S03 on the line
        me = _me("S02", goodFruit=20)   # camped on a choke
        # opponent committed onto S01->S02 with the whole edge ahead -> freeze
        opp = _opp("S01", state="MOVING", nextNodeId="S02", edgeProgressPermille=0)
        act = s.decide(_inq(50, me, opp))
        self.assertIn({"action": "SET_GUARD", "targetNodeId": "S02", "extraGoodFruit": 2}, act)

    def test_camps_not_guards_before_opponent_commits(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S02", goodFruit=20)
        opp = _opp("S01")  # parked, not committed -> we camp (wait), don't set early
        act = s.decide(_inq(50, me, opp))
        self.assertNotIn("SET_GUARD", [a["action"] for a in act])

    def test_does_not_guard_choke_opponent_already_passed(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S02", goodFruit=20)
        opp = _opp("S03")  # opponent already past S02 -> pointless to guard it
        act = s.decide(_inq(50, me, opp))
        self.assertNotIn("SET_GUARD", [a["action"] for a in act])

    def test_no_node_action_while_mid_edge(self) -> None:
        s = _line_strategy(gate="S04")
        # on the edge into S02 (currentNodeId still S02) -> must only MOVE, never SET_GUARD
        me = _me("S02", goodFruit=20, routeEdgeId="E1", nextNodeId="S03")
        opp = _opp("S01")
        act = s.decide(_inq(50, me, opp))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)

    def test_must_deliver_overrides_blocking_near_deadline(self) -> None:
        s = _line_strategy(gate="S04")
        # very late: no time left to keep blocking -> must move toward the gate
        act = s.decide(_inq(TOTAL_ROUNDS - 5, _me("S01"), _opp("S01")))
        self.assertEqual("MOVE", act[0]["action"])

    def test_delivers_when_verified_at_terminal(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S05", verified=True, currentNodeId="S05")
        act = s.decide(_inq(300, me, _opp("S01")))
        self.assertEqual("DELIVER", act[0]["action"])

    def test_opening_first_hop_obstacle_uses_main_clear_not_squad(self) -> None:
        s = _line_strategy(gate="S03")
        me = _me("S01", squadAvailable=2)
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": True, "resourceStock": {}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
        ]
        act = s.decide(_inq(10, me, _opp("S01"), nodes=nodes))

        self.assertEqual([{"action": "CLEAR", "targetNodeId": "S02"}], act)

    def test_obstacle_after_first_hop_is_squad_cleared(self) -> None:
        s = _line_strategy(gate="S03")
        me = _me("S01", squadAvailable=2)
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S03", "hasObstacle": True, "resourceStock": {}},
        ]
        act = s.decide(_inq(10, me, _opp("S01"), nodes=nodes))

        self.assertIn({"action": "SQUAD_CLEAR", "targetNodeId": "S03"}, act)
        self.assertIn({"action": "MOVE", "targetNodeId": "S02"}, act)

    def test_opening_clear_prefers_t04_when_available(self) -> None:
        s = _line_strategy(gate="S03")
        me = _me("S01", squadAvailable=2)
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": True, "resourceStock": {}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
        ]
        tasks = [{
            "taskId": "T04_1", "nodeId": "S02", "taskTemplateId": "T04",
            "processType": "CLEAR_OBSTACLE", "processRound": 6, "active": True,
            "completed": False, "failed": False, "ownerPlayerId": 0,
        }]
        act = s.decide(_inq(10, me, _opp("S01"), nodes=nodes, tasks=tasks))

        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T04_1"}], act)


class RoutePlanTests(unittest.TestCase):
    def test_route_plan_counts_opening_first_hop_obstacle_once(self) -> None:
        s = _line_strategy(gate="S03")
        me = _me("S01")
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "S02": {"nodeId": "S02", "hasObstacle": True, "resourceStock": {}},
            "S03": {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
        }

        self.assertEqual(34, s._route_plan("S01", "S03", me, nodes).frames)
        s._left_start = True
        self.assertEqual(28, s._route_plan("S01", "S03", me, nodes).frames)

    def test_route_plan_uses_horse_when_it_changes_the_fastest_path(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "G", "G"
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "A", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "A", "toNodeId": "G", "routeType": "ROAD",
             "distance": 100, "bidirectional": True},
            {"fromNodeId": "S01", "toNodeId": "B", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "B", "toNodeId": "G", "routeType": "ROAD",
             "distance": 99, "bidirectional": True},
        ])
        s._left_start = True
        me = _me("S01")
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "A": {"nodeId": "A", "hasObstacle": False,
                  "resourceStock": {"FAST_HORSE": 1}},
            "B": {"nodeId": "B", "hasObstacle": False, "resourceStock": {}},
            "G": {"nodeId": "G", "hasObstacle": False, "resourceStock": {}},
        }

        plan = s._route_plan("S01", "G", me, nodes)

        self.assertEqual(["S01", "A", "G"], plan.path)
        self.assertEqual(150, plan.frames)


class OpeningContestTests(unittest.TestCase):
    def _contest(self, ri=1):
        return {"contestId": "C1", "contestType": "DOCK", "roundIndex": ri,
                "redPlayerId": 1001, "bluePlayerId": 2002, "resolved": False,
                "deadlineRound": 200}

    def test_plays_xian_gong_on_every_tap_of_every_contest(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=95, goodFruit=20)
        # first contest, all three taps
        for ri in (1, 2, 3):
            act = s._card(me, [self._contest(ri)], 50)
            self.assertEqual("XIAN_GONG", act[0]["card"])
        # a SECOND (different) contest also gets XIAN_GONG (the bug was it didn't)
        c2 = self._contest(1); c2["contestId"] = "C2"
        act = s._card(me, [c2], 80)
        self.assertEqual("XIAN_GONG", act[0]["card"])

    def test_good_fruit_floor_stops_xian_gong(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=95, goodFruit=3)  # below the floor
        act = s._card(me, [self._contest()], 50)
        self.assertNotEqual("XIAN_GONG", act[0]["card"])  # protect delivery/guard fruit


if __name__ == "__main__":
    unittest.main()
