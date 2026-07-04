import unittest

from lychee_basic_client.graph import Graph, move_frames


class GraphTests(unittest.TestCase):
    def test_move_frames_uses_distance_and_route_type(self) -> None:
        self.assertEqual(42, move_frames(30, "ROAD"))
        self.assertEqual(55, move_frames(44, "WATER"))

    def test_shortest_path_and_next_hop(self) -> None:
        graph = Graph()
        graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 30},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 25},
            ]
        )

        self.assertEqual(["S01", "S02", "S03"], graph.shortest_path("S01", "S03"))
        self.assertEqual("S02", graph.next_hop("S01", "S03"))
        self.assertEqual(["S01"], graph.shortest_path("S01", "S01"))
        self.assertIsNone(graph.next_hop("S01", "S01"))

    def test_prefers_lower_freshness_loss_route(self) -> None:
        graph = Graph()
        graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S03", "routeType": "MOUNTAIN", "distance": 40},
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "WATER", "distance": 20},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "WATER", "distance": 20},
            ]
        )

        self.assertEqual("S02", graph.next_hop("S01", "S03"))

    def test_fastest_path_can_penalize_obstacles(self) -> None:
        graph = Graph()
        graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10},
                {"fromNodeId": "S02", "toNodeId": "S04", "routeType": "ROAD", "distance": 10},
                {"fromNodeId": "S01", "toNodeId": "S03", "routeType": "ROAD", "distance": 20},
                {"fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD", "distance": 20},
            ]
        )

        self.assertEqual(["S01", "S02", "S04"], graph.fastest_path("S01", "S04"))
        self.assertEqual(
            ["S01", "S03", "S04"],
            graph.fastest_path("S01", "S04", obstacles={"S02"}, obstacle_penalty=100),
        )

    def test_choke_points_are_ordered_nearest_destination_first(self) -> None:
        graph = Graph()
        graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 10},
                {"fromNodeId": "S03", "toNodeId": "S04", "routeType": "ROAD", "distance": 10},
                {"fromNodeId": "S04", "toNodeId": "S05", "routeType": "ROAD", "distance": 10},
            ]
        )

        self.assertEqual(["S04", "S03", "S02"], graph.choke_points("S01", "S05"))

    def test_avoid_disconnects_a_cut_vertex(self) -> None:
        graph = Graph()
        graph.load_edges(
            [
                {"fromNodeId": "S01", "toNodeId": "S02", "routeType": "ROAD", "distance": 10},
                {"fromNodeId": "S02", "toNodeId": "S03", "routeType": "ROAD", "distance": 10},
            ]
        )

        self.assertIsNone(graph.shortest_path("S01", "S03", avoid={"S02"}))
        self.assertEqual(float("inf"), graph.path_frames("S01", "S03", avoid={"S02"}))


if __name__ == "__main__":
    unittest.main()
