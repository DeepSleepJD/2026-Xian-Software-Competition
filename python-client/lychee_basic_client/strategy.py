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
import heapq
from dataclasses import dataclass
from typing import Any, Optional

from . import messages as M
from .contest import active_contest, pick_card
from .graph import BASE_MOVE_PER_FRAME, Graph, ROUTE_COST_COEF

TOTAL_ROUNDS = 600
DELIVER_MARGIN = 60          # safety frames before the delivery deadline (covers the
                             # obstacle clear-waits our frame estimate doesn't model, so
                             # camping on a choke never drags us past our own delivery)
VERIFY_FRAMES = 6            # ~frames to VERIFY_GATE at the gate in RUSH
DELIVER_FRAMES = 2           # move-into-terminal + DELIVER
GUARD_KEEP_FRUIT = 6         # never spend guard fruit below this (keep some to deliver)
GUARD_SETUP_FRAMES = 5       # SET_GUARD read-bar (4) + activates next frame
TASK_TIME = 8                # rough frames a task claim+complete costs (spare-time gate)
RACE_SAFETY = 30             # only task pre-choke if we lead the race to it by > this
FREEZE_SAFETY = 2            # extra edge-frame margin so the guard is up before arrival
ICE_BOX = "ICE_BOX"
HORSES = ("FAST_HORSE", "SHORT_HORSE")   # move-buff resources (fast first)
HORSE_MOVE_PER_FRAME = {"FAST_HORSE": 1200, "SHORT_HORSE": 1150}
HORSE_DURATION = {"FAST_HORSE": 20, "SHORT_HORSE": 14}
RESOURCE_CLAIM_FRAMES = 2
START_OBSTACLE_CLEAR_FRAMES = 6
WEATHER_MOVE_MULTIPLIER = {
    ("HEAVY_RAIN", "WATER"): 1350,
    ("MOUNTAIN_FOG", "MOUNTAIN"): 1100,
}
WEATHER_PROCESS_EXTRA = {
    ("HEAVY_RAIN", "BOARD"): 4,
    ("HEAVY_RAIN", "WATER_TRANSFER"): 4,
}
OBSTACLE_PENALTY = 0         # routing cost of crossing an obstacle node: obstacles are
                             # squad-cleared in parallel now (near-free), so don't avoid
                             # them -- take the true shortest route (may use shortcuts)
XIAN_GONG_FLOOR = 6          # keep at least this many good fruit (guards + delivery)

# main-car states where the engine is running our action; don't interrupt
BUSY_STATES = {"PROCESSING", "VERIFYING", "FORCED_PASSING", "RESTING", "CONTESTING"}


@dataclass(frozen=True)
class RoutePlan:
    frames: float
    path: list[str]
    first_claim: Optional[str] = None

    @property
    def next_hop(self) -> Optional[str]:
        if len(self.path) >= 2:
            return self.path[1]
        return None


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
        self._resource_claim_rounds: dict[tuple[str, str], int] = {}
        self._left_start = False
        self._opp_left_start = False

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
        self._resource_claim_rounds = {}
        for r in start_data.get("resources") or m.get("resources") or []:
            node_id = r.get("nodeId")
            resource_type = r.get("resourceType")
            if node_id and resource_type:
                self._resource_claim_rounds[(node_id, resource_type)] = int(
                    r.get("claimRound", RESOURCE_CLAIM_FRAMES)
                )
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
        weather = inquire_data.get("weather", {})
        nodes_by_id = {n["nodeId"]: n for n in inquire_data.get("nodes", [])}

        if node != self._last_node:
            self.processed.clear()
            self._last_node = node
        self._account_process(inquire_data.get("events") or [])
        self._my_team = me.get("teamId")
        self._guard_blocked = self._enemy_guards(nodes_by_id)
        self._update_start_flags(me, opp)

        if me.get("delivered") or me.get("retired"):
            return []

        # window card rides alongside the main action (separate quota)
        card = self._card(me, contests, round_no)

        # squad pre-clears obstacles ahead (separate quota) so the main car never
        # has to chain FORCED_PASS (two in a row are rejected: FORCED_PASS_REPEAT).
        squad = self._squad_action(node, me, opp, nodes_by_id, round_no, weather)

        # once verified we've committed to the delivery run -> always finish it
        # (we only ever VERIFY during our own delivery push).
        if me.get("verified"):
            main = self._advance_to(
                self.terminal_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )
            return self._ordered_actions(main, squad, card)

        # delivery safety: if we can't afford to block any longer, go to the gate.
        if self._must_deliver(node, me, round_no, nodes_by_id, weather):
            main = self._advance_to(
                self.gate_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )
            return self._ordered_actions(main, squad, card)

        main = self._blockade(
            me, opp, node, state, phase, round_no, tasks, nodes_by_id, weather
        )
        # remember opponent position for next-frame "just departed" detection
        if opp is not None:
            self._opp_prev_node = opp.get("currentNodeId")
            self._opp_prev_edge = opp.get("routeEdgeId")
        return self._ordered_actions(main, squad, card)

    @staticmethod
    def _ordered_actions(main, squad=None, card=None):
        """Server expects the main-car action first; side-channel actions follow."""
        squad = squad or []
        card = card or []
        if not main:
            return ([M.wait()] if squad or card else []) + squad + card
        return main + squad + card

    # ---- blockade / phase logic ----
    def _blockade(self, me, opp, node, state, phase, round_no, tasks, nodes_by_id, weather=None):
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
            return self._advance_to(
                self.gate_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )

        # FREEZE: camp on a choke the opponent must still cross and SET_GUARD only the
        # instant they've COMMITTED onto the edge into it (MOVING, nextNode==choke) AND
        # enough edge is left for the guard to finish before they arrive. They then
        # arrive to a blocked node and freeze mid-edge -- no backtrack, no FORCED_PASS,
        # no BREAK_GUARD. If they haven't committed yet we hold the choke and wait; our
        # delivery deadline (_must_deliver upstream) drags us off before we're too late.
        if node in self.chokes and not self._we_hold(node, nodes_by_id) \
           and self._opp_must_cross(node, opp) and not self._opp_walled_off(opp, nodes_by_id):
            if self._freeze_window_open(opp, node, round_no, weather) and me.get("goodFruit", 0) > GUARD_KEEP_FRUIT:
                if self._first_guard_node is None:
                    self._first_guard_node = node
                self._guarded_round[node] = round_no
                return [M.set_guard(node, extra_good_fruit=self._guard_fruit(me))]
            # opponent not committed yet -> camp; use the wait for a task ONLY if we
            # have spare time (won't miss the freeze / delivery -- see _spare_for_task)
            t = self._free_task_here(node, tasks, me)
            if t and self._spare_for_task(node, me, opp, round_no, nodes_by_id, weather):
                return t
            return [M.wait()]

        # a task anywhere on the way -- but only with spare time: doing it must NOT let
        # the opponent beat us to an unsecured choke, nor risk our own delivery.
        here = self._free_task_here(node, tasks, me)
        if here and self._spare_for_task(node, me, opp, round_no, nodes_by_id, weather):
            return here
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return [M.wait()]
        return self._advance_to(
            self.gate_node, me, node, state, phase, nodes_by_id, tasks,
            round_no, weather
        )

    def _spare_for_task(self, node, me, opp, round_no, nodes_by_id, weather=None) -> bool:
        """Do a task only with genuine spare time: it must not push us past our
        delivery deadline, and (before the blockade is secured) must not let the
        opponent reach the nearest choke we still need before we do."""
        # (a) delivery must survive the task's time cost
        if round_no + TASK_TIME + self._frames_to_deliver(node, me, nodes_by_id, round_no, weather) + DELIVER_MARGIN >= TOTAL_ROUNDS:
            return False
        # (b) the choke race: the nearest choke ahead that the opponent must still
        # cross and we don't yet hold -- a task must not lose us that race
        if opp is None:
            return True
        opp_node = opp.get("currentNodeId")
        for c in reversed(self.chokes):  # start-side first
            if self._we_hold(c, nodes_by_id) or not self._opp_must_cross(c, opp):
                continue
            # only chokes we're at or still before (haven't passed)
            if node != c and self.graph.path_frames(node, self.gate_node, avoid={c}) != float("inf"):
                continue
            our_eta = self._eta_to_node(
                me, c, nodes_by_id, round_no=round_no, weather=weather
            ) + GUARD_SETUP_FRAMES
            opp_eta = self._eta_to_node(
                opp, c, nodes_by_id, round_no=round_no, weather=weather
            ) if opp_node else float("inf")
            # only spare if we're COMFORTABLY ahead to the choke -- a mere tie is not
            # spare (a neck-and-neck opponent leaves no time for tasks before we camp)
            return opp_eta - our_eta > TASK_TIME + RACE_SAFETY
        return True  # no unsecured choke ahead -> race already won, task is safe

    def _opp_walled_off(self, opp, nodes_by_id) -> bool:
        """True if the opponent already can't reach the gate without crossing one of
        OUR active guards -- the blockade is secured, so stop camping downstream
        chokes they can't reach and go deliver."""
        if opp is None:
            return False
        opp_node = opp.get("currentNodeId")
        if not opp_node:
            return False
        my_guards = {
            nid for nid, n in nodes_by_id.items()
            if (g := n.get("guard")) and g.get("active")
            and g.get("ownerTeamId") == self._my_team and g.get("defense", 0) > 0
        }
        if not my_guards:
            return False
        return self.graph.path_frames(opp_node, self.gate_node, avoid=my_guards) == float("inf")

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

    def _freeze_window_open(self, opp, N, round_no=0, weather=None) -> bool:
        """The opponent has committed onto the edge into N and there is still enough
        of that edge left for our guard to finish setting up before they arrive."""
        if opp is None or opp.get("state") != "MOVING" or opp.get("nextNodeId") != N:
            return False
        return self._opp_remaining_edge_frames(opp, round_no, weather) >= GUARD_SETUP_FRAMES + FREEZE_SAFETY

    def _opp_remaining_edge_frames(self, opp, round_no=0, weather=None) -> int:
        edge = self._edge_info(opp.get("currentNodeId"), opp.get("nextNodeId"))
        if edge is None:
            return 0
        route_type, distance = edge
        remaining = self._remaining_edge_required(opp, route_type, distance)
        if remaining <= 0:
            return 0
        horse, horse_left, held = self._initial_horse_state(opp)
        frames, _horse, _left, _held = self._travel_required_frames(
            remaining, route_type, horse, horse_left, held, round_no, weather, round_no
        )
        return frames

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

    def _held_horse(self, actor) -> Optional[str]:
        res = actor.get("resources") or {}
        for h in HORSES:
            if res.get(h, 0) > 0:
                return h
        return None

    def _squad_action(self, node, me, opp, nodes_by_id, round_no=0, weather=None) -> list:
        """Squad CLEARS obstacles on our path so the main car MOVEs through (we never
        FORCED_PASS). Dispatch to the nearest uncleared obstacle ahead (clears in
        parallel as we race).

        NOTE: guard reinforcement (SQUAD_REINFORCE) is intentionally REMOVED for now
        -- to be re-added separately. The blockade relies on freeze timing (fresh
        max-defense guard set at the last moment) so a squad-poor opponent can't
        weaken through it, not on healing."""
        if me.get("squadAvailable", 0) < 2:
            return []
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        plan = self._route_plan(
            node, self.gate_node, me, nodes_by_id, obstacles=obstacles,
            round_no=round_no, weather=weather
        )
        path = plan.path
        for idx, nid in enumerate(path[1:], start=1):
            if idx == 1 and self._is_opening_first_hop_obstacle(node, nid, nodes_by_id, me):
                continue
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
    def _advance_to(
        self, dest, me, node, state, phase, nodes_by_id, tasks=None,
        round_no=0, weather=None
    ):
        """One step toward dest: continue an edge, process/verify, force past an
        obstacle, else MOVE. Handles the WAITING-on-edge continuation."""
        if state in BUSY_STATES:
            return []
        if node == dest:
            return self._arrive(dest, me, phase, nodes_by_id)
        # travelling: keep going to the committed next node
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            held = self._held_horse(me)
            if held and not self._active_horse(me):
                return [M.use_resource(held)]
            return [M.move(me["nextNodeId"])]
        # gate en route -> must VERIFY before passing (only in RUSH)
        if node == self.gate_node and not me.get("verified"):
            return self._arrive(self.gate_node, me, phase, nodes_by_id)
        # mandatory fixed process at the node we're standing on
        if self._needs_process(node, nodes_by_id) and node not in self.processed:
            return [M.process(node)]
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        avoid = self._guard_blocked | self.route_avoid
        plan = self._route_plan(
            node, dest, me, nodes_by_id, avoid=avoid, obstacles=obstacles,
            round_no=round_no, weather=weather
        )
        if plan.frames == float("inf"):
            plan = self._route_plan(
                node, dest, me, nodes_by_id, obstacles=obstacles,
                round_no=round_no, weather=weather
            )
        if plan.first_claim:
            return [M.claim_resource(node, plan.first_claim)]
        nxt = plan.next_hop
        if not nxt:
            return []
        if nxt in self._guard_blocked:
            return [M.wait()]
        if nodes_by_id.get(nxt, {}).get("hasObstacle"):
            if self._is_opening_first_hop_obstacle(node, nxt, nodes_by_id, me):
                return self._opening_obstacle_action(node, nxt, tasks or [])
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
    def _must_deliver(self, node, me, round_no, nodes_by_id, weather=None) -> bool:
        need = self._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        return round_no + need + DELIVER_MARGIN >= TOTAL_ROUNDS

    def _frames_to_deliver(self, node, me, nodes_by_id, round_no=0, weather=None) -> float:
        to_gate = 0 if me.get("verified") else self._route_frames(
            node, self.gate_node, me, nodes_by_id, round_no=round_no,
            weather=weather, weather_base_round=round_no
        )
        if to_gate == float("inf"):
            return float("inf")
        verify = 0 if me.get("verified") else VERIFY_FRAMES
        start = self.gate_node if not me.get("verified") else node
        to_term = self._route_frames(
            start, self.terminal_node, me, nodes_by_id,
            round_no=round_no + to_gate + verify, weather=weather,
            weather_base_round=round_no
        )
        return to_gate + verify + to_term + DELIVER_FRAMES

    # ---- context-aware routing ----
    def _route_frames(
        self, src, dst, actor, nodes_by_id, avoid=None, obstacles=None,
        round_no=0, weather=None, weather_base_round=None,
        process_destination=True
    ) -> float:
        return self._route_plan(
            src, dst, actor, nodes_by_id, avoid, obstacles, round_no, weather,
            weather_base_round, process_destination
        ).frames

    def _route_plan(
        self, src, dst, actor, nodes_by_id, avoid=None, obstacles=None,
        round_no=0, weather=None, weather_base_round=None,
        process_destination=True
    ) -> RoutePlan:
        """Fewest-frame route with actor-local horse state and our opening obstacle rule.

        Obstacles after the first hop are treated as zero-cost for our route model,
        because the squad path pre-clear runs in parallel. The one special case is the
        match opening at S01: if the very first hop is obstructed, the main car spends
        the 6-frame clear/T04 window instead of dispatching squad.
        """
        if not src:
            return RoutePlan(float("inf"), [])
        if src == dst:
            return RoutePlan(0, [src])

        if weather_base_round is None:
            weather_base_round = round_no
        avoid = avoid or set()
        obstacles = obstacles or {
            nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")
        }
        active, active_left, held = self._initial_horse_state(actor)
        start_state = (src, active, active_left, held, tuple(), False)
        dist: dict[tuple, int] = {start_state: 0}
        prev: dict[tuple, tuple] = {}
        pq: list[tuple[int, int, tuple]] = [(0, 0, start_state)]
        seq = 1
        best: Optional[tuple] = None

        while pq:
            d, _seq, state = heapq.heappop(pq)
            if d > dist.get(state, math.inf):
                continue
            u, horse, horse_left, held_horse, claimed, moved = state
            if u == dst:
                best = state
                break

            claim = self._claimable_horse(u, nodes_by_id, claimed, horse, held_horse)
            if claim:
                claimed_key = self._claim_key(u, claim)
                new_claimed = tuple(sorted((*claimed, claimed_key)))
                ns = (u, horse, horse_left, claim, new_claimed, moved)
                nd = d + self._resource_claim_frames(u, claim)
                if nd < dist.get(ns, math.inf):
                    dist[ns] = nd
                    prev[ns] = state
                    heapq.heappush(pq, (nd, seq, ns))
                    seq += 1

            for v, rt, dd in self.graph.adj.get(u, []):
                if v in avoid:
                    continue
                pre_edge_wait = 0
                if (not moved and self._opening_first_hop_applies(actor, src, u)
                        and v in obstacles):
                    pre_edge_wait = START_OBSTACLE_CLEAR_FRAMES
                wh, wh_left = self._spend_horse_wait(horse, horse_left, pre_edge_wait)
                edge_start_round = round_no + d + pre_edge_wait
                edge_frames, nh, nh_left, nheld = self._horse_edge_frames(
                    rt, dd, wh, wh_left, held_horse, edge_start_round,
                    weather, weather_base_round
                )
                process_start_round = edge_start_round + edge_frames
                process_frames = 0
                if process_destination or v != dst:
                    process_frames = self._process_frames(
                        v, nodes_by_id, process_start_round, weather,
                        weather_base_round
                    )
                nh, nh_left = self._spend_horse_wait(nh, nh_left, process_frames)
                nd = d + pre_edge_wait + edge_frames + process_frames
                ns = (v, nh, nh_left, nheld, claimed, True)
                if nd < dist.get(ns, math.inf):
                    dist[ns] = nd
                    prev[ns] = state
                    heapq.heappush(pq, (nd, seq, ns))
                    seq += 1

        if best is None:
            return RoutePlan(float("inf"), [])

        states = [best]
        while states[-1] != start_state:
            states.append(prev[states[-1]])
        states.reverse()

        path = [states[0][0]]
        for st in states[1:]:
            if st[0] != path[-1]:
                path.append(st[0])

        first_claim = None
        if len(states) >= 2 and states[0][0] == states[1][0]:
            before_claimed = set(states[0][4])
            after_claimed = set(states[1][4])
            added = after_claimed - before_claimed
            if added:
                first_claim = next(iter(added)).split(":", 1)[1]

        return RoutePlan(dist[best], path, first_claim)

    def _eta_to_node(self, actor, dst, nodes_by_id, round_no=0, weather=None) -> float:
        """Arrival ETA to a node, respecting current edge progress.

        Route plans normally include mandatory processing on the destination because
        delivery routing needs through-node costs. Choke races need the arrival
        moment instead: a guard can be set as soon as we stand on the choke, and the
        opponent reaches it before any local processing completes.
        """
        src = actor.get("currentNodeId")
        if not src:
            return float("inf")
        if src == dst and not actor.get("routeEdgeId"):
            return 0
        next_node = actor.get("nextNodeId")
        if not actor.get("routeEdgeId") or not next_node:
            return self._route_frames(
                src, dst, actor, nodes_by_id, round_no=round_no, weather=weather,
                process_destination=False
            )

        edge = self._edge_info(src, next_node)
        if edge is None:
            return self._route_frames(
                src, dst, actor, nodes_by_id, round_no=round_no, weather=weather,
                process_destination=False
            )
        route_type, distance = edge
        remaining = self._remaining_edge_required(actor, route_type, distance)
        horse, horse_left, held = self._initial_horse_state(actor)
        edge_frames, horse, horse_left, held = self._travel_required_frames(
            remaining, route_type, horse, horse_left, held, round_no, weather,
            round_no
        )
        if next_node == dst:
            return edge_frames

        process_frames = self._process_frames(
            next_node, nodes_by_id, round_no + edge_frames, weather, round_no
        )
        horse, horse_left = self._spend_horse_wait(
            horse, horse_left, process_frames
        )
        actor_at_next = self._actor_after_travel(
            actor, next_node, horse, horse_left, held
        )
        rest = self._route_frames(
            next_node, dst, actor_at_next, nodes_by_id,
            round_no=round_no + edge_frames + process_frames,
            weather=weather, weather_base_round=round_no,
            process_destination=False
        )
        return edge_frames + process_frames + rest

    @staticmethod
    def _actor_after_travel(actor, node, horse, horse_left, held):
        nxt = dict(actor)
        nxt["currentNodeId"] = node
        nxt["routeEdgeId"] = None
        nxt["nextNodeId"] = None

        resources = dict(actor.get("resources") or {})
        for h in HORSES:
            resources.pop(h, None)
        if held:
            resources[held] = max(1, resources.get(held, 0))
        nxt["resources"] = resources

        buffs = [
            b for b in actor.get("buffs") or []
            if b.get("type") not in HORSE_MOVE_PER_FRAME
        ]
        if horse and horse_left > 0:
            buffs.append({"type": horse, "remainingRound": horse_left})
        nxt["buffs"] = buffs
        return nxt

    def _initial_horse_state(self, actor) -> tuple[Optional[str], int, Optional[str]]:
        active = self._active_horse(actor)
        held = self._held_horse(actor)
        if active:
            return active[0], active[1], held
        return None, 0, held

    def _active_horse(self, actor) -> Optional[tuple[str, int]]:
        best = None
        for b in actor.get("buffs") or []:
            t = b.get("type")
            if t not in HORSE_MOVE_PER_FRAME:
                continue
            left = int(b.get("remainingRound", 0) or 0)
            if left <= 0:
                continue
            rank = (HORSE_MOVE_PER_FRAME[t], left)
            if best is None or rank > best[0]:
                best = (rank, t, left)
        if best is None:
            return None
        return best[1], best[2]

    def _claimable_horse(self, node, nodes_by_id, claimed, active, held) -> Optional[str]:
        if active or held:
            return None
        stock = nodes_by_id.get(node, {}).get("resourceStock") or {}
        for h in HORSES:
            if stock.get(h, 0) > 0 and self._claim_key(node, h) not in claimed:
                return h
        return None

    @staticmethod
    def _claim_key(node, horse) -> str:
        return f"{node}:{horse}"

    @staticmethod
    def _remaining_edge_required(actor, route_type, distance) -> int:
        required = math.ceil(distance * ROUTE_COST_COEF.get(route_type, 1500))
        progress = actor.get("edgeProgressMs")
        total = actor.get("edgeTotalMs")
        if progress is not None and total:
            try:
                progress_ratio = max(0.0, min(1.0, float(progress) / float(total)))
            except (TypeError, ValueError, ZeroDivisionError):
                progress_ratio = 0.0
            return max(0, math.ceil(required * (1.0 - progress_ratio)))

        permille = actor.get("edgeProgressPermille")
        if permille is None:
            move_progress = actor.get("moveProgress")
            if move_progress is not None:
                try:
                    permille = float(move_progress) * 1000
                except (TypeError, ValueError):
                    permille = 0
            else:
                permille = 0
        try:
            permille = max(0.0, min(1000.0, float(permille)))
        except (TypeError, ValueError):
            permille = 0.0
        return max(0, math.ceil(required * (1000.0 - permille) / 1000.0))

    def _resource_claim_frames(self, node, resource_type) -> int:
        return self._resource_claim_rounds.get((node, resource_type), RESOURCE_CLAIM_FRAMES)

    def _horse_edge_frames(
        self, route_type, distance, horse, horse_left, held, start_round=0,
        weather=None, weather_base_round=0
    ):
        required = math.ceil(distance * ROUTE_COST_COEF.get(route_type, 1500))
        return self._travel_required_frames(
            required, route_type, horse, horse_left, held, start_round,
            weather, weather_base_round
        )

    def _travel_required_frames(
        self, required, route_type, horse, horse_left, held, start_round=0,
        weather=None, weather_base_round=0
    ):
        if (not horse or horse_left <= 0) and held:
            horse = held
            horse_left = HORSE_DURATION[held]
            held = None
        progress = 0
        frames = 0
        while progress < required:
            if horse and horse_left > 0:
                base_speed = HORSE_MOVE_PER_FRAME[horse]
                horse_left -= 1
            else:
                base_speed = BASE_MOVE_PER_FRAME
                horse = None
                horse_left = 0
            multiplier = self._weather_move_multiplier(
                route_type, start_round + frames, weather, weather_base_round
            )
            progress += max(1, math.floor(base_speed * 1000 / multiplier))
            frames += 1
            if horse and horse_left <= 0:
                horse = None
        return frames, horse, horse_left, held

    @staticmethod
    def _spend_horse_wait(horse, horse_left, frames) -> tuple[Optional[str], int]:
        if not horse or horse_left <= 0 or frames <= 0:
            return horse, horse_left
        left = horse_left - frames
        if left <= 0:
            return None, 0
        return horse, left

    def _process_frames(self, node, nodes_by_id, start_round, weather=None, weather_base_round=0) -> int:
        base = self.graph.process_rounds.get(node, 0)
        if base <= 0:
            return 0
        process_type = nodes_by_id.get(node, {}).get("processType")
        extra = self._weather_process_extra(process_type, start_round, weather, weather_base_round)
        return base + extra

    def _weather_process_extra(self, process_type, frame_round, weather=None, weather_base_round=0) -> int:
        if not process_type:
            return 0
        extra = 0
        for w in self._weather_entries(weather, weather_base_round):
            if not (w["start"] <= frame_round < w["end"]):
                continue
            extra = max(extra, WEATHER_PROCESS_EXTRA.get((w["type"], process_type), 0))
        return extra

    def _weather_move_multiplier(self, route_type, frame_round, weather=None, weather_base_round=0) -> int:
        multiplier = 1000
        for w in self._weather_entries(weather, weather_base_round):
            if not (w["start"] <= frame_round < w["end"]):
                continue
            if w["region"] not in (None, "ALL", route_type):
                continue
            multiplier = max(
                multiplier,
                WEATHER_MOVE_MULTIPLIER.get((w["type"], route_type), 1000),
            )
        return multiplier

    @staticmethod
    def _weather_entries(weather=None, base_round=0) -> list[dict[str, Any]]:
        if not weather:
            return []
        entries: list[dict[str, Any]] = []
        for w in weather.get("active") or []:
            start = int(w.get("startRound", base_round) or base_round)
            if "durationRound" in w and "startRound" in w:
                end = start + int(w.get("durationRound", 0) or 0)
            elif "remainRound" in w:
                start = base_round
                end = start + int(w.get("remainRound", 0) or 0)
            else:
                end = start + 1
            if end > start:
                entries.append({
                    "type": w.get("type"),
                    "region": w.get("region"),
                    "start": start,
                    "end": end,
                })
        for w in weather.get("forecast") or []:
            if "startRound" not in w or "durationRound" not in w:
                continue
            start = int(w.get("startRound", 0) or 0)
            end = start + int(w.get("durationRound", 0) or 0)
            if end > start:
                entries.append({
                    "type": w.get("type"),
                    "region": w.get("region"),
                    "start": start,
                    "end": end,
                })
        return entries

    def _edge_info(self, a: str, b: str) -> Optional[tuple[str, int]]:
        for v, rt, dd in self.graph.adj.get(a, []):
            if v == b:
                return rt, dd
        return None

    def _opening_first_hop_applies(self, actor, route_src, current_node) -> bool:
        if route_src != self.start_node or current_node != self.start_node:
            return False
        if actor.get("playerId") == self.player_id:
            return not self._left_start
        return not self._opp_left_start

    def _is_opening_first_hop_obstacle(self, node, nxt, nodes_by_id, actor) -> bool:
        return (
            nxt
            and nodes_by_id.get(nxt, {}).get("hasObstacle")
            and self._opening_first_hop_applies(actor, node, node)
        )

    def _opening_obstacle_action(self, node, target, tasks):
        task = self._clear_task_for(node, target, tasks)
        if task:
            return [M.claim_task(task["taskId"])]
        return [M.clear(target)]

    def _clear_task_for(self, node, target, tasks):
        if not self._adjacent_or_same(node, target):
            return None
        for t in tasks:
            if t.get("nodeId") != target:
                continue
            if t.get("processType") != "CLEAR_OBSTACLE" and t.get("taskTemplateId") != "T04":
                continue
            if not t.get("active") or t.get("completed") or t.get("failed") or t.get("ownerPlayerId"):
                continue
            if int(t.get("processRound", START_OBSTACLE_CLEAR_FRAMES)) <= START_OBSTACLE_CLEAR_FRAMES:
                return t
        return None

    def _adjacent_or_same(self, node, target) -> bool:
        if node == target:
            return True
        return any(v == target for v, _rt, _dd in self.graph.adj.get(node, []))

    def _update_start_flags(self, me, opp) -> None:
        if me.get("routeEdgeId") or me.get("currentNodeId") != self.start_node:
            self._left_start = True
        if opp and (opp.get("routeEdgeId") or opp.get("currentNodeId") != self.start_node):
            self._opp_left_start = True

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
