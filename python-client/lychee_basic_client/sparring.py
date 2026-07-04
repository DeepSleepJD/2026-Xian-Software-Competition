"""Sparring opponents for LOCAL adversarial testing (--strategy aggressive).

AggressiveStrategy is a guard-BREAKING delivery rusher: it takes a divergent route
off the start (so it doesn't collide with us at the first process station, which in
self-play would dead-lock on a mutual DOCK draw), pre-clears its own obstacles, and
SQUAD_WEAKENs any enemy guard blocking its way -- exactly the opponent that broke
our two static guards and delivered. If our freeze + SQUAD_REINFORCE holds it out,
the blockade really works.
"""
from . import messages as M
from .strategy import Strategy


class AggressiveStrategy(Strategy):
    def _ensure_diverged(self, nodes_by_id):
        # avoid the OBSTACLE-AWARE first hop (the road hop our main client takes) so
        # we take the other route and don't mirror-collide at the first process node.
        # Graph edges arrive via inquire, so do this lazily once the graph is loaded.
        if not self.route_avoid and self.graph.adj:
            obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
            first = self.graph.fastest_hop(self.start_node, self.gate_node, obstacles=obstacles)
            if first:
                self.route_avoid = {first}

    def _main_action(self, me, opp, node, state, phase, round_no, tasks, nodes_by_id):
        if state in ("MOVING", "PROCESSING", "CONTESTING"):
            return []
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return [M.move(me["nextNodeId"])]
        self._ensure_diverged(nodes_by_id)
        dest = self.terminal_node if me.get("verified") else self.gate_node
        return self._advance_to(dest, me, node, state, phase, nodes_by_id)

    def _squad_action(self, node, me, opp, nodes_by_id):
        """Break through: weaken the enemy guard on our route; else clear our own
        obstacles so we can keep moving."""
        if me.get("squadAvailable", 0) < 2:
            return []
        self._ensure_diverged(nodes_by_id)
        path = self.graph.fastest_path(node, self.gate_node, avoid=self.route_avoid) or []
        # 1) smash the enemy guard standing between us and the gate
        for nid in path:
            g = nodes_by_id.get(nid, {}).get("guard") or {}
            if g.get("active") and g.get("ownerTeamId") not in (None, self._my_team) \
               and g.get("defense", 0) > 0:
                return [M.squad_weaken(nid)]
        # 2) otherwise pre-clear our own obstacles
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        for nid in path[1:]:
            if nid in obstacles and nid not in self._squad_sent:
                self._squad_sent.add(nid)
                return [M.squad_clear(nid)]
        return []
