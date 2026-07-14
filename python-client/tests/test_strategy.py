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

    def test_active_guard_flips_to_farm_and_advances(self) -> None:
        # fire-and-forget: once our freeze guard is ACTIVE we stop camping, flip
        # to task-priority farming and walk our own run
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

        self.assertTrue(s._task_priority_mode)
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S04"}], act)

    def test_farm_after_freeze_takes_local_task(self) -> None:
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

    def test_local_wait_overrides_farm_when_opponent_parks_next_door(self) -> None:
        # The freeze is placed, but an unsafe local task must not consume the
        # guard window while the opponent waits one hop behind us.
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

    def test_watches_when_opponent_moves_to_behind_neighbor(self) -> None:
        s = _line_strategy(gate="S04")
        nodes = [
            {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04", "S05")
        ]
        opp = _opp("S01", state="MOVING", routeEdgeId="E01",
                   nextNodeId="S02", edgeProgressPermille=0)

        act = s.decide(_inq(70, _me("S03"), opp, nodes=nodes))

        self.assertEqual([{"action": "WAIT"}], act)

    def test_watches_and_claims_safe_task_when_opponent_moves_to_behind_neighbor(self) -> None:
        s = _line_strategy(gate="S04")
        nodes = [
            {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04", "S05")
        ]
        task = {
            "taskId": "T_S03", "nodeId": "S03", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 3, "score": 30,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 200,
        }
        opp = _opp("S01", state="MOVING", routeEdgeId="E01",
                   nextNodeId="S02", edgeProgressPermille=0)

        act = s.decide(_inq(70, _me("S03"), opp, nodes=nodes, tasks=[task]))

        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_S03"}], act)

    def test_moves_on_when_behind_neighbor_opponent_bypasses_without_safe_op(self) -> None:
        s = _line_strategy(gate="S04")
        nodes = [
            {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04", "S05")
        ]
        opp = _opp("S02", state="MOVING", routeEdgeId="E10",
                   nextNodeId="S01", edgeProgressPermille=0)

        act = s.decide(_inq(70, _me("S03"), opp, nodes=nodes))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S04"}], act)

    def test_moves_on_when_behind_neighbor_force_passes_after_contest_loss(self) -> None:
        s = _line_strategy(gate="S04")
        nodes = [
            {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04", "S05")
        ]
        opp = _opp("S02", state="FORCED_PASSING", routeEdgeId="P1",
                   nextNodeId="S03", edgeProgressPermille=0)

        act = s.decide(_inq(70, _me("S03"), opp, nodes=nodes))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S04"}], act)

    def test_local_ambush_reguards_after_freeze_when_opponent_commits_to_us(self) -> None:
        # The old fire-and-forget plan would keep walking here; the always-on
        # local ambush must arm our current node if the opponent commits into it.
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

        self.assertEqual([{"action": "SET_GUARD", "targetNodeId": "S03", "extraGoodFruit": 2}], act)

    def test_local_ambush_resumes_route_when_adjacent_opponent_moves_elsewhere(self) -> None:
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
            {"fromNodeId": "S01", "toNodeId": "B1", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "B1", "toNodeId": "S03", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ])
        s.chokes = s.graph.choke_points("S01", "S04")
        nodes = [
            {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04", "B1")
        ]
        opp = _opp("S01", state="MOVING", routeEdgeId="E_SIDE",
                   nextNodeId="B1", edgeProgressPermille=0)

        act = s.decide(_inq(80, _me("S02", goodFruit=20), opp, nodes=nodes))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)

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

        self.assertEqual(
            [{"action": "SET_GUARD", "targetNodeId": "S08", "extraGoodFruit": 2}],
            act,
        )

    def test_missed_delivery_abandons_blocking_near_deadline(self) -> None:
        s = _line_strategy(gate="S04")
        # very late: delivery can no longer finish, so stop forcing a doomed run.
        act = s.decide(_inq(TOTAL_ROUNDS - 5, _me("S01"), _opp("S01")))
        self.assertTrue(s._delivery_abandoned)
        self.assertEqual([{"action": "WAIT"}], act)

    def test_unsecured_deny_uses_hard_departure_not_delivery_buffer(self) -> None:
        s = _line_strategy(gate="S04")
        # At round 500 we can still finish comfortably from S02, so do not
        # abandon delivery just because a safety buffer would be shrinking.
        act = s.decide(_inq(500, _me("S02"), _opp("S01")))
        self.assertFalse(s._delivery_abandoned)
        self.assertEqual([{"action": "WAIT"}], act)

    def test_must_deliver_overrides_local_wait_near_deadline(self) -> None:
        s = _line_strategy(gate="S04")
        # Once the latest safe departure arrives, we leave even if an adjacent
        # opponent could be baited into a local ambush.
        act = s.decide(_inq(545, _me("S02"), _opp("S01")))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)

    def test_task_mode_claims_local_task_after_delivery_missed(self) -> None:
        s = _line_strategy(gate="S04")
        s._task_priority_mode = True
        tasks = [{
            "taskId": "T_LATE", "nodeId": "S02", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 3, "score": 60,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 600,
        }]

        act = s.decide(_inq(TOTAL_ROUNDS - 5, _me("S02"), _opp("S01"), tasks=tasks))

        self.assertTrue(s._delivery_abandoned)
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_LATE"}], act)

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

        self.assertEqual({"action": "CLEAR", "targetNodeId": "S02"}, act[0])
        self.assertNotIn("SQUAD_CLEAR", [a["action"] for a in act])

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

        self.assertEqual({"action": "CLAIM_TASK", "taskId": "T04_1"}, act[0])
        self.assertNotIn("SQUAD_CLEAR", [a["action"] for a in act])

    def test_opening_route_prefers_water_when_scout_budget_beats_mountain(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S14", "S15"
        edges = [
            ("S01", "S02", "ROAD", 30), ("S02", "S03", "ROAD", 25),
            ("S03", "S07", "ROAD", 54), ("S07", "S09", "ROAD", 46),
            ("S09", "S10", "ROAD", 40), ("S10", "S11", "ROAD", 36),
            ("S11", "S12", "ROAD", 20), ("S12", "S13", "ROAD", 25),
            ("S13", "S14", "ROAD", 18), ("S14", "S15", "ROAD", 10),
            ("S02", "S04", "ROAD", 20), ("S04", "S05", "WATER", 44),
            ("S05", "S07", "BRANCH", 46), ("S01", "S06", "MOUNTAIN", 44),
            ("S06", "S08", "MOUNTAIN", 54), ("S08", "S10", "BRANCH", 46),
            ("S03", "S06", "BRANCH", 38), ("S05", "S09", "WATER", 48),
            ("S07", "S08", "MOUNTAIN", 42), ("S04", "S07", "BRANCH", 54),
            ("S08", "S09", "BRANCH", 64),
        ]
        s.graph.load_edges([
            {"fromNodeId": a, "toNodeId": b, "routeType": rt,
             "distance": d, "bidirectional": True}
            for a, b, rt, d in edges
        ])
        s.graph.process_rounds = {
            "S02": 4, "S04": 7, "S05": 6, "S11": 5, "S13": 5,
        }
        s.chokes = s.graph.choke_points("S01", "S14")
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "processRound": 4, "resourceStock": {}},
            {"nodeId": "S03", "hasObstacle": False, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S04", "hasObstacle": False, "processRound": 7, "resourceStock": {}},
            {"nodeId": "S05", "hasObstacle": False, "processRound": 6, "resourceStock": {}},
            {"nodeId": "S06", "hasObstacle": True, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S07", "hasObstacle": False, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S08", "hasObstacle": True, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S09", "hasObstacle": False, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S10", "hasObstacle": True, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S11", "hasObstacle": True, "processRound": 5, "resourceStock": {}},
            {"nodeId": "S12", "hasObstacle": False, "processRound": 0, "resourceStock": {}},
            {"nodeId": "S13", "hasObstacle": False, "processRound": 5, "resourceStock": {}},
            {"nodeId": "S14", "hasObstacle": False, "processRound": 6, "resourceStock": {}},
            {"nodeId": "S15", "hasObstacle": False, "processRound": 0, "resourceStock": {}},
        ]

        act = s.decide(_inq(1, _me("S01", squadAvailable=8), _opp("S01"), nodes=nodes))

        self.assertEqual({"action": "MOVE", "targetNodeId": "S02"}, act[0])
        self.assertIn({"action": "SQUAD_CLEAR", "targetNodeId": "S10"}, act)
        self.assertEqual(["S01", "S02", "S04", "S05", "S09", "S10", "S11", "S12", "S13", "S14"], s._opening_route_path)

    def test_squad_scouts_process_node_once_inside_marker_window(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S14", "S15"
        s.graph.load_edges([
            {"fromNodeId": "S04", "toNodeId": "S05", "routeType": "WATER",
             "distance": 44, "bidirectional": True},
            {"fromNodeId": "S05", "toNodeId": "S09", "routeType": "WATER",
             "distance": 48, "bidirectional": True},
            {"fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD",
             "distance": 40, "bidirectional": True},
            {"fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD",
             "distance": 36, "bidirectional": True},
            {"fromNodeId": "S11", "toNodeId": "S12", "routeType": "ROAD",
             "distance": 20, "bidirectional": True},
            {"fromNodeId": "S12", "toNodeId": "S13", "routeType": "ROAD",
             "distance": 25, "bidirectional": True},
            {"fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD",
             "distance": 18, "bidirectional": True},
        ])
        s.graph.process_rounds = {"S05": 6, "S11": 5, "S13": 5}
        s._my_team = "RED"
        s.route_avoid = {"S03", "S06", "S07", "S08"}
        s._squad_sent = {"S10", "S11"}
        nodes = {
            "S04": {"nodeId": "S04", "x": 22, "y": 52, "hasObstacle": False,
                    "processRound": 7, "resourceStock": {}},
            "S05": {"nodeId": "S05", "x": 38, "y": 48, "hasObstacle": False,
                    "processRound": 6, "resourceStock": {}, "scouted": []},
            "S09": {"nodeId": "S09", "x": 55, "y": 32, "hasObstacle": False,
                    "processRound": 0, "resourceStock": {}},
            "S10": {"nodeId": "S10", "x": 62, "y": 26, "hasObstacle": True,
                    "processRound": 0, "resourceStock": {}},
            "S11": {"nodeId": "S11", "x": 66, "y": 22, "hasObstacle": True,
                    "processRound": 5, "resourceStock": {}},
            "S12": {"nodeId": "S12", "x": 70, "y": 20, "hasObstacle": False,
                    "processRound": 0, "resourceStock": {}},
            "S13": {"nodeId": "S13", "x": 73, "y": 19, "hasObstacle": False,
                    "processRound": 5, "resourceStock": {}},
            "S14": {"nodeId": "S14", "x": 76, "y": 18, "hasObstacle": False,
                    "processRound": 6, "resourceStock": {}},
            "S15": {"nodeId": "S15", "x": 78, "y": 18, "hasObstacle": False,
                    "processRound": 0, "resourceStock": {}},
        }
        me = _me(
            "S04", squadAvailable=4, state="MOVING", routeEdgeId="E12",
            nextNodeId="S05", edgeProgressPermille=300,
        )

        act = s._squad_action("S04", me, _opp("S01"), [], nodes, round_no=90)

        self.assertEqual([{"action": "SQUAD_SCOUT", "targetNodeId": "S05"}], act)


def _spaced_line_strategy(gate="S04"):
    # S01 -30- S02 -30- S03 -30- S04 -30- S05: long edges (42 frames each) so a
    # camped racer has real slack over a parked opponent
    s = Strategy(1001)
    s.graph.load_edges([
        {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": 30,
         "bidirectional": True}
        for a, b in [("S01", "S02"), ("S02", "S03"), ("S03", "S04"), ("S04", "S05")]
    ])
    s.start_node, s.gate_node, s.terminal_node = "S01", gate, "S05"
    s.chokes = s.graph.choke_points("S01", gate)
    s._my_team = "RED"
    return s


class PerOpRaceMarginTests(unittest.TestCase):
    """Pre-choke ops are allowed iff the lead survives, unless the higher-priority
    adjacent-wait ambush is active."""

    ICE_NODES = [
        {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
        {"nodeId": "S02", "hasObstacle": False, "resourceStock": {"ICE_BOX": 1}},
        {"nodeId": "S03", "hasObstacle": False, "resourceStock": {}},
        {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        {"nodeId": "S05", "hasObstacle": False, "resourceStock": {}},
    ]

    def test_camped_claims_ice_box_when_lead_survives_it(self) -> None:
        s = _spaced_line_strategy(gate="S04")
        # Camped on S03; opponent parked two hops back, so local adjacent-wait
        # does not preempt the old spare-time calculation.
        nodes = [dict(n) for n in self.ICE_NODES]
        nodes[2] = dict(nodes[2])
        nodes[2]["resourceStock"] = {"ICE_BOX": 1}
        act = s.decide(_inq(50, _me("S03"), _opp("S01"), nodes=nodes))
        self.assertEqual(
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S03",
              "resourceType": "ICE_BOX"}], act)

    def test_camped_skips_ice_box_when_race_is_tight(self) -> None:
        s = _line_strategy(gate="S04")  # 10-distance edges: opp only 14 frames out
        nodes = [dict(n) for n in self.ICE_NODES]
        act = s.decide(_inq(50, _me("S02"), _opp("S01"), nodes=nodes))
        self.assertEqual([{"action": "WAIT"}], act)

    def test_camped_short_task_claims_long_task_waits(self) -> None:
        def task(process_round):
            return [{
                "taskId": "T_S03", "nodeId": "S03", "taskTemplateId": "T02",
                "processType": "STATION_PROCESS", "processRound": process_round,
                "score": 30, "active": True, "completed": False, "failed": False,
                "ownerPlayerId": 0, "expireRound": 500,
            }]
        nodes = [{"nodeId": n, "hasObstacle": False, "resourceStock": {}}
                 for n in ("S01", "S02", "S03", "S04", "S05")]

        # Opponent is two hops back; short op 3 -> lead survives, claim.
        s = _spaced_line_strategy(gate="S04")
        act = s.decide(_inq(50, _me("S03"), _opp("S01"), nodes=nodes, tasks=task(3)))
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_S03"}], act)

        # Long op loses the race, so wait for the freeze instead.
        s = _spaced_line_strategy(gate="S04")
        act = s.decide(_inq(50, _me("S03"), _opp("S01"), nodes=nodes, tasks=task(80)))
        self.assertEqual([{"action": "WAIT"}], act)


class FarmModeTests(unittest.TestCase):
    def test_does_not_preclear_future_task_obstacle_before_freeze(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S14", "S15"
        s.graph.load_edges([
            {"fromNodeId": "S09", "toNodeId": "S10", "routeType": "ROAD",
             "distance": 40, "bidirectional": True},
            {"fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD",
             "distance": 36, "bidirectional": True},
            {"fromNodeId": "S11", "toNodeId": "S14", "routeType": "BRANCH",
             "distance": 15, "bidirectional": True},
            {"fromNodeId": "S10", "toNodeId": "S13", "routeType": "BRANCH",
             "distance": 27, "bidirectional": True},
            {"fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD",
             "distance": 18, "bidirectional": True},
            {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ])
        s.graph.process_rounds = {"S11": 5, "S13": 5}
        s.chokes = ["S10"]
        nodes = [
            {"nodeId": "S09", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S10", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S11", "hasObstacle": True, "processRound": 5,
             "resourceStock": {}},
            {"nodeId": "S13", "hasObstacle": False, "processRound": 5,
             "resourceStock": {}},
            {"nodeId": "S14", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S15", "hasObstacle": False, "resourceStock": {}},
        ]
        task = [{
            "taskId": "T_S11", "nodeId": "S11", "taskTemplateId": "T11",
            "processType": "STATION_PROCESS", "processRound": 4, "score": 60,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 500,
        }]
        me = _me(
            "S09", state="MOVING", nextNodeId="S10", routeEdgeId="E05",
            edgeProgressMs=50000, edgeTotalMs=55200, edgeProgressPermille=905,
            squadAvailable=2,
        )
        opp = _opp(
            "S09", state="MOVING", nextNodeId="S10", routeEdgeId="E05",
            edgeProgressMs=10000, edgeTotalMs=55200, edgeProgressPermille=181,
        )

        act = s.decide(_inq(250, me, opp, nodes=nodes, tasks=task))

        self.assertEqual({"action": "MOVE", "targetNodeId": "S10"}, act[0])
        self.assertNotIn({"action": "SQUAD_CLEAR", "targetNodeId": "S11"}, act)

    def test_farm_mode_preclears_task_obstacle_with_squad(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S14", "S15"
        s.graph.load_edges([
            {"fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD",
             "distance": 36, "bidirectional": True},
            {"fromNodeId": "S11", "toNodeId": "S14", "routeType": "BRANCH",
             "distance": 15, "bidirectional": True},
            {"fromNodeId": "S10", "toNodeId": "S13", "routeType": "BRANCH",
             "distance": 27, "bidirectional": True},
            {"fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD",
             "distance": 18, "bidirectional": True},
            {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ])
        s.graph.process_rounds = {"S11": 5, "S13": 5}
        s.chokes = ["S10"]
        s._task_priority_mode = True
        nodes = [
            {"nodeId": "S10", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S11", "hasObstacle": True, "processRound": 5,
             "resourceStock": {}},
            {"nodeId": "S13", "hasObstacle": False, "processRound": 5,
             "resourceStock": {}},
            {"nodeId": "S14", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S15", "hasObstacle": False, "resourceStock": {}},
        ]
        task = [{
            "taskId": "T_S11", "nodeId": "S11", "taskTemplateId": "T11",
            "processType": "STATION_PROCESS", "processRound": 4, "score": 60,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 500,
        }]

        act = s.decide(_inq(283, _me("S10", squadAvailable=2), _opp("S09"), nodes=nodes, tasks=task))

        self.assertIn({"action": "SQUAD_CLEAR", "targetNodeId": "S11"}, act)

    def test_farm_mode_main_clears_task_obstacle_without_squad(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S14", "S15"
        s.graph.load_edges([
            {"fromNodeId": "S10", "toNodeId": "S11", "routeType": "ROAD",
             "distance": 36, "bidirectional": True},
            {"fromNodeId": "S11", "toNodeId": "S14", "routeType": "BRANCH",
             "distance": 15, "bidirectional": True},
            {"fromNodeId": "S10", "toNodeId": "S13", "routeType": "BRANCH",
             "distance": 27, "bidirectional": True},
            {"fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD",
             "distance": 18, "bidirectional": True},
            {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ])
        s.graph.process_rounds = {"S11": 5, "S13": 5}
        s.chokes = ["S10"]
        s._first_guard_node = "S10"
        nodes = [
            {"nodeId": "S10", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 6}},
            {"nodeId": "S11", "hasObstacle": True, "processRound": 5,
             "resourceStock": {}},
            {"nodeId": "S13", "hasObstacle": False, "processRound": 5,
             "resourceStock": {}},
            {"nodeId": "S14", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S15", "hasObstacle": False, "resourceStock": {}},
        ]
        task = [{
            "taskId": "T_S11", "nodeId": "S11", "taskTemplateId": "T11",
            "processType": "STATION_PROCESS", "processRound": 4, "score": 60,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 500,
        }]

        act = s.decide(_inq(283, _me("S10", squadAvailable=0), _opp("S09"), nodes=nodes, tasks=task))

        self.assertTrue(s._task_priority_mode)
        self.assertEqual([{"action": "CLEAR", "targetNodeId": "S11"}], act)

    def test_farm_mode_claims_ice_box_ahead(self) -> None:
        s = _line_strategy(gate="S04")
        s._first_guard_node = "S02"
        nodes = [
            {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            {"nodeId": "S02", "hasObstacle": False, "resourceStock": {},
             "guard": {"active": True, "ownerTeamId": "RED", "defense": 3}},
            {"nodeId": "S03", "hasObstacle": False, "resourceStock": {"ICE_BOX": 1}},
            {"nodeId": "S04", "hasObstacle": False, "resourceStock": {}},
        ]

        act = s.decide(_inq(70, _me("S03"), _opp("S01"), nodes=nodes))

        self.assertEqual(
            [{"action": "CLAIM_RESOURCE", "targetNodeId": "S03",
              "resourceType": "ICE_BOX"}], act)

    def test_farm_mode_never_backtracks_past_our_guard(self) -> None:
        # a juicy task sits BEHIND our freeze guard -> unreachable by doctrine
        # (we farm forward only); keep walking to the gate
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
            "taskId": "T_S01", "nodeId": "S01", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 3, "score": 60,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 500,
        }]

        act = s.decide(_inq(70, _me("S03"), _opp("S01"), nodes=nodes, tasks=tasks))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S04"}], act)


class OpeningChokeRaceTests(unittest.TestCase):
    def test_opening_score_puts_choke_race_before_delivery(self) -> None:
        # S01 -10- S02(process 5, choke) -10- S03(gate) -10- S04(terminal)
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S03", "S04"
        s.graph.load_edges([
            {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": 10,
             "bidirectional": True}
            for a, b in [("S01", "S02"), ("S02", "S03"), ("S03", "S04")]
        ])
        s.graph.process_rounds = {"S02": 5}
        s.chokes = s.graph.choke_points("S01", "S03")
        nodes_by_id = {
            n: {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04")
        }

        score, path = s._opening_route_score(
            ["S01", "S02", "S03"], _me("S01"), 1, [], nodes_by_id
        )

        race, total = score
        # race = ARRIVAL at S02 (14 frames), excluding its own processing;
        # total = full delivery: 14 + 5 + 14 (to gate) + 6 verify + 14 + 2 deliver
        self.assertEqual(14, race)
        self.assertEqual(55, total)
        self.assertEqual(["S01", "S02", "S03"], path)


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

    def test_route_plan_uses_own_scout_marker_for_process_eta(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "P", "P"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "P", "routeType": "ROAD",
             "distance": 1, "bidirectional": True},
        ])
        s.graph.process_rounds = {"P": 6}
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "P": {"nodeId": "P", "hasObstacle": False, "resourceStock": {},
                  "processType": "TRANSFER",
                  "scouted": [{"teamId": "RED", "remainRound": 10,
                               "processReduceRound": 3, "remainingTriggers": 1}]},
        }

        self.assertEqual(5, s._route_plan("S01", "P", _me("S01"), nodes).frames)

    def test_route_plan_ignores_enemy_scout_marker_for_process_eta(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "P", "P"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "P", "routeType": "ROAD",
             "distance": 1, "bidirectional": True},
        ])
        s.graph.process_rounds = {"P": 6}
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "P": {"nodeId": "P", "hasObstacle": False, "resourceStock": {},
                  "processType": "TRANSFER",
                  "scouted": [{"teamId": "BLUE", "remainRound": 10,
                               "processReduceRound": 3, "remainingTriggers": 1}]},
        }

        self.assertEqual(8, s._route_plan("S01", "P", _me("S01"), nodes).frames)

    def test_route_plan_ignores_scout_marker_that_expires_before_processing(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "P", "P"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "P", "routeType": "ROAD",
             "distance": 1, "bidirectional": True},
        ])
        s.graph.process_rounds = {"P": 6}
        nodes = {
            "S01": {"nodeId": "S01", "hasObstacle": False, "resourceStock": {}},
            "P": {"nodeId": "P", "hasObstacle": False, "resourceStock": {},
                  "processType": "TRANSFER",
                  "scouted": [{"teamId": "RED", "remainRound": 1,
                               "processReduceRound": 3, "remainingTriggers": 1}]},
        }

        self.assertEqual(
            8,
            s._route_plan("S01", "P", _me("S01"), nodes, round_no=100).frames,
        )

    def test_delivery_eta_uses_scout_marker_for_gate_verify(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S14", "S15"
        s._left_start = True
        s.graph.load_edges([
            {"fromNodeId": "S13", "toNodeId": "S14", "routeType": "ROAD",
             "distance": 1, "bidirectional": True},
            {"fromNodeId": "S14", "toNodeId": "S15", "routeType": "ROAD",
             "distance": 1, "bidirectional": True},
        ])
        nodes = {
            "S13": {"nodeId": "S13", "hasObstacle": False, "resourceStock": {}},
            "S14": {"nodeId": "S14", "hasObstacle": False, "resourceStock": {},
                    "scouted": [{"teamId": "RED", "remainRound": 10,
                                 "processReduceRound": 3, "remainingTriggers": 1}]},
            "S15": {"nodeId": "S15", "hasObstacle": False, "resourceStock": {}},
        }

        self.assertEqual(9, s._frames_to_deliver("S13", _me("S13"), nodes, 100))

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
        me = _me("S02", freshness=95, goodFruit=20)

        for ri in (1, 2):
            act = s._card(me, [self._contest(ri)], 50)
            self.assertEqual("XIAN_GONG", act[0]["card"])

        # a SECOND (different) contest also gets XIAN_GONG (the bug was it didn't)
        c2 = self._contest(1); c2["contestId"] = "C2"
        act = s._card(me, [c2], 80)
        self.assertEqual("XIAN_GONG", act[0]["card"])

    def test_uses_fallback_card_when_good_fruit_is_gone(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=79, goodFruit=0, guardActionPoint=4)

        act = s._card(me, [self._contest(1)], 50)

        self.assertEqual("BING_ZHENG", act[0]["card"])

    def test_low_freshness_uses_bing_zheng_over_invalid_xian_gong(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=79, goodFruit=20, guardActionPoint=4)

        act = s._card(me, [self._contest(1)], 50)

        self.assertEqual("BING_ZHENG", act[0]["card"])

    def test_low_freshness_abstains_without_bing_zheng(self) -> None:
        s = _line_strategy()
        me = _me(
            "S02", freshness=79, goodFruit=20, guardActionPoint=0,
            resources={"PASS_TOKEN": 1},
        )

        act = s._card(me, [self._contest(1)], 50)

        self.assertEqual("ABSTAIN", act[0]["card"])

    def test_low_freshness_abstains_when_already_up_two_zero(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=79, goodFruit=20, guardActionPoint=4)

        act = s._card(me, [self._contest(3, red_point=2, blue_point=0)], 50)

        self.assertEqual("ABSTAIN", act[0]["card"])

    def test_third_tap_abstains_when_already_up_two_zero(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=95, goodFruit=20)

        act = s._card(me, [self._contest(3, red_point=2, blue_point=0)], 50)

        # already won 2-0 -> 3rd tap is moot, save the card
        self.assertEqual("ABSTAIN", act[0]["card"])

    def test_third_tap_uses_xian_gong_unless_already_up_two_zero(self) -> None:
        s = _line_strategy()
        me = _me("S02", freshness=95, goodFruit=20)

        act = s._card(me, [self._contest(3, red_point=1, blue_point=1)], 50)

        self.assertEqual("XIAN_GONG", act[0]["card"])

    def test_third_tap_abstains_when_already_up_two_zero_on_blue_side_too(self) -> None:
        s = Strategy(2002)
        me = {"playerId": 2002, "goodFruit": 20}

        act = s._card(me, [self._contest(3, red_point=0, blue_point=2)], 50)

        self.assertEqual("ABSTAIN", act[0]["card"])

    def test_low_freshness_blue_side_abstains_when_already_up_two_zero(self) -> None:
        s = Strategy(2002)
        me = {"playerId": 2002, "freshness": 79, "goodFruit": 20, "guardActionPoint": 4}

        act = s._card(me, [self._contest(3, red_point=0, blue_point=2)], 50)

        self.assertEqual("ABSTAIN", act[0]["card"])


class DeliveryAbandonTests(unittest.TestCase):
    def test_eta_200_abandons_at_round_400_not_399(self) -> None:
        # Once the best delivery ETA reaches the 600-frame deadline, stop trying
        # to force delivery and switch to score farming.
        s = Strategy(1001)
        s._frames_to_deliver = lambda *args, **kwargs: 200

        self.assertFalse(s._should_abandon_delivery("S01", _me("S01"), 399, {}))
        self.assertTrue(s._should_abandon_delivery("S01", _me("S01"), 400, {}))

    def test_switches_to_task_priority_when_delivery_eta_misses_deadline(self) -> None:
        s = Strategy(1001)
        s.start_node, s.gate_node, s.terminal_node = "S01", "S03", "S04"
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
             "distance": 30, "bidirectional": True},
            {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD",
             "distance": 30, "bidirectional": True},
            {"fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD",
             "distance": 30, "bidirectional": True},
            {"fromNodeId": "S01", "toNodeId": "T1", "routeType": "ROAD",
             "distance": 5, "bidirectional": True},
        ])
        nodes = [
            {"nodeId": n, "hasObstacle": False, "resourceStock": {}}
            for n in ("S01", "S02", "S03", "S04", "T1")
        ]
        tasks = [{
            "taskId": "T_SIDE", "nodeId": "T1", "taskTemplateId": "T02",
            "processType": "STATION_PROCESS", "processRound": 3, "score": 60,
            "active": True, "completed": False, "failed": False,
            "ownerPlayerId": 0, "expireRound": 590,
        }]

        act = s.decide(_inq(540, _me("S01"), _opp("S01"), nodes=nodes, tasks=tasks))

        self.assertTrue(s._task_priority_mode)
        self.assertTrue(s._delivery_abandoned)
        self.assertEqual([{"action": "MOVE", "targetNodeId": "T1"}], act)


class RushTacticTests(unittest.TestCase):
    def test_uses_rush_speed_as_soon_as_rush_phase_allows_it(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me(
            "S02", state="MOVING", nextNodeId="S03", routeEdgeId="E02",
            goodFruit=20, rushTacticUsedCount=0, buffs=[],
        )

        act = s.decide(_inq(451, me, _opp("S01"), phase="RUSH"))

        # RUSH_SPEED is the main-car action for this frame (issued only while MOVING)
        self.assertEqual([{"action": "RUSH_SPEED"}], act)

    def test_does_not_use_rush_speed_over_active_horse(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me(
            "S02", state="MOVING", nextNodeId="S03", routeEdgeId="E02",
            goodFruit=20, rushTacticUsedCount=0,
            buffs=[{"type": "FAST_HORSE", "remainingRound": 5}],
        )

        act = s.decide(_inq(451, me, _opp("S01"), phase="RUSH"))

        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], act)


def _guard_nodes(guard_node, defense, team="RED", node_type=None):
    nodes = [{"nodeId": f"S0{i}", "hasObstacle": False, "resourceStock": {}}
             for i in range(1, 6)]
    for n in nodes:
        if n["nodeId"] == guard_node:
            n["guard"] = {"active": defense > 0, "ownerTeamId": team,
                          "defense": defense}
            if node_type:
                n["nodeType"] = node_type
    return nodes


def _weaken_dispatch(order, target, round_no):
    return {"type": "SQUAD_DISPATCH", "round": round_no,
            "payload": {"orderId": order, "playerId": 2002,
                        "action": "SQUAD_WEAKEN", "targetNodeId": target,
                        "completeRound": round_no + 3}}


class GuardReinforceTests(unittest.TestCase):
    def _decide(self, s, me, opp, nodes, events, round_no=50):
        inq = _inq(round_no, me, opp, nodes=nodes)
        inq["events"] = events
        return s.decide(inq)

    def test_reinforces_when_enemy_weaken_targets_our_guard(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S01", squadAvailable=4)
        nodes = _guard_nodes("S03", defense=4)
        act = self._decide(s, me, _opp("S02"), nodes,
                           [_weaken_dispatch("W1", "S03", 49)])
        self.assertIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act)

    def test_one_reinforce_per_enemy_order(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S01", squadAvailable=8)
        nodes = _guard_nodes("S03", defense=4)
        ev = [_weaken_dispatch("W1", "S03", 49)]
        act1 = self._decide(s, me, _opp("S02"), nodes, ev, round_no=50)
        # same order re-observed (dispatch + landing share the orderId)
        landing = {"type": "SQUAD_WEAKEN", "round": 52,
                   "payload": {"orderId": "W1", "playerId": 2002,
                               "targetNodeId": "S03", "before": 4, "after": 2}}
        act2 = self._decide(s, me, _opp("S02"), nodes, [landing], round_no=53)
        self.assertIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act1)
        self.assertNotIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act2)

    def test_holds_reinforce_while_guard_at_cap_then_answers(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S01", squadAvailable=4)
        at_cap = _guard_nodes("S03", defense=6)
        act1 = self._decide(s, me, _opp("S02"), at_cap,
                            [_weaken_dispatch("W1", "S03", 49)], round_no=50)
        self.assertNotIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act1)
        # weaken landed -> defense below cap -> the held debt is answered
        dropped = _guard_nodes("S03", defense=4)
        act2 = self._decide(s, me, _opp("S02"), dropped, [], round_no=53)
        self.assertIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act2)

    def test_never_reinforces_a_dead_guard(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S01", squadAvailable=4)
        live = _guard_nodes("S03", defense=2)
        self._decide(s, me, _opp("S02"), live,
                     [_weaken_dispatch("W1", "S03", 49),
                      _weaken_dispatch("W2", "S03", 49)], round_no=50)
        dead = _guard_nodes("S03", defense=0)
        act = self._decide(s, me, _opp("S02"), dead, [], round_no=53)
        self.assertNotIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act)

    def test_needs_two_squad_members(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S01", squadAvailable=1)
        nodes = _guard_nodes("S03", defense=4)
        act = self._decide(s, me, _opp("S02"), nodes,
                           [_weaken_dispatch("W1", "S03", 49)])
        self.assertNotIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S03"}, act)


class GateAmbushTests(unittest.TestCase):
    # gate S04, terminal S05 on the line map; we are parked on the gate
    def test_freezes_opponent_committing_into_the_gate(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=0)
        opp = _opp("S03", state="MOVING", nextNodeId="S04",
                   routeEdgeId="E03", edgeProgressPermille=0)
        act = s.decide(_inq(500, me, opp, phase="RUSH"))
        self.assertIn(
            {"action": "SET_GUARD", "targetNodeId": "S04", "extraGoodFruit": 1},
            act,
        )

    def test_camps_the_gate_while_opponent_approaches(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=0)
        act = s.decide(_inq(500, me, _opp("S02"), phase="RUSH"))
        self.assertEqual({"action": "WAIT"}, act[0])

    def test_delivers_once_opponent_reaches_the_gate_unfrozen(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1)
        act = s.decide(_inq(500, me, _opp("S04"), phase="RUSH"))
        self.assertNotEqual({"action": "WAIT"}, act[0])
        self.assertNotIn("SET_GUARD", [a["action"] for a in act])

    def test_own_deadline_outranks_the_ambush(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1)
        act = s.decide(_inq(TOTAL_ROUNDS - 21, me, _opp("S02"), phase="RUSH"))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S05"}], act)

    def test_missed_deadline_abandons_gate_delivery(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1)
        act = s.decide(_inq(TOTAL_ROUNDS - 12, me, _opp("S02"), phase="RUSH"))
        self.assertTrue(s._delivery_abandoned)
        self.assertEqual([{"action": "WAIT"}], act)

    def test_still_camps_when_opponent_eta_misses_but_is_behind_gate(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1)
        act = s.decide(_inq(570, me, _opp("S01"), phase="RUSH"))
        self.assertEqual([{"action": "WAIT"}], act)

    def test_opponent_retired_means_go_deliver(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1)
        act = s.decide(_inq(500, me, _opp("S02", retired=True), phase="RUSH"))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S05"}], act)

    def test_trap_armed_means_hold_gate_until_deadline(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1)
        opp = _opp("S03", state="MOVING", nextNodeId="S04",
                   routeEdgeId="E03", edgeProgressPermille=500)
        nodes = _guard_nodes("S04", defense=4)
        act = s.decide(_inq(510, me, opp, nodes=nodes, phase="RUSH"))
        self.assertEqual([{"action": "WAIT"}], act)

    def test_reinforces_gate_guard_while_holding(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=True, goodFruit=20, rushTacticUsedCount=1,
                 squadAvailable=4)
        nodes = _guard_nodes("S04", defense=2)
        inq = _inq(510, me, _opp("S02"), nodes=nodes, phase="RUSH")
        inq["events"] = [_weaken_dispatch("W_GATE", "S04", 509)]
        act = s.decide(inq)
        self.assertIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S04"}, act)
        self.assertIn({"action": "WAIT"}, act)

    def test_gate_watch_does_not_block_rush_verify(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=False, goodFruit=20, rushTacticUsedCount=1)
        act = s.decide(_inq(500, me, _opp("S02"), phase="RUSH"))
        self.assertEqual([{"action": "VERIFY_GATE"}], act)

    def test_arms_the_trap_pre_rush_while_waiting_at_the_gate(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S04", verified=False, goodFruit=20)
        opp = _opp("S03", state="MOVING", nextNodeId="S04",
                   routeEdgeId="E03", edgeProgressPermille=0)
        act = s.decide(_inq(300, me, opp, phase="NORMAL"))
        self.assertIn(
            {"action": "SET_GUARD", "targetNodeId": "S04", "extraGoodFruit": 1},
            act,
        )


if __name__ == "__main__":
    unittest.main()
