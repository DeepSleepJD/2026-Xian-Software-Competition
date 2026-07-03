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
import math
from typing import Any, Optional

from . import messages as M
from .contest import active_contest, pick_card
from .graph import Graph

TOTAL_ROUNDS = 600
DELIVER_MARGIN = 25          # safety frames kept before the delivery deadline
VERIFY_FRAMES = 6            # ~frames to VERIFY_GATE at the gate in RUSH
DELIVER_FRAMES = 2           # move-into-terminal + DELIVER
GUARD_KEEP_FRUIT = 6         # never spend guard fruit below this (keep some to deliver)
GUARD_SETUP_FRAMES = 5       # SET_GUARD read-bar (4) + activates next frame
FREEZE_SAFETY = 2            # extra edge-frame margin so the guard is up before arrival
ICE_BOX = "ICE_BOX"
HORSES = ("FAST_HORSE", "SHORT_HORSE")   # move-buff resources (fast first)
SQUAD_LOOKAHEAD = 70         # only pre-clear obstacles within this many frames ahead
XIAN_GONG_FLOOR = 6          # keep at least this many good fruit (guards + delivery)

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
        self._first_guard_node: Optional[str] = None   # decoy guard (not reinforced)
        # opponent tracking (previous frame)
        self._opp_prev_node: Optional[str] = None
        self._opp_prev_edge: Optional[str] = None
        # guards we've placed this visit (nodeId) so we don't spam SET_GUARD
        self._guarded_round: dict[str, int] = {}
        # obstacle nodes we've dispatched a squad to clear (avoid re-dispatch)
        self._squad_sent: set[str] = set()
        self._guard_blocked: set[str] = set()   # enemy guards blocking us
        self.route_avoid: set[str] = set()       # nodes to route around (variants/testing)

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
        squad = self._squad_action(node, me, opp, nodes_by_id)

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
        """Goal: WE deliver, the opponent doesn't. Camp the first choke the opponent
        must cross and, the instant they commit ONTO the edge into it (state MOVING,
        with enough edge left for the guard to activate), SET_GUARD -- they arrive to
        a blocked node and FREEZE mid-edge, where they can neither FORCED_PASS nor
        BREAK_GUARD (both need a current node) nor backtrack. Their only out is a
        squad-weaken, which we out-heal with SQUAD_REINFORCE (see _squad_action).
        Then we run to deliver. Never linger for tasks (only grab freebies where we
        already stop). Our delivery deadline (_must_deliver upstream) always wins."""
        if state in BUSY_STATES:
            return []

        # MID-EDGE: never attempt a node action -- SET_GUARD/PROCESS while travelling
        # are rejected MOVING_ACTION_FORBIDDEN, which once stalled us dead on the edge
        # spamming SET_GUARD. currentNodeId still reads the edge's start node, so gate
        # this on routeEdgeId, not on `node`. Just push to the far end.
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return [M.move(me["nextNodeId"])]

        # GUARD-AS-WE-PASS: drop a guard on every choke we stand on that the opponent
        # must still cross, then keep moving. We never camp waiting for the perfect
        # commit moment (that once stalled us past our own delivery deadline); the
        # freeze still happens -- the opponent freezes mid-edge whenever they arrive
        # while the guard is up. First guard = decoy (see _squad_action).
        if node in self.chokes and not self._we_hold(node, nodes_by_id) \
           and self._opp_must_cross(node, opp) and me.get("goodFruit", 0) > GUARD_KEEP_FRUIT:
            if self._first_guard_node is None:
                self._first_guard_node = node
            self._guarded_round[node] = round_no
            return [M.set_guard(node, extra_good_fruit=self._guard_fruit(me))]

        if self._stopped_anyway(node, me, phase, nodes_by_id):
            here = self._free_task_here(node, tasks, me)
            if here:
                return here
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return [M.wait()]
        return self._advance_to(self.gate_node, me, node, state, phase, nodes_by_id)

    def _opp_must_cross(self, node, opp) -> bool:
        """True if this cut-vertex is still on the opponent's only way to the gate."""
        if opp is None:
            return False
        opp_node = opp.get("currentNodeId")
        if not opp_node:
            return True
        return self.graph.path_frames(opp_node, self.gate_node, avoid={node}) == float("inf")

    def _we_hold(self, node, nodes_by_id) -> bool:
        g = nodes_by_id.get(node, {}).get("guard") or {}
        return bool(g.get("active") and g.get("ownerTeamId") == self._my_team and g.get("defense", 0) > 0)

    def _freeze_window_open(self, opp, N) -> bool:
        """The opponent has committed onto the edge into N and there is still enough
        of that edge left for our guard to finish setting up before they arrive."""
        if opp is None or opp.get("state") != "MOVING" or opp.get("nextNodeId") != N:
            return False
        return self._opp_remaining_edge_frames(opp) >= GUARD_SETUP_FRAMES + FREEZE_SAFETY

    def _opp_remaining_edge_frames(self, opp) -> int:
        ef = self.graph.edge_frames(opp.get("currentNodeId"), opp.get("nextNodeId"))
        if not ef:
            return 0
        permille = opp.get("edgeProgressPermille", 0) or 0
        return math.ceil((1 - permille / 1000.0) * ef)

    def _stopped_anyway(self, node, me, phase, nodes_by_id) -> bool:
        """True where we're forced to stop regardless of tasks: a mandatory process
        station we haven't finished, or the gate before RUSH. A task grabbed here is
        free; grabbing one anywhere else would cost us the lead."""
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return True
        return self._needs_process(node, nodes_by_id) and node not in self.processed

    def _guard_fruit(self, me) -> int:
        spare = me.get("goodFruit", 0) - GUARD_KEEP_FRUIT
        return max(0, min(2, spare))

    def _horse_action(self, me, node, nodes_by_id):
        """Mount a held horse (speed buff) before moving; else grab one sitting here.
        Horses accelerate the race to the choke -- and taking the one before the choke
        also denies it to the opponent."""
        res = me.get("resources") or {}
        buffed = any((b.get("type") or "").endswith("HORSE") or b.get("type") == "MOVE_BUFF"
                     for b in (me.get("buffs") or []))
        held = [h for h in HORSES if res.get(h, 0) > 0]
        if not buffed and held:
            return [M.use_resource(held[0])]           # mount it now, then move
        if not buffed and not held:
            stock = nodes_by_id.get(node, {}).get("resourceStock") or {}
            for h in HORSES:                            # fast horse first
                if stock.get(h, 0) > 0:
                    return [M.claim_resource(node, h)]
        return None

    def _squad_action(self, node, me, opp, nodes_by_id) -> list:
        """Squad is a separate quota (rides alongside the main action) and a scarce
        budget. Priorities:
        1) REINFORCE a weakened guard -- but NOT the first (decoy) guard: let it soak
           the opponent's squad and fall; heal the LATER guards, which the (now
           squad-poor) opponent can no longer break. Any distance, no backtrack.
        2) pre-CLEAR the next obstacle -- but ONLY if we're not already ahead (if we
           lead, keep the squad for reinforcing; clearing just speeds a race we win)."""
        if me.get("squadAvailable", 0) < 2:
            return []
        # 1) heal a knocked-down guard (a weaken hit = >=2 below cap), except the decoy
        for nid, n in nodes_by_id.items():
            if nid == self._first_guard_node:
                continue  # decoy: don't reinforce, let it draw their squad
            g = n.get("guard") or {}
            if g.get("active") and g.get("ownerTeamId") == self._my_team:
                cap = g.get("maxDefense", g.get("initialDefense", 0))
                if 0 < g.get("defense", 0) <= cap - 2:
                    return [M.squad_reinforce(nid)]
        # 2) clear obstacles on our path -- REQUIRED now that we never FORCED_PASS: the
        # main car MOVEs through only once a squad has cleared the obstacle. Dispatch to
        # the nearest uncleared obstacle within reach (clears in parallel as we race).
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        path = self.graph.fastest_path(node, self.gate_node, obstacles=obstacles) or []
        for nid in path[1:]:
            if nid in obstacles and nid not in self._squad_sent:
                self._squad_sent.add(nid)   # nearest uncleared obstacle on our path
                return [M.squad_clear(nid)]
        return []

    def _ahead_of(self, node, opp) -> bool:
        """True if we're closer to the gate (in frames) than the opponent."""
        if opp is None:
            return True
        opp_node = opp.get("currentNodeId")
        if not opp_node:
            return True
        return self.graph.path_frames(node, self.gate_node) < self.graph.path_frames(opp_node, self.gate_node)

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
        # grab / mount a horse to win the race to the choke (and deny it to the
        # opponent). A move-buff means every following edge is faster.
        horse = self._horse_action(me, node, nodes_by_id)
        if horse:
            return horse
        # route around obstacle nodes (they carry a time tax); only cross one when
        # it's unavoidable (e.g. an obstacle sitting on a choke).
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        avoid = self._guard_blocked | self.route_avoid
        nxt = self.graph.fastest_hop(node, dest, avoid=avoid, obstacles=obstacles) \
            or self.graph.fastest_hop(node, dest, obstacles=obstacles)
        if not nxt:
            return []
        if nodes_by_id.get(nxt, {}).get("hasObstacle") or nxt in self._guard_blocked:
            # NO FORCED_PASS anymore (it chained into FORCED_PASS_REPEAT and stalled us).
            # A squad clears the obstacle in parallel (_squad_action); we just wait a
            # frame for it, then MOVE straight through.
            return [M.wait()]
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
        card = pick_card(me, c)
        # HEDGE / deny-everything: play XIAN_GONG on EVERY tap of EVERY contest while
        # we can afford it -- the strongest single card (beats YAN_DIE + BING_ZHENG,
        # ties XIAN_GONG, only loses to QIANG_XING which needs a horse). This never
        # loses an early contest, so the opponent never wins the processing-priority
        # (speed) lead. Keep a good-fruit floor so we don't starve guards / delivery.
        if me.get("freshness", 0) >= 80 and me.get("goodFruit", 0) > XIAN_GONG_FLOOR:
            card = "XIAN_GONG"
        return [M.window_card(c["contestId"], card)]

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
