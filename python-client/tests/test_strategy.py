import unittest

from lychee_basic_client.strategy import Strategy


def _strategy_with_line_map() -> Strategy:
    s = Strategy(1001)
    s.gate_node = "S03"
    s.graph.load_edges(
        [
            {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ]
    )
    return s


class SquadPreClearTests(unittest.TestCase):
    def test_dispatches_to_first_obstacle_on_path(self) -> None:
        s = _strategy_with_line_map()
        nodes = {"S02": {"nodeId": "S02", "hasObstacle": True}, "S03": {"nodeId": "S03"}}
        me = {"squadAvailable": 8}
        self.assertEqual(
            {"action": "SQUAD_CLEAR", "targetNodeId": "S02"},
            s._squad_action("S01", nodes, me, "NORMAL"),
        )
        # already dispatched -> no re-dispatch to the same node
        self.assertIsNone(s._squad_action("S01", nodes, me, "NORMAL"))

    def test_gated_by_phase_and_members(self) -> None:
        s = _strategy_with_line_map()
        nodes = {"S02": {"nodeId": "S02", "hasObstacle": True}, "S03": {"nodeId": "S03"}}
        self.assertIsNone(s._squad_action("S01", nodes, {"squadAvailable": 8}, "RUSH"))
        self.assertIsNone(s._squad_action("S01", nodes, {"squadAvailable": 1}, "NORMAL"))

    def test_none_when_no_obstacle_on_path(self) -> None:
        s = _strategy_with_line_map()
        nodes = {"S02": {"nodeId": "S02"}, "S03": {"nodeId": "S03"}}
        self.assertIsNone(s._squad_action("S01", nodes, {"squadAvailable": 8}, "NORMAL"))


class ContestDedupTests(unittest.TestCase):
    def test_plays_card_once_per_tap(self) -> None:
        s = Strategy(1001)
        s.gate_node = "S14"
        me = {"playerId": 1001, "state": "CONTESTING", "guardActionPoint": 2, "resources": {}}
        contest = {
            "contestId": "C1", "contestType": "TASK", "roundIndex": 1,
            "redPlayerId": 1001, "bluePlayerId": 2002, "resolved": False,
            "deadlineRound": 200,
        }
        args = ("CONTESTING", "S07", "NORMAL", 100, [], [contest], {})
        first = s._main_action(me, *args)
        self.assertEqual("WINDOW_CARD", first[0]["action"])
        # same tap again -> do NOT replay (would risk a server error / retire)
        self.assertEqual([], s._main_action(me, *args))
        # next tap -> play again
        contest["roundIndex"] = 2
        second = s._main_action(me, *args)
        self.assertEqual("WINDOW_CARD", second[0]["action"])


def _node(nid, process_round=0, obstacle=False, ice=0):
    n = {"nodeId": nid, "processRound": process_round, "effectiveCombatCount": 0,
         "guardBlockCount": 0, "hasObstacle": obstacle, "resourceStock": {}}
    if ice:
        n["resourceStock"] = {"ICE_BOX": ice}
    return n


def _me(node, state="IDLE"):
    return {"playerId": 1001, "state": state, "currentNodeId": node, "nextNodeId": None,
            "routeEdgeId": None, "resources": {}, "freshness": 90.0, "goodFruit": 100,
            "verified": False, "delivered": False, "retired": False,
            "squadAvailable": 0, "rushTacticUsedCount": 1}


def _inq(round_no, node, state, nodes, events=None):
    return {"round": round_no, "phase": "NORMAL", "players": [_me(node, state)],
            "nodes": nodes, "tasks": [], "contests": [], "events": events or [],
            "actionResults": []}


class ReprocessOnRevisitTests(unittest.TestCase):
    def _strat(self):
        s = Strategy(1001)
        s.gate_node = "S03"
        s.graph.load_edges([
            {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
            {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD",
             "distance": 10, "bidirectional": True},
        ])
        return s

    def test_reprocesses_a_station_on_revisit(self) -> None:
        s = self._strat()
        nodes = [_node("S01"), _node("S02", process_round=4), _node("S03")]
        done = [{"type": "PROCESS_COMPLETE", "payload": {"playerId": 1001, "targetNodeId": "S02"}}]

        # arrive S02 -> must PROCESS
        self.assertEqual("PROCESS", s.decide(_inq(1, "S02", "IDLE", nodes))[0]["action"])
        # server confirms completion -> now free to move on
        self.assertEqual("MOVE", s.decide(_inq(2, "S02", "IDLE", nodes, done))[0]["action"])
        # leave to S03 (node changes -> processed cleared)
        s.decide(_inq(3, "S03", "IDLE", nodes))
        # come back to S02 -> must PROCESS AGAIN, not MOVE (the dead-lock bug)
        self.assertEqual("PROCESS", s.decide(_inq(4, "S02", "IDLE", nodes))[0]["action"])


class WaypointTests(unittest.TestCase):
    def _line(self) -> Strategy:
        s = Strategy(1001)
        s.gate_node = "S05"
        s.graph.load_edges([
            {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": 10,
             "bidirectional": True}
            for a, b in [("S01", "S02"), ("S02", "S03"), ("S03", "S04"), ("S04", "S05")]
        ])
        return s

    def _task(self, node):
        return [{"taskId": "T", "taskTemplateId": "T01", "nodeId": node, "score": 30,
                 "active": True, "completed": False, "failed": False,
                 "ownerPlayerId": 0, "protectionPlayerId": 0, "expireRound": 999}]

    def test_detours_for_a_worthwhile_task(self) -> None:
        s = self._line()
        s.task_base = 0
        # a task worth 30 (x2.5 below 90) easily beats the detour freshness cost
        self.assertEqual("S04", s._best_waypoint("S03", {}, self._task("S04"), _me("S03"), 100))

    def test_no_waypoint_once_task_target_reached(self) -> None:
        s = self._line()
        s.task_base = 130  # at the cap -> tasks are worth 0 -> no detour
        self.assertIsNone(s._best_waypoint("S03", {}, self._task("S04"), _me("S03"), 100))


class GuardHandlingTests(unittest.TestCase):
    def _diamond(self) -> Strategy:
        # S01 -> S02 -> S04  and  S01 -> S03 -> S04  (two ways to the gate S04)
        s = Strategy(1001)
        s.gate_node = "S04"
        s.graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
                 "distance": 10, "bidirectional": True},
                {"fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD",
                 "distance": 10, "bidirectional": True},
                {"fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD",
                 "distance": 10, "bidirectional": True},
                {"fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD",
                 "distance": 10, "bidirectional": True},
            ]
        )
        return s

    def test_reroutes_around_guard_when_alternative_exists(self) -> None:
        s = self._diamond()
        s._guard_blocked.add("S02")
        # S02 guarded -> detour via S03 with a normal MOVE, not a forced pass
        self.assertEqual([{"action": "MOVE", "targetNodeId": "S03"}], s._advance("S01", {}))

    def test_forces_through_guard_on_a_funnel(self) -> None:
        s = Strategy(1001)
        s.gate_node = "S03"
        s.graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
                 "distance": 10, "bidirectional": True},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD",
                 "distance": 10, "bidirectional": True},
            ]
        )
        s._guard_blocked.add("S02")  # only way to the gate is through the guard
        self.assertEqual(
            [{"action": "FORCED_PASS", "targetNodeId": "S02"}], s._advance("S01", {})
        )

    def test_step_to_forced_passes_obstacle_and_guard(self) -> None:
        s = Strategy(1001)
        s._guard_blocked.add("SG")
        self.assertEqual(
            {"action": "FORCED_PASS", "targetNodeId": "SO"},
            s._step_to("SO", {"SO": {"hasObstacle": True}}),
        )
        self.assertEqual(
            {"action": "FORCED_PASS", "targetNodeId": "SG"}, s._step_to("SG", {})
        )
        self.assertEqual({"action": "MOVE", "targetNodeId": "SF"}, s._step_to("SF", {}))


class TravellingStateTests(unittest.TestCase):
    def test_waiting_with_stale_route_edge_is_not_travelling(self) -> None:
        s = Strategy(1001)
        me = {"state": "WAITING", "currentNodeId": "S02", "nextNodeId": None,
              "routeEdgeId": "E01"}
        self.assertFalse(s._is_travelling(me, "WAITING", "S02"))

    def test_waiting_with_next_node_is_travelling(self) -> None:
        s = Strategy(1001)
        me = {"state": "WAITING", "currentNodeId": "S02", "nextNodeId": "S03",
              "routeEdgeId": "E02"}
        self.assertTrue(s._is_travelling(me, "WAITING", "S02"))

if __name__ == "__main__":
    unittest.main()
