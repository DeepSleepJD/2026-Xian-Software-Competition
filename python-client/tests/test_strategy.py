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


if __name__ == "__main__":
    unittest.main()
