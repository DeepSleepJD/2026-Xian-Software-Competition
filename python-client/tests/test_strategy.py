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

    def test_first_choke_failure_switches_to_task_priority(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S04", "S04"
        s._my_team = "RED"
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "S02", "toNodeId": "T1", "routeType": "ROAD",
             "distance": 5, "bidirectional": True},
        ])
        s.chokes = s.graph.choke_points("S01", "S04")
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "T1", "hasObstacle": False, "resourceStock": {}},
        ]
        tasks = [{
            "taskId": "T_SIDE", "nodeId": "T1", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 3, "score": 50,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 200,
        }]

        act = s.decide(_inq(50, _me("S02"), _opp("S03"), nodes=nodes, tasks=tasks))

        self.assertTrue(s._task_priority_mode)
        self.assertEqual([{"action": "MOVE", "targetNodeId": "T1"}], act)

    def test_held_choke_moves_forward_immediately_after_guard(self) -> None:
        s = _line_strategy(gate="S04")
        s._first_guard_node = "S02"
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 3}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        ]

        act = s.decide(_inq(60, _me("S02"), _opp("S01"), nodes=nodes))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)

    def test_rolls_blockade_to_next_choke_even_when_previous_guard_walls_off(self) -> None:
        s = _line_strategy(gate="S04")
        s._first_guard_node = "S02"
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 3}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        ]

        act = s.decide(_inq(70, _me("S03"), _opp("S01"), nodes=nodes))

        self.assertEqual([{"action": "WAIT"}], act)

    def test_rolling_blockade_takes_local_task_when_opponent_is_far_enough(self) -> None:
        s = _line_strategy(gate="S04")
        s._first_guard_node = "S02"
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 3}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        ]
        tasks = [{
            "taskId": "T_S03", "nodeId": "S03", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 3, "score": 30,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 200,
        }]

        act = s.decide(_inq(70, _me("S03"), _opp("S01"), nodes=nodes, tasks=tasks))

        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_S03"}], act)

    def test_rolling_blockade_waits_when_local_task_would_miss_guard_window(self) -> None:
        s = _line_strategy(gate="S04")
        s._first_guard_node = "S02"
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 3}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        ]
        tasks = [{
            "taskId": "T_S03", "nodeId": "S03", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 10, "score": 30,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 200,
        }]

        act = s.decide(_inq(70, _me("S03"), _opp("S02"), nodes=nodes, tasks=tasks))

        self.assertEqual([{"action": "WAIT"}], act)

    def test_rolls_blockade_sets_next_choke_on_departure(self) -> None:
        s = _line_strategy(gate="S04")
        s._first_guard_node = "S02"
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 3}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        ]
        opp = _opp("S02", state="MOVING", nextNodeId="S03", edgeProgressPermille=0)

        act = s.decide(_inq(80, _me("S03", goodFruit=20), opp, nodes=nodes))

        self.assertIn({"action": "SET_GUARD", "targetNodeId": "S03", "extraGoodFruit": 2}, act)

    def test_no_node_action_while_mid_edge(self) -> None:
        s = _line_strategy(gate="S04")
        # on the edge into S02 (currentNodeId still S02) -> must only MOVE, never SET_GUARD
        me = _me("S02", goodFruit=20, routeEdgeId="E1", nextNodeId="S03")
        opp = _opp("S01")
        act = s.decide(_inq(50, me, opp))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)

    def test_task_spare_counts_opponent_mid_edge_progress(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S06", "S14", "S14"
        s.chokes = ["S10"]
        s._my_team = "RED"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S06", "toNodeId": "S08", "routeType": "MOUNTAIN",
             "distance": 54, "bidirectional": True},
            {"fromNodeId": "S08", "toNodeId": "S10", "routeType": "BRANCH",
             "distance": 46, "bidirectional": True},
            {"fromNodeId": "S10", "toNodeId": "S14", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ])
        nodes = [
            {"nodeId": "S06", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S08", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S10", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S14", "hasObstacle": False, "resourceStock": {}},
        ]
        task = {
            "taskId": "T_S08", "nodeId": "S08", "taskTemplateId": "T11",
            "processType": "PASS_NODE", "processRound": 4, "active": True,
            "completed": False, "failed": False, "ownerPlayerId": 0,
        }
        opp = _opp(
            "S06", state="MOVING", routeEdgeId="E16", nextNodeId="S08",
            edgeProgressMs=87000, edgeTotalMs=96120, edgeProgressPermille=905,
        )

        nodes_by_id = {n["nodeId"]: n for n in nodes}
        self.assertEqual(82, s._eta_to_node(opp, "S10", nodes_by_id, 183, {}))
        act = s.decide(_inq(183, _me("S08"), opp, nodes=nodes, tasks=[task]))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S10"}], act)

    def test_must_deliver_overrides_blocking_near_deadline(self) -> None:
        s = _line_strategy(gate="S04")
        # very late: no time left to keep blocking -> must move toward the gate
        act = s.decide(_inq(TOTAL_ROUNDS - 5, _me("S01"), _opp("S01")))
        self.assertEqual("MOVE", act[0]["action"])

    def test_unsecured_deny_uses_hard_departure_not_delivery_buffer(self) -> None:
        s = _line_strategy(gate="S04")
        # At round 500 we can still finish from S02, but only if the old 60-frame
        # buffer is ignored. Since the opponent can still finish too, keep camping.
        act = s.decide(_inq(500, _me("S02"), _opp("S01")))
        self.assertEqual([{"action": "WAIT"}], act)

    def test_returns_to_buffer_once_opponent_fastest_finish_is_too_late(self) -> None:
        s = _line_strategy(gate="S04")
        # By round 540 the opponent's optimistic fastest delivery is already past
        # the deadline, so the normal delivery buffer should take over again.
        act = s.decide(_inq(540, _me("S02"), _opp("S01")))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)

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
        self.assertEqual("MOVE", act[0]["action"])

    def test_main_action_stays_first_when_squad_runs_while_busy(self) -> None:
        s = _line_strategy(gate="S03")
        me = _me("S01", state="PROCESSING", squadAvailable=2)
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S03", "hasObstacle": True, "resourceStock": {}},
        ]

        act = s.decide(_inq(10, me, _opp("S01"), nodes=nodes))

        self.assertEqual([
            {"action": "WAIT"},
            {"action": "SQUAD_CLEAR", "targetNodeId": "S03"},
        ], act)

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

    def test_route_plan_applies_active_heavy_rain_to_water_edges(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "G", "G"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "G", "routeType": "WATER",
             "distance": 10, "bidirectional": True},
        ])
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "G": {"nodeId": "G", "hasObstacle": False, "resourceStock": {}},
        }
        weather = {"active": [{"type": "HEAVY_RAIN", "region": "WATER", "remainRound": 99}]}

        self.assertEqual(13, s._route_plan("S01", "G", _me("S01"), nodes).frames)
        self.assertEqual(
            17,
            s._route_plan("S01", "G", _me("S01"), nodes, round_no=100, weather=weather).frames,
        )

    def test_route_plan_applies_forecast_weather_mid_edge(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "G", "G"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "G", "routeType": "MOUNTAIN",
             "distance": 20, "bidirectional": True},
        ])
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "G": {"nodeId": "G", "hasObstacle": False, "resourceStock": {}},
        }
        weather = {
            "forecast": [{
                "type": "MOUNTAIN_FOG", "region": "MOUNTAIN",
                "startRound": 110, "durationRound": 100,
            }]
        }

        self.assertEqual(
            39,
            s._route_plan("S01", "G", _me("S01"), nodes, round_no=100, weather=weather).frames,
        )

    def test_route_plan_adds_rain_time_to_water_process_nodes(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "G", "G"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "S04", "routeType": "ROAD",
             "distance": 1, "bidirectional": True},
        ])
        s.graph.process_rounds = {"S04": 7}
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "S04": {
                "nodeId": "S04", "hasObstacle": False, "resourceStock": {},
                "processType": "BOARD",
            },
        }
        weather = {"active": [{"type": "HEAVY_RAIN", "region": "WATER", "remainRound": 99}]}

        self.assertEqual(
            13,
            s._route_plan("S01", "S04", _me("S01"), nodes, round_no=100, weather=weather).frames,
        )

    def test_active_weather_remain_round_uses_original_base_round(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "G", "G"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "G", "routeType": "WATER",
             "distance": 10, "bidirectional": True},
        ])
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "G": {"nodeId": "G", "hasObstacle": False, "resourceStock": {}},
        }
        weather = {"active": [{"type": "HEAVY_RAIN", "region": "WATER", "remainRound": 5}]}

        self.assertEqual(
            13,
            s._route_plan(
                "S01", "G", _me("S01"), nodes, round_no=110, weather=weather,
                weather_base_round=100,
            ).frames,
        )


class OpeningContestTests(unittest.TestCase):
    def _contest(self, ri=1, red_point=0, blue_point=0, red=1001, blue=2002):
        return {"contestId": "C1", "contestType": "DOCK", "roundIndex": ri,
                "redPlayerId": red, "bluePlayerId": blue, "resolved": False,
                "deadlineRound": 200, "redPoint": red_point, "bluePoint": blue_point}

    def test_plays_xian_gong_on_first_two_taps(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=10, goodFruit=0)

        for ri in (1, 2):
            act = s._card(me, [self._contest(ri)], 50)
            self.assertEqual("XIAN_GONG", act[0]["card"])

        # a SECOND (different) contest also gets XIAN_GONG (the bug was it didn't)
        c2 = self._contest(1); c2["contestId"] = "C2"
        act = s._card(me, [c2], 80)
        self.assertEqual("XIAN_GONG", act[0]["card"])

    def test_third_tap_abstains_when_already_up_two_zero(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=95, goodFruit=20)

        act = s._card(me, [self._contest(3, red_point=2, blue_point=0)], 50)

        self.assertEqual("ABSTAIN", act[0]["card"])

    def test_third_tap_uses_xian_gong_unless_already_up_two_zero(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=95, goodFruit=20)

        act = s._card(me, [self._contest(3, red_point=1, blue_point=1)], 50)

        self.assertEqual("XIAN_GONG", act[0]["card"])

    def test_third_tap_abstain_uses_blue_side_points_too(self) -> None:
        s = Strategy(2002)
        me = {"playerId": 2002}

        act = s._card(me, [self._contest(3, red_point=0, blue_point=2)], 50)

        self.assertEqual("ABSTAIN", act[0]["card"])


if __name__ == "__main__":
    unittest.main()
