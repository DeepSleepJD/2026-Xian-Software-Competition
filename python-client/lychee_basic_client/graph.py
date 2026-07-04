"""Map graph and route-planning helpers."""
import heapq
import math
from typing import Any, Optional


ROUTE_COST_COEF = {
    "ROAD": 1380,
    "WATER": 1250,
    "MOUNTAIN": 1780,
    "BRANCH": 1550,
}

ROUTE_FRESHNESS_LOSS = {
    "ROAD": 0.055,
    "WATER": 0.045,
    "MOUNTAIN": 0.07,
    "BRANCH": 0.065,
}

IDLE_FRESHNESS_LOSS = 0.05
BASE_MOVE_PER_FRAME = 1000


def move_frames(distance: int, route_type: str) -> int:
    coef = ROUTE_COST_COEF.get(route_type, 1500)
    required_moves = math.ceil(max(1, distance) * coef)
    return max(1, math.ceil(required_moves / BASE_MOVE_PER_FRAME))


class Graph:
    def __init__(self) -> None:
        self.adj: dict[str, list[tuple[str, str, int]]] = {}
        self.process_rounds: dict[str, int] = {}

    def load_edges(self, edges: list[dict[str, Any]]) -> None:
        self.adj = {}
        for edge in edges:
            from_node = edge.get("fromNodeId") or edge.get("fromNode")
            to_node = edge.get("toNodeId") or edge.get("toNode")
            if not isinstance(from_node, str) or not isinstance(to_node, str):
                continue
            route_type = edge.get("routeType", "ROAD")
            if not isinstance(route_type, str):
                route_type = "ROAD"
            distance = edge.get("distance", 1)
            if not isinstance(distance, int):
                distance = 1
            distance = max(1, distance)

            self.adj.setdefault(from_node, []).append((to_node, route_type, distance))
            if edge.get("bidirectional") is not False:
                self.adj.setdefault(to_node, []).append((from_node, route_type, distance))

    def load_process_nodes(self, process_nodes: list[dict[str, Any]], gate_node: str) -> None:
        self.process_rounds = {}
        for node in process_nodes:
            node_id = node.get("nodeId")
            if not isinstance(node_id, str) or node_id == gate_node:
                continue
            process_round = node.get("processRound", 0)
            if isinstance(process_round, int) and process_round > 0:
                self.process_rounds[node_id] = process_round

    def shortest_path(self, src: str, dst: str, avoid: Optional[set[str]] = None) -> Optional[list[str]]:
        if src == dst:
            return [src]
        dist, prev = self._dijkstra(src, avoid)
        if dst not in dist:
            return None
        return self._restore_path(src, dst, prev)

    def next_hop(self, src: str, dst: str, avoid: Optional[set[str]] = None) -> Optional[str]:
        path = self.shortest_path(src, dst, avoid)
        if path and len(path) >= 2:
            return path[1]
        return None

    def path_cost(self, src: str, dst: str, avoid: Optional[set[str]] = None) -> float:
        if src == dst:
            return 0.0
        dist, _ = self._dijkstra(src, avoid)
        return dist.get(dst, math.inf)

    def path_frames(
        self,
        src: str,
        dst: str,
        speed: float = 1.0,
        avoid: Optional[set[str]] = None,
        obstacles: Optional[set[str]] = None,
        obstacle_penalty: int = 0,
    ) -> float:
        if src == dst:
            return 0
        dist, _ = self._frame_dijkstra(src, speed, avoid, obstacles, obstacle_penalty)
        return dist.get(dst, math.inf)

    def fastest_path(
        self,
        src: str,
        dst: str,
        avoid: Optional[set[str]] = None,
        obstacles: Optional[set[str]] = None,
        obstacle_penalty: int = 40,
    ) -> Optional[list[str]]:
        if src == dst:
            return [src]
        dist, prev = self._frame_dijkstra(src, 1.0, avoid, obstacles, obstacle_penalty)
        if dst not in dist:
            return None
        return self._restore_path(src, dst, prev)

    def fastest_hop(
        self,
        src: str,
        dst: str,
        avoid: Optional[set[str]] = None,
        obstacles: Optional[set[str]] = None,
        obstacle_penalty: int = 40,
    ) -> Optional[str]:
        path = self.fastest_path(src, dst, avoid, obstacles, obstacle_penalty)
        if path and len(path) >= 2:
            return path[1]
        return None

    def edge_frames(self, src: str, dst: str, speed: float = 1.0) -> Optional[int]:
        for neighbor, route_type, distance in self.adj.get(src, []):
            if neighbor == dst:
                coef = ROUTE_COST_COEF.get(route_type, 1500)
                required = math.ceil(distance * coef)
                return max(1, math.ceil(required / (BASE_MOVE_PER_FRAME * max(speed, 0.1))))
        return None

    def choke_points(self, src: str, dst: str) -> list[str]:
        if not self._reachable(src, dst, set()):
            return []
        chokes = [
            node
            for node in list(self.adj)
            if node not in (src, dst) and not self._reachable(src, dst, {node})
        ]
        chokes.sort(key=lambda node: self.path_cost(node, dst))
        return chokes

    def _edge_cost(self, dst: str, route_type: str, distance: int) -> float:
        frames = move_frames(distance, route_type)
        loss = frames * ROUTE_FRESHNESS_LOSS.get(route_type, 0.06)
        loss += self.process_rounds.get(dst, 0) * IDLE_FRESHNESS_LOSS
        return loss

    def _dijkstra(
        self, src: str, avoid: Optional[set[str]] = None
    ) -> tuple[dict[str, float], dict[str, str]]:
        avoid = avoid or set()
        dist: dict[str, float] = {src: 0.0}
        prev: dict[str, str] = {}
        queue: list[tuple[float, str]] = [(0.0, src)]
        while queue:
            cost, node = heapq.heappop(queue)
            if cost > dist.get(node, math.inf):
                continue
            for neighbor, route_type, distance in self.adj.get(node, []):
                if neighbor in avoid:
                    continue
                next_cost = cost + self._edge_cost(neighbor, route_type, distance)
                if next_cost >= dist.get(neighbor, math.inf):
                    continue
                dist[neighbor] = next_cost
                prev[neighbor] = node
                heapq.heappush(queue, (next_cost, neighbor))
        return dist, prev

    def _frame_edge(self, dst: str, route_type: str, distance: int, speed: float) -> int:
        coef = ROUTE_COST_COEF.get(route_type, 1500)
        required = math.ceil(distance * coef)
        frames = max(1, math.ceil(required / (BASE_MOVE_PER_FRAME * max(speed, 0.1))))
        return frames + self.process_rounds.get(dst, 0)

    def _frame_dijkstra(
        self,
        src: str,
        speed: float,
        avoid: Optional[set[str]],
        obstacles: Optional[set[str]] = None,
        obstacle_penalty: int = 0,
    ) -> tuple[dict[str, int], dict[str, str]]:
        avoid = avoid or set()
        obstacles = obstacles or set()
        dist: dict[str, int] = {src: 0}
        prev: dict[str, str] = {}
        queue: list[tuple[int, str]] = [(0, src)]
        while queue:
            cost, node = heapq.heappop(queue)
            if cost > dist.get(node, math.inf):
                continue
            for neighbor, route_type, distance in self.adj.get(node, []):
                if neighbor in avoid:
                    continue
                next_cost = cost + self._frame_edge(neighbor, route_type, distance, speed)
                if neighbor in obstacles:
                    next_cost += obstacle_penalty
                if next_cost >= dist.get(neighbor, math.inf):
                    continue
                dist[neighbor] = next_cost
                prev[neighbor] = node
                heapq.heappush(queue, (next_cost, neighbor))
        return dist, prev

    def _reachable(self, src: str, dst: str, blocked: set[str]) -> bool:
        if src == dst:
            return True
        seen = {src}
        stack = [src]
        while stack:
            node = stack.pop()
            for neighbor, _route_type, _distance in self.adj.get(node, []):
                if neighbor in blocked:
                    continue
                if neighbor == dst:
                    return True
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                stack.append(neighbor)
        return False

    def _restore_path(self, src: str, dst: str, prev: dict[str, str]) -> list[str]:
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        path.reverse()
        return path
