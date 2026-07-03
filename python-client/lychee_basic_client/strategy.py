"""Blockade strategy.

Plan (feature/blockade-strategy):
  1. From the map, find the robust-fastest route to the gate and the choke points
     (cut-vertices) the opponent must pass through.
  2. Race ahead to the choke and park there before the opponent.
  3. The instant the opponent commits toward the choke (just leaves the previous
     station), SET_GUARD so they are forced to reroute and lose that leg.
  4. Keep the choke (and later chokes) blocked -- re-guard as it weathers and
     follow the opponent's detour -- so the opponent can never deliver in 600.
  5. Never risk our own delivery: every frame we compute the latest round we may
     leave and still verify + deliver in time; past that we abandon blocking and
     go deliver. In slack time we pick up nearby tasks.

The window-card / contest layer is reused as-is; only navigation + guarding is new.
"""
from typing import Any, Optional

from . import messages as M
from .contest import active_contest, pick_card
from .graph import Graph

TOTAL_ROUNDS = 600
DELIVER_MARGIN = 25          # safety frames kept before the delivery deadline
VERIFY_FRAMES = 6            # ~frames to VERIFY_GATE at the gate in RUSH
DELIVER_FRAMES = 2           # move-into-terminal + DELIVER
GUARD_KEEP_FRUIT = 6         # never spend guard fruit below this (keep some to deliver)
ICE_BOX = "ICE_BOX"

# main-car states where the engine is running our action; don't interrupt
BUSY_STATES = {"PROCESSING", "VERIFYING", "FORCED_PASSING", "RESTING", "CONTESTING"}


class Strategy:
    def __init__(self, player_id: int) -> None:
        self.player_id = player_id
        self.graph = Graph()
        self.gate_node = "S14"
        self.terminal_node = "S15"
        self.start_node = "S01"
        self.chokes: list[str] = []
        self.processed: set[str] = set()
        self._last_node: Optional[str] = None
        self._my_team: Optional[str] = None
        self._contest_played: set[tuple] = set()
        # opponent tracking (previous frame)
        self._opp_prev_node: Optional[str] = None
        self._opp_prev_edge: Optional[str] = None
        # guards we've placed this visit (nodeId) so we don't spam SET_GUARD
        self._guarded_round: dict[str, int] = {}
        # obstacle nodes we've dispatched a squad to clear (avoid re-dispatch)
        self._squad_sent: set[str] = set()
        self._guard_blocked: set[str] = set()   # enemy guards blocking us

    # ---- setup ----
    def ingest_start(self, start_data: dict[str, Any]) -> None:
        m = start_data.get("map", {})
        edges = start_data.get("edges") or m.get("edges") or []
        self.graph.load_edges(edges)
        roles = m.get("gameplay", {}).get("roles", {})
        self.gate_node = roles.get("gateNodeId", "S14")
        self.start_node = roles.get("startNodeId", "S01")
        self.terminal_node = (roles.get("terminalNodeIds") or ["S15"])[0]
        self.graph.load_process_nodes(m.get("gameplay", {}).get("processNodes", []), self.gate_node)
        # chokes the opponent must cross, nearest the gate first (strongest to hold)
        self.chokes = self.graph.choke_points(self.start_node, self.gate_node)

    # ---- per-frame ----
    def decide(self, inquire_data: dict[str, Any]) -> list[dict[str, Any]]:
        edges = inquire_data.get("edges")
        if edges:
            proc = self.graph.process_rounds
            self.graph.load_edges(edges)
            self.graph.process_rounds = proc

        players = inquire_data.get("players", [])
        me = self._find(players, self.player_id)
        if me is None:
            return []
        opp = self._find_other(players)

        node = me.get("currentNodeId") or ""
        state = me.get("state", "IDLE")
        phase = inquire_data.get("phase", "NORMAL")
        round_no = inquire_data.get("round", 0)
        tasks = inquire_data.get("tasks", [])
        contests = inquire_data.get("contests", [])
        nodes_by_id = {n["nodeId"]: n for n in inquire_data.get("nodes", [])}

        if node != self._last_node:
            self.processed.clear()
            self._last_node = node
        self._account_process(inquire_data.get("events") or [])
        self._my_team = me.get("teamId")
        self._guard_blocked = self._enemy_guards(nodes_by_id)

        if me.get("delivered") or me.get("retired"):
            return []

        # window card rides alongside the main action (separate quota)
        card = self._card(me, contests, round_no)

        # squad pre-clears obstacles ahead (separate quota) so the main car never
        # has to chain FORCED_PASS (two in a row are rejected: FORCED_PASS_REPEAT).
        squad = self._squad_action(node, me, nodes_by_id)

        # once verified we've committed to the delivery run -> always finish it
        # (we only ever VERIFY during our own delivery push).
        if me.get("verified"):
            return card + squad + self._advance_to(self.terminal_node, me, node, state, phase, nodes_by_id)

        # delivery safety: if we can't afford to block any longer, go to the gate.
        if self._must_deliver(node, me, round_no):
            return card + squad + self._advance_to(self.gate_node, me, node, state, phase, nodes_by_id)

        main = self._blockade(me, opp, node, state, phase, round_no, tasks, nodes_by_id)
        main = squad + main
        # remember opponent position for next-frame "just departed" detection
        if opp is not None:
            self._opp_prev_node = opp.get("currentNodeId")
            self._opp_prev_edge = opp.get("routeEdgeId")
        return card + main

    # ---- blockade / phase logic ----
    def _blockade(self, me, opp, node, state, phase, round_no, tasks, nodes_by_id):
        """Goal: WE deliver, the opponent doesn't. Race to the gate dropping a guard
        at every choke we pass (a guard blocks the enemy, never us); the opponent's
        squad can only break so much, so the guard chain outlasts them. Never linger:
        tasks are grabbed ONLY where we're already stopped (a process station or the
        pre-RUSH gate wait) -- we never make a dedicated stop for a task."""
        if state in BUSY_STATES:
            return []

        # standing on a choke the opponent still has to cross -> guard it, then move on
        if node in self.chokes and self._worth_guarding(node, opp, nodes_by_id, me):
            self._guarded_round[node] = round_no
            return [M.set_guard(node, extra_good_fruit=self._guard_fruit(me))]

        # freebie task: only where we're stopped anyway, so it costs us no lead
        if self._stopped_anyway(node, me, phase, nodes_by_id):
            here = self._free_task_here(node, tasks, me)
            if here:
                return here

        # pre-RUSH at the gate: nothing to do but wait for RUSH to verify
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return [M.wait()]

        # otherwise keep advancing toward the gate (through the chokes) -- no lingering
        return self._advance_to(self.gate_node, me, node, state, phase, nodes_by_id)

    def _stopped_anyway(self, node, me, phase, nodes_by_id) -> bool:
        """True where we're forced to stop regardless of tasks: a mandatory process
        station we haven't finished, or the gate before RUSH. Grabbing a task here is
        essentially free; grabbing one anywhere else would cost us the lead."""
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return True
        return self._needs_process(node, nodes_by_id) and node not in self.processed

    def _worth_guarding(self, choke, opp, nodes_by_id, me) -> bool:
        """Guard this choke if the opponent still has to cross it, we're not already
        holding it, and we can spare the fruit."""
        if opp is None:
            return False
        g = nodes_by_id.get(choke, {}).get("guard") or {}
        if g.get("active") and g.get("ownerTeamId") == self._my_team and g.get("defense", 0) > 0:
            return False  # already held
        if me.get("goodFruit", 0) <= GUARD_KEEP_FRUIT:
            return False  # keep enough fruit to deliver
        opp_node = opp.get("currentNodeId")
        if not opp_node:
            return True
        # opponent must still pass this cut-vertex to reach the gate
        return self.graph.path_frames(opp_node, self.gate_node, avoid={choke}) == float("inf")

    def _guard_fruit(self, me) -> int:
        spare = me.get("goodFruit", 0) - GUARD_KEEP_FRUIT
        return max(0, min(2, spare))

    def _squad_action(self, node, me, nodes_by_id) -> list:
        """Dispatch a squad to clear the next unavoidable obstacle on our route to
        the gate, so we MOVE through it instead of chaining FORCED_PASS."""
        if me.get("squadAvailable", 0) < 2:
            return []
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        path = self.graph.fastest_path(node, self.gate_node, obstacles=obstacles) or []
        for nid in path[1:]:
            if nid in obstacles and nid not in self._squad_sent:
                self._squad_sent.add(nid)
                return [M.squad_clear(nid)]
        return []

    # ---- navigation ----
    def _advance_to(self, dest, me, node, state, phase, nodes_by_id):
        """One step toward dest: continue an edge, process/verify, force past an
        obstacle, else MOVE. Handles the WAITING-on-edge continuation."""
        if state in BUSY_STATES:
            return []
        if node == dest:
            return self._arrive(dest, me, phase, nodes_by_id)
        # travelling: keep going to the committed next node
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return [M.move(me["nextNodeId"])]
        # gate en route -> must VERIFY before passing (only in RUSH)
        if node == self.gate_node and not me.get("verified"):
            return self._arrive(self.gate_node, me, phase, nodes_by_id)
        # mandatory fixed process at the node we're standing on
        if self._needs_process(node, nodes_by_id) and node not in self.processed:
            return [M.process(node)]
        # route around obstacle nodes (they carry a time tax); only cross one when
        # it's unavoidable (e.g. an obstacle sitting on a choke).
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        nxt = self.graph.fastest_hop(node, dest, avoid=self._guard_blocked, obstacles=obstacles) \
            or self.graph.fastest_hop(node, dest, obstacles=obstacles)
        if not nxt:
            return []
        if nodes_by_id.get(nxt, {}).get("hasObstacle") or nxt in self._guard_blocked:
            # FORCED_PASS a pure obstacle opens no window (safe); CLEAR dead-locked
            # on this server. Obstacle-avoiding routing keeps us off chained obstacles.
            return [M.forced_pass(nxt)]
        return [M.move(nxt)]

    def _arrive(self, dest, me, phase, nodes_by_id):
        """At the gate: verify (RUSH) then move on. At the terminal: ice + deliver."""
        if dest == self.terminal_node or me.get("currentNodeId") == self.terminal_node:
            if not me.get("verified"):
                return [M.move(self.gate_node)]  # can't deliver unverified; go back
            if (me.get("resources", {}) or {}).get(ICE_BOX, 0) > 0 and me.get("freshness", 100) < 100:
                return [M.use_resource(ICE_BOX)]
            return [M.deliver()]
        if dest == self.gate_node:
            if me.get("verified"):
                return [M.move(self.terminal_node)]
            if phase == "RUSH":
                return [M.verify_gate()]
            return [M.wait()]  # can't verify before RUSH
        return []

    # ---- opportunistic (free) task pickup ----
    def _free_task_here(self, node, tasks, me):
        """Claim a task sitting on the node we're already stopped at -- no detour,
        no dedicated stop (called only from _stopped_anyway)."""
        for t in tasks:
            if t.get("nodeId") == node and t.get("active") and not t.get("completed") \
               and not t.get("failed") and not t.get("ownerPlayerId"):
                return [M.claim_task(t["taskId"])]
        return None

    # ---- delivery-time safety ----
    def _must_deliver(self, node, me, round_no) -> bool:
        need = self._frames_to_deliver(node, me)
        return round_no + need + DELIVER_MARGIN >= TOTAL_ROUNDS

    def _frames_to_deliver(self, node, me) -> float:
        to_gate = 0 if me.get("verified") else self.graph.path_frames(node, self.gate_node)
        verify = 0 if me.get("verified") else VERIFY_FRAMES
        start = self.gate_node if not me.get("verified") else node
        to_term = self.graph.path_frames(start, self.terminal_node)
        return to_gate + verify + to_term + DELIVER_FRAMES

    # ---- helpers ----
    def _card(self, me, contests, round_no):
        c = active_contest(self.player_id, contests, round_no)
        if c is None:
            return []
        tap = (c.get("contestId"), c.get("roundIndex"))
        if tap in self._contest_played:
            return []
        self._contest_played.add(tap)
        return [M.window_card(c["contestId"], pick_card(me, c))]

    def _needs_process(self, node, nodes_by_id) -> bool:
        if node in (self.gate_node, self.terminal_node):
            return False
        return nodes_by_id.get(node, {}).get("processRound", 0) > 0 or node in self.graph.process_rounds

    def _account_process(self, events) -> None:
        for e in events:
            if e.get("type") == "PROCESS_COMPLETE":
                pl = e.get("payload") or {}
                if pl.get("playerId") == self.player_id and pl.get("targetNodeId"):
                    self.processed.add(pl["targetNodeId"])

    def _enemy_guards(self, nodes_by_id) -> set:
        return {
            nid for nid, n in nodes_by_id.items()
            if (g := n.get("guard")) and g.get("active") and g.get("defense", 0) > 0
            and g.get("ownerTeamId") not in (None, self._my_team)
        }

    @staticmethod
    def _find(players, pid):
        for p in players:
            if p.get("playerId") == pid:
                return p
        return None

    def _find_other(self, players):
        for p in players:
            if p.get("playerId") != self.player_id:
                return p
        return None
