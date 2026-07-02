import unittest

from lychee_basic_client.graph import Graph, move_frames


class GraphTests(unittest.TestCase):
    def test_move_frames_uses_distance_and_coef(self) -> None:
        # ROAD coef 1380: ceil(30 * 1380 / 1000) = ceil(41.4) = 42
        self.assertEqual(42, move_frames(30, "ROAD"))
        # WATER coef 1250: ceil(44 * 1250 / 1000) = ceil(55.0) = 55
        self.assertEqual(55, move_frames(44, "WATER"))

    def _line_graph(self) -> Graph:
        g = Graph()
        g.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD",
                 "distance": 30, "bidirectional": True},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD",
                 "distance": 25, "bidirectional": True},
            ]
        )
        return g

    def test_shortest_path_and_next_hop(self) -> None:
        g = self._line_graph()
        self.assertEqual(["S01", "S02", "S03"], g.shortest_path("S01", "S03"))
        self.assertEqual("S02", g.next_hop("S01", "S03"))
        self.assertEqual(["S01"], g.shortest_path("S01", "S01"))
        self.assertIsNone(g.next_hop("S01", "S01"))

    def test_prefers_lower_freshness_loss_route(self) -> None:
        # Two ways S01 -> S03: direct MOUNTAIN (high loss) vs via S02 on ROAD/WATER.
        g = Graph()
        g.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S03", "routeType": "MOUNTAIN",
                 "distance": 40, "bidirectional": True},
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "WATER",
                 "distance": 20, "bidirectional": True},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "WATER",
                 "distance": 20, "bidirectional": True},
            ]
        )
        self.assertEqual("S02", g.next_hop("S01", "S03"))


if __name__ == "__main__":
    unittest.main()
