"""Map graph and shortest-path helpers for route planning."""
import heapq
import math
from typing import Any, Optional

# Per-route-type cost coefficient (moves needed per 1 point of route distance)
# and per-frame freshness loss, from the task book (2.3.2).
ROUTE_COST_COEF = {
    "ROAD": 1380,
    "WATER": 1250,
    "MOUNTAIN": 1780,
    "BRANCH": 1550,
}
# per-frame freshness loss by route type (task book 3.2.2)
ROUTE_FRESHNESS_LOSS = {
    "ROAD": 0.055,
    "WATER": 0.045,
    "MOUNTAIN": 0.07,
    "BRANCH": 0.065,
}
IDLE_FRESHNESS_LOSS = 0.05  # stopping / processing / waiting
BASE_MOVE_PER_FRAME = 1000


def move_frames(distance: int, route_type: str) -> int:
    """Frames to traverse an edge with no acceleration / no weather.

    Task book 2.3.2: required-moves = ceil(distance * coef); per-frame move = 1000
    (no acceleration / clear weather), so frames = ceil(required-moves / 1000).
    """
    coef = ROUTE_COST_COEF.get(route_type, 1500)
    required_moves = math.ceil(distance * coef)
    return max(1, math.ceil(required_moves / BASE_MOVE_PER_FRAME))


class Graph:
    def __init__(self) -> None:
        # node -> list of (neighbor, route_type, distance)
        self.adj: dict[str, list[tuple[str, str, int]]] = {}
        self.process_rounds: dict[str, int] = {}  # mandatory process node -> frames

    def load_edges(self, edges: list[dict[str, Any]]) -> None:
        self.adj = {}
        for e in edges:
            f = e.get("fromNodeId") or e.get("fromNode")
            t = e.get("toNodeId") or e.get("toNode")
            rt = e.get("routeType", "ROAD")
            d = int(e.get("distance", 1))
            self.adj.setdefault(f, []).append((t, rt, d))
            if e.get("bidirectional"):
                self.adj.setdefault(t, []).append((f, rt, d))

    def load_process_nodes(self, process_nodes: list[dict[str, Any]], gate_node: str) -> None:
        self.process_rounds = {}
        for p in process_nodes:
            nid = p["nodeId"]
            if nid == gate_node:
                continue  # gate uses VERIFY_GATE, handled separately
            self.process_rounds[nid] = int(p.get("processRound", 0))

    def _edge_cost(self, dst: str, route_type: str, distance: int) -> float:
        """Planning cost = freshness lost traversing the edge plus the freshness
        lost waiting out any mandatory fixed-process on arrival.

        Freshness (not raw frames) is what scores while we complete no tasks:
        the time score is folded to 0 by the task factor, whereas both the
        freshness (180) and good-fruit (180) score components track freshness.
        """
        frames = move_frames(distance, route_type)
        loss = frames * ROUTE_FRESHNESS_LOSS.get(route_type, 0.06)
        loss += self.process_rounds.get(dst, 0) * IDLE_FRESHNESS_LOSS
        return loss

    def _dijkstra(
        self, src: str, avoid: Optional[set] = None
    ) -> tuple[dict[str, float], dict[str, str]]:
        """Min freshness-cost from src to every node (incl. mandatory process waits).
        Nodes in `avoid` (other than src) are treated as impassable."""
        avoid = avoid or set()
        dist: dict[str, float] = {src: 0.0}
        prev: dict[str, str] = {}
        pq: list[tuple[float, str]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, math.inf):
                continue
            for v, rt, dd in self.adj.get(u, []):
                if v in avoid:
                    continue
                nd = d + self._edge_cost(v, rt, dd)
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    def shortest_path(
        self, src: str, dst: str, avoid: Optional[set] = None
    ) -> Optional[list[str]]:
        """Least-freshness-loss path as a node list, or None if unreachable."""
        if src == dst:
            return [src]
        dist, prev = self._dijkstra(src, avoid)
        if dst not in dist:
            return None
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        path.reverse()
        return path

    def path_cost(self, src: str, dst: str) -> float:
        """Least freshness cost from src to dst (math.inf if unreachable)."""
        if src == dst:
            return 0.0
        dist, _ = self._dijkstra(src)
        return dist.get(dst, math.inf)

    def next_hop(self, src: str, dst: str, avoid: Optional[set] = None) -> Optional[str]:
        path = self.shortest_path(src, dst, avoid)
        if path and len(path) >= 2:
            return path[1]
        return None
