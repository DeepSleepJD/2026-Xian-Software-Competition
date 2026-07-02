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


if __name__ == "__main__":
    unittest.main()
