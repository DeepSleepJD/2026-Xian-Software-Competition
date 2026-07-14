"""Blockade strategy: win the race to the first choke, freeze once, then farm.

Plan (feature/blockade-strategy-fix, 2026-07-05):
  1. From the map, find the choke points (cut-vertices) the opponent must pass.
     The OPENING ROUTE is chosen to win the race to the first start-side choke
     (delivery speed is only the tiebreak): on shortcut maps (S10-S13 / S11-S14
     edges) that choke is the ONLY deniable node, so first entry decides the
     whole denial game.
  2. Race there. En route, spend frames on a task / ice-box claim ONLY if the
     lead survives it: opp_eta - our_eta > op_frames + RACE_SAFETY.
  3. Camp the choke; the instant the opponent commits onto the edge into it
     (MOVING with >= guard-setup frames of edge left), SET_GUARD -- they arrive
     to a blocked node and freeze mid-edge.
  4. Fire-and-forget: once our guard is ACTIVE we leave and never re-guard
     (downstream chokes are bypassable on shortcut maps anyway). From there we
     farm FORWARD tasks to TASK_BASE_TARGET and net-positive resources, then
     deliver inside the normal buffer.

The window-card / contest layer is reused as-is; only navigation + guarding is new.
"""
import math
import heapq
import time
from dataclasses import dataclass
from typing import Any, Optional

from . import messages as M
from .contest import active_contest, pick_card
from .graph import BASE_MOVE_PER_FRAME, Graph, ROUTE_COST_COEF

TOTAL_ROUNDS = 600
DELIVER_MARGIN = 5           # safety frames before the delivery deadline (covers the
                             # obstacle clear-waits our frame estimate doesn't model, so
                             # camping on a choke never drags us past our own delivery)
DELIVERY_ABANDON_MARGIN = 50 # only stop forcing delivery once the ETA is this far
                             # beyond the deadline; e.g. ETA=200 abandons at 450
DENY_DELIVER_MARGIN = 0      # no buffer while an unsecured blockade is the only thing
                             # preventing the opponent from finishing
VERIFY_FRAMES = 6            # ~frames to VERIFY_GATE at the gate in RUSH
DELIVER_FRAMES = 2           # move-into-terminal + DELIVER
SCOUT_PROCESS_MIN_FRAMES = 2
SCOUT_DEFAULT_PROCESS_REDUCE = 3
SCOUT_MARKER_LIFETIME = 45
GUARD_KEEP_FRUIT = 6         # never spend guard fruit below this (keep some to deliver)
GUARD_SETUP_FRAMES = 5       # SET_GUARD read-bar (4) + activates next frame
SQUAD_REINFORCE_COST = 2     # squad members consumed per SQUAD_REINFORCE (rules 6.4)
GATE_GUARD_EXTRA_FRUIT = 1   # gate defense cap is 4 = 2 + 1*2; a 2nd fruit is wasted
TASK_TIME = 8                # rough frames a task claim+complete costs (deadline gate)
RACE_SAFETY = 8              # lead margin that must REMAIN after paying an op's frames
                             # pre-choke (we trust the ETA model -- horses/weather/scouts
                             # are simulated -- so this only covers guard-setup jitter)
FREEZE_SAFETY = 2            # extra edge-frame margin so the guard is up before arrival
TASK_BASE_TARGET = 130       # enough to fill delivery/task milestones; then deliver
TASK_FRAME_SCORE_COST = 0.12 # rough score lost per extra task-detour frame
ICE_BOX = "ICE_BOX"
RUSH_SPEED = "RUSH_SPEED"
HORSES = ("FAST_HORSE", "SHORT_HORSE")   # move-buff resources (fast first)
HORSE_MOVE_PER_FRAME = {"FAST_HORSE": 1200, "SHORT_HORSE": 1150, RUSH_SPEED: 1300}
HORSE_DURATION = {"FAST_HORSE": 20, "SHORT_HORSE": 14, RUSH_SPEED: 15}
RESOURCE_CLAIM_FRAMES = 2
START_OBSTACLE_CLEAR_FRAMES = 6
OPENING_SCORE_BUDGET_S = 0.25  # platform action window is 500ms/frame; round-1 full
                               # scoring of all opening candidates took ~1.08s and got
                               # every round-1 action voided (ACTION_TOO_LATE). Score
                               # cheap-heuristic-first under this budget instead.
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
        # guard-reinforcement bookkeeping: enemy weaken orders already counted,
        # and per-node count of weakens we still owe a SQUAD_REINFORCE for
        self._seen_weaken_orders: set[str] = set()
        self._reinforce_debt: dict[str, int] = {}
        self._scout_sent: set[str] = set()
        self._guard_blocked: set[str] = set()   # enemy guards blocking us
        self.route_avoid: set[str] = set()       # nodes to route around (variants/testing)
        self._resource_claim_rounds: dict[tuple[str, str], int] = {}
        self._left_start = False
        self._opp_left_start = False
        self._task_priority_mode = False
        self._delivery_abandoned = False
        self.task_base = 0
        self._counted_tasks: set[str] = set()
        self._task_attempts: dict[str, int] = {}
        self._opening_route_path: list[str] = []
        self._latest_tasks: list[dict[str, Any]] = []

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
        self._account_enemy_weakens(inquire_data.get("events") or [], nodes_by_id)
        self._update_start_flags(me, opp)
        self._account_tasks(tasks)
        self._latest_tasks = tasks
        self._maybe_choose_opening_route(me, node, round_no, tasks, nodes_by_id, weather)

        # Fire-and-forget: the freeze guard is ACTIVE -> the blockade did its job.
        # Never re-guard; farm forward tasks/resources and finish our own run.
        if (
            self._first_guard_node is not None
            and not self._task_priority_mode
            and self._we_hold(self._first_guard_node, nodes_by_id)
        ):
            self._enter_task_priority()

        if me.get("delivered") or me.get("retired"):
            return []

        # window card rides alongside the main action (separate quota)
        card = self._card(me, contests, round_no)

        # squad pre-clears obstacles ahead (separate quota) so the main car never
        # has to chain FORCED_PASS (two in a row are rejected: FORCED_PASS_REPEAT).
        squad = self._squad_action(node, me, opp, tasks, nodes_by_id, round_no, weather)

        # A hard delivery deadline beats speed buffs, ambushes, and any remaining
        # task farm: block only while our own finish is still safe.
        if self._must_deliver(node, me, opp, round_no, nodes_by_id, weather):
            main = self._advance_to(
                self.terminal_node if me.get("verified") else self.gate_node,
                me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )
            return self._ordered_actions(main, squad, card)

        # RUSH_SPEED IS a main-car action and is only valid mid-move -> issue it (as THE
        # main action) while we're MOVING; never when idle/parked (invalid + wasted).
        if self._rush_speed_action(me, state, phase):
            return self._ordered_actions([M.rush_speed()], squad, card)

        # Highest-priority local ambush: whenever we are already standing on a
        # node the opponent is about to enter, arm it. If they are still behind a
        # neighboring route node, the route-neighbor watch below decides whether
        # to wait, take a safe local op, or keep moving.
        if not me.get("verified"):
            local_ambush = self._local_ambush_action(
                me, opp, node, state, round_no, nodes_by_id, weather
            )
            if local_ambush:
                return self._ordered_actions(local_ambush, squad, card)
            watch = self._route_neighbor_watch_action(
                me, opp, node, state, phase, round_no, tasks, nodes_by_id, weather
            )
            if watch:
                return self._ordered_actions(watch, squad, card)

        # Endgame gate ambush: the gate is the one true cut-vertex before the
        # terminal (palace stations have branch bypasses), so while parked on it
        # -- pre-RUSH wait or post-verify -- freeze the opponent mid-edge the
        # moment they commit into the gate. Checked before rush-speed so the
        # sprint buff isn't burned while camping.
        if node == self.gate_node and (me.get("verified") or phase != "RUSH"):
            ambush = self._gate_ambush_action(
                me, opp, node, state, round_no, nodes_by_id, weather
            )
            if ambush:
                return self._ordered_actions(ambush, squad, card)

        # once verified we've committed to the delivery run -> always finish it
        # (we only ever VERIFY during our own delivery push), except for the safe
        # gate ambush window handled just above.
        if me.get("verified"):
            main = self._advance_to(
                self.terminal_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )
            return self._ordered_actions(main, squad, card)

        if self._should_abandon_delivery(node, me, round_no, nodes_by_id, weather):
            self._enter_task_priority(abandon_delivery=True)

        if self._task_priority_mode:
            main = self._task_priority_action(
                me, node, state, phase, round_no, tasks, nodes_by_id, weather
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
        already stop). The upstream delivery check uses a hard deadline while the
        denial is still unsecured, so we do not abandon a useful choke just for the
        normal delivery buffer."""
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

        if node in self.chokes and self._we_hold(node, nodes_by_id) and self._rolling_blockade_active():
            return self._advance_to(
                self.gate_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )

        # FREEZE: camp on a choke the opponent must still cross and SET_GUARD only the
        # instant they've COMMITTED onto the edge into it (MOVING, nextNode==choke) AND
        # enough edge is left for the guard to finish before they arrive. They then
        # arrive to a blocked node and freeze mid-edge -- no backtrack, no FORCED_PASS,
        # no BREAK_GUARD. If they haven't committed yet we hold the choke and wait;
        # once the opponent can no longer finish, the normal delivery buffer drags
        # us off to score.
        if self._first_choke_failed(node, me, opp, round_no, weather):
            self._enter_task_priority()
            return self._task_priority_action(
                me, node, state, phase, round_no, tasks, nodes_by_id, weather
            )

        if node in self.chokes and not self._we_hold(node, nodes_by_id) \
           and self._opp_must_cross(node, opp) \
           and (self._rolling_blockade_active() or not self._opp_walled_off(opp, nodes_by_id)):
            if self._freeze_window_open(opp, node, round_no, weather) and me.get("goodFruit", 0) > GUARD_KEEP_FRUIT:
                if self._first_guard_node is None:
                    self._first_guard_node = node
                self._guarded_round[node] = round_no
                return [M.set_guard(node, extra_good_fruit=self._guard_fruit(me))]
            if self._rolling_blockade_active():
                t = self._claimable_task_here(node, tasks, me, round_no)
                if t and self._spare_for_rolling_task(
                    node, me, opp, t, round_no, nodes_by_id, weather
                ):
                    return self._claim_task_action(t)
                return [M.wait()]
            # opponent not committed yet -> camp; use the wait for a task / ice-box
            # ONLY if the lead survives the op (won't miss the freeze / delivery)
            act = self._spare_op_here(node, me, opp, round_no, tasks, nodes_by_id, weather)
            if act:
                return act
            return [M.wait()]

        # a task / ice-box on the way -- but only with spare time: the op must NOT
        # let the opponent beat us to an unsecured choke, nor risk our own delivery.
        act = self._spare_op_here(node, me, opp, round_no, tasks, nodes_by_id, weather)
        if act:
            return act
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return [M.wait()]
        return self._advance_to(
            self.gate_node, me, node, state, phase, nodes_by_id, tasks,
            round_no, weather
        )

    def _rolling_blockade_active(self) -> bool:
        # only reachable as a fizzle-retry: guard attempted but never activated
        # (once it activates, decide() flips to task-priority and we never return)
        return self._first_guard_node is not None and not self._task_priority_mode

    def _enter_task_priority(self, abandon_delivery: bool = False) -> None:
        """The blockade phase is over (freeze active, or first choke unwinnable):
        farm forward tasks/resources under the normal delivery buffer. The opening
        corridor lock has served its purpose -- drop it so the farm planner may
        use every forward node."""
        self._task_priority_mode = True
        if abandon_delivery:
            self._delivery_abandoned = True
        self.route_avoid = set()

    def _first_choke_failed(self, node, me, opp, round_no, weather=None) -> bool:
        """The first start-side choke is no longer a viable freeze point."""
        if self._first_guard_node is not None or node != self._first_start_side_choke():
            return False
        if self._we_can_wait_for_first_choke(me, opp, node, round_no, weather):
            return False
        return True

    def _we_can_wait_for_first_choke(self, me, opp, node, round_no, weather=None) -> bool:
        if opp is None or me.get("goodFruit", 0) <= GUARD_KEEP_FRUIT:
            return False
        if not self._opp_must_cross(node, opp):
            return False
        if opp.get("currentNodeId") == node and not opp.get("routeEdgeId"):
            return False
        if opp.get("state") == "MOVING" and opp.get("nextNodeId") == node:
            return self._freeze_window_open(opp, node, round_no, weather)
        return True

    def _first_start_side_choke(self) -> Optional[str]:
        if not self.chokes:
            return None
        return self.chokes[-1]

    def _spare_for_rolling_task(self, node, me, opp, task, round_no, nodes_by_id, weather=None) -> bool:
        """While parked on a rolling-blockade choke, use the opponent ETA to decide
        whether a local task can finish before we still need to set the guard."""
        task_frames = self._task_process_frames(
            task, nodes_by_id, me, round_no, round_no
        )
        if round_no + task_frames + self._frames_to_deliver(node, me, nodes_by_id, round_no, weather) + DELIVER_MARGIN >= TOTAL_ROUNDS:
            return False
        if opp is None:
            return True
        if not self._opp_must_cross(node, opp):
            return False
        if opp.get("currentNodeId") == node and not opp.get("routeEdgeId"):
            return False
        if opp.get("state") == "MOVING" and opp.get("nextNodeId") == node:
            return False
        opp_eta = self._eta_to_node(
            opp, node, nodes_by_id, round_no=round_no, weather=weather
        )
        if opp_eta == float("inf"):
            return True
        return opp_eta >= task_frames + GUARD_SETUP_FRAMES + FREEZE_SAFETY

    def _spare_op_here(self, node, me, opp, round_no, tasks, nodes_by_id, weather=None):
        """A task claim or ICE_BOX claim at this node, if its frame cost fits both
        the delivery deadline and the choke race. Tasks first (worth more)."""
        t = self._claimable_task_here(node, tasks, me, round_no)
        if t is not None:
            op = self._task_op_frames(t, me, round_no, nodes_by_id)
            if self._spare_for_op(node, me, opp, op, round_no, nodes_by_id, weather):
                return self._claim_task_action(t)
        ice = self._ice_claim_frames_here(node, me, nodes_by_id, round_no)
        if ice is not None and self._spare_for_op(node, me, opp, ice, round_no, nodes_by_id, weather):
            return [M.claim_resource(node, ICE_BOX)]
        return None

    def _task_op_frames(self, task, me, round_no, nodes_by_id) -> int:
        """Frames a task holds us at its node. Measured on platform replays
        (r183 CLAIM -> r187 free, config 4): the claim submit frame is INCLUDED
        in processRound, so the true cost is exactly the (scout-reduced) config."""
        return self._task_process_frames(task, nodes_by_id, me, round_no, round_no)

    def _ice_claim_frames_here(self, node, me, nodes_by_id, round_no) -> Optional[int]:
        """Claim frames for an ICE_BOX in stock at this node, else None. Ice is the
        one resource always worth a stop when the frames are spare: it restores
        freshness at delivery (the router auto-claims horses; other resource types
        have no modelled effect, so we skip them)."""
        stock = nodes_by_id.get(node, {}).get("resourceStock") or {}
        if int(stock.get(ICE_BOX, 0) or 0) <= 0:
            return None
        return self._resource_claim_frames(node, ICE_BOX, nodes_by_id, round_no, me, round_no)

    def _spare_for_op(self, node, me, opp, op_frames, round_no, nodes_by_id, weather=None) -> bool:
        """Spend op_frames at this node only with genuine spare time: the op must
        not push us past our delivery deadline, and (before the blockade is
        secured) must leave RACE_SAFETY frames of lead to the nearest choke we
        still need AFTER paying for the op."""
        # (a) delivery must survive the op's time cost
        if round_no + op_frames + self._frames_to_deliver(node, me, nodes_by_id, round_no, weather) + DELIVER_MARGIN >= TOTAL_ROUNDS:
            return False
        # (b) the choke race: the nearest choke ahead that the opponent must still
        # cross and we don't yet hold -- the op must not lose us that race
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
            return opp_eta - our_eta > op_frames + RACE_SAFETY
        return True  # no unsecured choke ahead -> race already won, the op is safe

    def _opp_walled_off(self, opp, nodes_by_id) -> bool:
        """True if the opponent already can't reach the gate without crossing one of
        OUR active guards -- the blockade is secured, so stop camping downstream
        chokes they can't reach and go deliver."""
        if opp is None:
            return False
        opp_node = opp.get("currentNodeId")
        if not opp_node:
            return False
        my_guards = self._my_active_guards(nodes_by_id)
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

    def _local_ambush_action(self, me, opp, node, state, round_no, nodes_by_id, weather=None) -> list:
        """Global interception rule: if we reached a node before the opponent and
        they are coming in with enough setup time, SET_GUARD."""
        if state in BUSY_STATES or not node:
            return []
        if me.get("routeEdgeId") or me.get("nextNodeId"):
            return []
        if node == self.terminal_node:
            return []
        if opp is None or opp.get("delivered") or opp.get("retired"):
            return []
        if opp.get("currentNodeId") == node and not opp.get("routeEdgeId"):
            return []
        if self._guard_active(node, nodes_by_id):
            return []
        if self._guard_pending(node, round_no):
            return [M.wait()]

        if self._freeze_window_open(opp, node, round_no, weather):
            if me.get("goodFruit", 0) <= GUARD_KEEP_FRUIT:
                return []
            self._guarded_round[node] = round_no
            return [M.set_guard(node, extra_good_fruit=self._local_guard_fruit(node, me))]

        return []

    def _guard_active(self, node, nodes_by_id) -> bool:
        guard = (nodes_by_id.get(node) or {}).get("guard") or {}
        return bool(guard.get("active") and guard.get("defense", 0) > 0)

    def _guard_pending(self, node, round_no) -> bool:
        placed = self._guarded_round.get(node)
        return placed is not None and round_no - placed < GUARD_SETUP_FRAMES

    def _local_guard_fruit(self, node, me) -> int:
        if node == self.gate_node:
            return min(GATE_GUARD_EXTRA_FRUIT, self._guard_fruit(me))
        return self._guard_fruit(me)

    def _route_neighbor_watch_action(
        self, me, opp, node, state, phase, round_no, tasks, nodes_by_id,
        weather=None
    ) -> list:
        """Hold a route node while the opponent is still behind it.

        A behind neighbor is defined by delivery ETA, not by hard-coded route
        order: from that neighbor, finishing delivery is at least one guard
        setup window slower than from our current node.
        """
        if state in BUSY_STATES or not node or node in (self.gate_node, self.terminal_node):
            return []
        if me.get("routeEdgeId") or me.get("nextNodeId") or me.get("verified"):
            return []
        if node == self._first_guard_node and self._we_hold(node, nodes_by_id):
            return []
        if opp is None or opp.get("delivered") or opp.get("retired"):
            return []

        my_delivery = self._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        if my_delivery == float("inf"):
            return []
        if round_no + my_delivery + DELIVER_MARGIN >= TOTAL_ROUNDS:
            return []

        behind = self._behind_neighbors(node, me, nodes_by_id, round_no, weather)
        if not behind:
            return []

        opp_node = opp.get("currentNodeId")
        opp_next = opp.get("nextNodeId")
        opp_is_moving = bool(opp.get("routeEdgeId") or opp_next)
        relevant = False
        bypassing = False
        if opp_is_moving and opp_next in behind:
            relevant = True
        elif opp_node in behind:
            relevant = True
            bypassing = opp_is_moving and opp_next != node
        if not relevant:
            return []
        if self._opponent_forced_passing_from_behind(opp, behind):
            return self._advance_to(
                self.gate_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )

        lead = self._delivery_progress_lead(me, opp, node, my_delivery, round_no, nodes_by_id, weather)
        act = self._safe_op_here_with_lead(
            node, me, opp, round_no, tasks, nodes_by_id, my_delivery, lead, weather
        )
        if act:
            return act
        if bypassing:
            return self._advance_to(
                self.gate_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )
        return [M.wait()]

    @staticmethod
    def _opponent_forced_passing_from_behind(opp, behind: set[str]) -> bool:
        if opp.get("currentNodeId") not in behind:
            return False
        if opp.get("state") == "FORCED_PASSING":
            return True
        proc = opp.get("currentProcess") or {}
        return proc.get("action") == "FORCED_PASS" or proc.get("processType") == "FORCED_PASS"

    def _behind_neighbors(self, node, me, nodes_by_id, round_no=0, weather=None) -> set[str]:
        current_eta = self._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        if current_eta == float("inf"):
            return set()
        threshold = GUARD_SETUP_FRAMES + FREEZE_SAFETY
        behind: set[str] = set()
        for nxt, _rt, _dd in self.graph.adj.get(node, []):
            if nxt == self.terminal_node:
                continue
            eta = self._frames_to_deliver(nxt, me, nodes_by_id, round_no, weather)
            if eta != float("inf") and eta - current_eta > threshold:
                behind.add(nxt)
        return behind

    def _delivery_progress_lead(
        self, me, opp, node, my_delivery, round_no, nodes_by_id, weather=None
    ) -> float:
        opp_delivery = self._opponent_frames_to_deliver(
            opp, nodes_by_id, round_no, weather
        )
        if opp_delivery == float("inf"):
            return float("inf")
        return opp_delivery - my_delivery

    def _safe_op_here_with_lead(
        self, node, me, opp, round_no, tasks, nodes_by_id, my_delivery, lead,
        weather=None
    ) -> Optional[list]:
        task = self._claimable_task_here(node, tasks, me, round_no)
        if task is not None:
            frames = self._task_op_frames(task, me, round_no, nodes_by_id)
            if self._op_fits_delivery_and_lead(round_no, frames, my_delivery, lead) \
                    and self._spare_for_op(node, me, opp, frames, round_no, nodes_by_id, weather):
                return self._claim_task_action(task)

        ice = self._ice_claim_frames_here(node, me, nodes_by_id, round_no)
        if ice is not None and self._op_fits_delivery_and_lead(round_no, ice, my_delivery, lead) \
                and self._spare_for_op(node, me, opp, ice, round_no, nodes_by_id, weather):
            return [M.claim_resource(node, ICE_BOX)]

        horse = self._claimable_horse_for_wait(node, me, nodes_by_id)
        if horse is not None:
            frames = self._resource_claim_frames(
                node, horse, nodes_by_id, round_no, me, round_no
            )
            if self._op_fits_delivery_and_lead(round_no, frames, my_delivery, lead) \
                    and self._spare_for_op(node, me, opp, frames, round_no, nodes_by_id, weather):
                return [M.claim_resource(node, horse)]
        return None

    @staticmethod
    def _op_fits_delivery_and_lead(round_no, op_frames, my_delivery, lead) -> bool:
        if round_no + op_frames + my_delivery + DELIVER_MARGIN >= TOTAL_ROUNDS:
            return False
        return lead > op_frames + GUARD_SETUP_FRAMES + FREEZE_SAFETY

    def _claimable_horse_for_wait(self, node, me, nodes_by_id) -> Optional[str]:
        active, _left, held = self._initial_horse_state(me)
        return self._claimable_horse(node, nodes_by_id, tuple(), active, held)

    # ---- guard reinforcement ----
    def _account_enemy_weakens(self, events, nodes_by_id) -> None:
        """Count enemy SQUAD_WEAKEN aimed at a guard we hold; each one is one
        SQUAD_REINFORCE of debt. Keyed by orderId so the dispatch event and the
        later landing event of the same order count once."""
        for e in events:
            etype = e.get("type")
            if etype not in ("SQUAD_DISPATCH", "SQUAD_WEAKEN"):
                continue
            pl = e.get("payload") or {}
            if pl.get("playerId") == self.player_id:
                continue
            if etype == "SQUAD_DISPATCH" and pl.get("action") != "SQUAD_WEAKEN":
                continue
            target = pl.get("targetNodeId")
            order = pl.get("orderId")
            if not target or (order and order in self._seen_weaken_orders):
                continue
            if not self._we_hold(target, nodes_by_id):
                continue
            if order:
                self._seen_weaken_orders.add(order)
            self._reinforce_debt[target] = self._reinforce_debt.get(target, 0) + 1

    def _guard_reinforce_action(self, me, nodes_by_id) -> list:
        """One SQUAD_REINFORCE per enemy weaken aimed at a still-live guard of
        ours. Held while the guard sits at its defense cap (the +2 would be
        wasted -- answer once the weaken lands) and dropped once the guard is
        gone (a defense-0 guard is removed and can never be re-activated)."""
        if int(me.get("squadAvailable", 0) or 0) < SQUAD_REINFORCE_COST:
            return []
        for nid in list(self._reinforce_debt):
            if self._reinforce_debt[nid] <= 0:
                continue
            guard = (nodes_by_id.get(nid) or {}).get("guard") or {}
            if not (guard.get("active") and guard.get("ownerTeamId") == self._my_team
                    and guard.get("defense", 0) > 0):
                self._reinforce_debt[nid] = 0
                continue
            if guard.get("defense", 0) >= self._guard_defense_cap(nid, nodes_by_id):
                continue
            self._reinforce_debt[nid] -= 1
            return [M.squad_reinforce(nid)]
        return []

    def _guard_defense_cap(self, nid, nodes_by_id) -> int:
        """Defense cap by node class (rules 6.2.1)."""
        node = nodes_by_id.get(nid) or {}
        if nid == self.gate_node:
            return 4
        if node.get("nodeType") == "KEY_PASS":
            return 7
        if node.get("hasObstacle"):
            return 5
        return 6

    # ---- endgame gate ambush ----
    def _gate_ambush_action(self, me, opp, node, state, round_no, nodes_by_id, weather=None) -> list:
        """Camp the gate while we have delivery slack and the opponent is behind it.

        S14 is the hard gate, so do not leave merely because the opponent ETA
        model says they miss. Stay, reinforce any active guard via the squad path,
        and SET_GUARD the instant they commit onto an edge into the gate. Only the
        top-level delivery deadline should pull us off this node.
        """
        if state in BUSY_STATES or node != self.gate_node:
            return []
        if me.get("routeEdgeId") or me.get("nextNodeId"):
            return []
        if not self._opponent_behind_gate(opp):
            return []
        if self._must_deliver(node, me, opp, round_no, nodes_by_id, weather):
            return []
        if not self._we_hold(node, nodes_by_id) \
           and self._freeze_window_open(opp, node, round_no, weather) \
           and me.get("goodFruit", 0) > GUARD_KEEP_FRUIT:
            self._guarded_round[node] = round_no
            return [M.set_guard(node, extra_good_fruit=GATE_GUARD_EXTRA_FRUIT)]
        return [M.wait()]

    def _opponent_behind_gate(self, opp) -> bool:
        if opp is None or opp.get("delivered") or opp.get("retired"):
            return False
        opp_node = opp.get("currentNodeId")
        if opp_node in (self.gate_node, self.terminal_node):
            return False
        if opp.get("routeEdgeId") and opp.get("nextNodeId") == self.terminal_node:
            return False
        return bool(opp_node)

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

    def _squad_action(self, node, me, opp, tasks, nodes_by_id, round_no=0, weather=None) -> list:
        """Squad priorities: (1) REINFORCE a live guard of ours the enemy is
        squad-weakening (+2 answers their -2, see _guard_reinforce_action);
        (2) CLEAR obstacles on our path so the main car MOVEs through (we never
        FORCED_PASS), dispatched to the nearest uncleared obstacle ahead;
        (3) scout."""
        squad_available = int(me.get("squadAvailable", 0) or 0)
        if squad_available < 1:
            return []
        reinforce = self._guard_reinforce_action(me, nodes_by_id)
        if reinforce:
            return reinforce
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        if squad_available >= 2:
            task_obstacle = self._post_freeze_task_obstacle(
                node, me, opp, tasks, nodes_by_id, obstacles, round_no, weather
            )
            if task_obstacle and task_obstacle not in self._squad_sent:
                self._squad_sent.add(task_obstacle)
                return [M.squad_clear(task_obstacle)]

        avoid = self._guard_blocked | self.route_avoid
        plan = self._route_plan(
            node, self.gate_node, me, nodes_by_id, avoid=avoid,
            obstacles=obstacles, round_no=round_no, weather=weather
        )
        if plan.frames == float("inf"):
            plan = self._route_plan(
                node, self.gate_node, me, nodes_by_id, obstacles=obstacles,
                round_no=round_no, weather=weather
            )
        path = plan.path
        if squad_available >= 2:
            for idx, nid in enumerate(path[1:], start=1):
                if idx == 1 and self._is_opening_first_hop_obstacle(node, nid, nodes_by_id, me):
                    continue
                if nid in obstacles and nid not in self._squad_sent:
                    self._squad_sent.add(nid)   # nearest uncleared obstacle on our path
                    return [M.squad_clear(nid)]
        scout = self._squad_scout_action(path, node, me, round_no, nodes_by_id, weather)
        if scout:
            return scout
        return []

    def _post_freeze_task_obstacle(
        self, node, me, opp, tasks, nodes_by_id, obstacles, round_no=0, weather=None
    ) -> Optional[str]:
        projected = self._post_freeze_projected_node(
            node, me, opp, nodes_by_id, round_no, weather
        )
        if not projected:
            return None
        actor = self._actor_after_travel(me, projected, *self._initial_horse_state(me))
        dest = self._best_task_waypoint(
            projected, actor, tasks, nodes_by_id, round_no, weather,
            route_avoid=set()
        )
        if dest in obstacles:
            return dest
        return None

    def _post_freeze_projected_node(
        self, node, me, opp, nodes_by_id, round_no=0, weather=None
    ) -> Optional[str]:
        # Do not spend squad on future farming while the first freeze is only a
        # projection. Keep remote clears for after the blockade actually flips
        # into task-priority mode; main-route obstacle clears still happen above.
        if not self._task_priority_mode:
            return None
        return me.get("nextNodeId") or node

    def _maybe_choose_opening_route(self, me, node, round_no, tasks, nodes_by_id, weather=None) -> None:
        if self.route_avoid or self._opening_route_path:
            return
        if node != self.start_node or me.get("routeEdgeId") or self._left_start:
            return
        if not self.graph.adj or not nodes_by_id:
            return

        candidates = self._opening_candidate_paths(nodes_by_id)
        # cheap presort so the promising corridors are fully scored before the
        # deadline; full scoring is ~10ms/path and must fit the 500ms frame window
        candidates.sort(key=self._opening_rough_frames)
        deadline = time.monotonic() + OPENING_SCORE_BUDGET_S

        best = None
        for path in candidates:
            score = self._opening_route_score(path, me, round_no, tasks, nodes_by_id, weather)
            if score is not None and (best is None or score[0] < best[0]):
                best = score
            if time.monotonic() >= deadline and best is not None:
                break
        if best is None:
            return

        _, path = best
        self._opening_route_path = path
        route_nodes = set(path)
        self.route_avoid = {
            nid for nid in nodes_by_id
            if nid not in route_nodes and nid != self.terminal_node
        }

    def _opening_rough_frames(self, path) -> float:
        """Cheap ordering key for opening candidates: plain move frames plus
        mandatory process waits, no horses/weather/scouts. Only used to decide
        WHICH candidates get the expensive scoring first."""
        total = 0.0
        for a, b in zip(path, path[1:]):
            edge = self._edge_info(a, b)
            if edge is None:
                return float("inf")
            route_type, distance = edge
            coef = ROUTE_COST_COEF.get(route_type, 1500)
            total += math.ceil(math.ceil(distance * coef) / BASE_MOVE_PER_FRAME)
            total += self.graph.process_rounds.get(b, 0)
        return total

    def _opening_candidate_paths(self, nodes_by_id) -> list[list[str]]:
        limit = max(4, len(nodes_by_id) + 1)
        paths: list[list[str]] = []

        def dfs(node, path):
            if len(paths) >= 128:
                return
            if node == self.gate_node:
                paths.append(path[:])
                return
            if len(path) >= limit:
                return
            for nxt, _rt, _dd in self.graph.adj.get(node, []):
                if nxt in path or nxt == self.terminal_node:
                    continue
                dfs(nxt, [*path, nxt])

        dfs(self.start_node, [self.start_node])
        return paths

    def _opening_route_score(self, path, me, round_no, tasks, nodes_by_id, weather=None):
        if len(path) < 2 or path[-1] != self.gate_node:
            return None
        avoid = {
            nid for nid in nodes_by_id
            if nid not in set(path) and nid != self.terminal_node
        }
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        plan = self._route_plan(
            self.start_node, self.gate_node, me, nodes_by_id, avoid=avoid,
            obstacles=obstacles, round_no=round_no, weather=weather
        )
        if plan.frames == float("inf") or plan.path != path:
            return None

        verify = self._verify_frames(me, nodes_by_id, round_no + plan.frames, round_no)
        terminal = self._route_frames(
            self.gate_node, self.terminal_node, me, nodes_by_id,
            round_no=round_no + plan.frames + verify, weather=weather,
            weather_base_round=round_no
        )
        if terminal == float("inf"):
            return None

        base = plan.frames + verify + terminal + DELIVER_FRAMES
        squad_budget = self._opening_scout_budget(path, me, nodes_by_id)
        if squad_budget < 0:
            return None
        savings = self._opening_scout_savings(path, tasks, nodes_by_id, squad_budget)
        race = self._opening_choke_race_frames(
            path, me, tasks, nodes_by_id, squad_budget, avoid, obstacles,
            round_no, weather
        )
        # PRIMARY: win the race to the first start-side choke (the only deniable
        # node on shortcut maps). Total delivery speed is the tiebreak.
        return (race, base - savings), path

    def _opening_choke_race_frames(
        self, path, me, tasks, nodes_by_id, squad_budget, avoid, obstacles,
        round_no, weather=None
    ) -> float:
        """Frames to REACH the first start-side choke along this corridor (arrival
        matters, not through-processing), minus the scout savings realizable
        before it. 0 on choke-less maps so the delivery tiebreak decides alone."""
        choke = self._first_start_side_choke()
        if not choke:
            return 0.0
        if choke not in path:
            return float("inf")
        frames = self._route_frames(
            self.start_node, choke, me, nodes_by_id, avoid=avoid,
            obstacles=obstacles, round_no=round_no, weather=weather,
            process_destination=False
        )
        if frames == float("inf"):
            return frames
        prefix = path[:path.index(choke) + 1]
        return frames - self._opening_scout_savings(prefix, tasks, nodes_by_id, squad_budget)

    def _opening_scout_budget(self, path, me, nodes_by_id) -> int:
        budget = int(me.get("squadAvailable", 0) or 0)
        for idx, nid in enumerate(path[1:], start=1):
            if not nodes_by_id.get(nid, {}).get("hasObstacle"):
                continue
            if idx == 1 and self._is_opening_first_hop_obstacle(path[0], nid, nodes_by_id, me):
                continue
            budget -= 2
        return budget

    def _opening_scout_savings(self, path, tasks, nodes_by_id, squad_budget) -> int:
        task_nodes = {
            t.get("nodeId") for t in tasks
            if t.get("active") and not t.get("completed") and not t.get("failed")
        }
        savings: list[int] = []
        for nid in path[1:]:
            if nid == self.gate_node:
                savings.append(self._scout_saving_for_frames(VERIFY_FRAMES))
                continue
            frames = self._node_process_round(nid, nodes_by_id)
            if frames <= 0:
                continue
            # A single marker at a task node is consumed by the task first, so don't
            # count it as mandatory-process savings in the opening route estimate.
            if nid in task_nodes:
                continue
            savings.append(self._scout_saving_for_frames(frames))
        savings = [s for s in savings if s > 0]
        savings.sort(reverse=True)
        return sum(savings[:max(0, squad_budget)])

    @staticmethod
    def _scout_saving_for_frames(frames: int) -> int:
        return max(0, frames - max(SCOUT_PROCESS_MIN_FRAMES, frames - SCOUT_DEFAULT_PROCESS_REDUCE))

    def _squad_scout_action(self, path, node, me, round_no, nodes_by_id, weather=None) -> list:
        if not path:
            return []
        candidates = []
        task_nodes = {
            t.get("nodeId") for t in self._latest_tasks
            if t.get("active") and not t.get("completed") and not t.get("failed")
        }
        for nid in path[1:]:
            if nid in self._scout_sent or self._has_own_scout(nid, nodes_by_id):
                continue
            if nid == self.gate_node:
                saving = self._scout_saving_for_frames(VERIFY_FRAMES)
            else:
                frames = self._node_process_round(nid, nodes_by_id)
                if frames <= 0 or nid in task_nodes:
                    continue
                saving = self._scout_saving_for_frames(frames)
            if saving <= 0:
                continue
            eta = self._eta_to_node(
                me, nid, nodes_by_id, round_no=round_no, weather=weather,
                avoid=self._guard_blocked | self.route_avoid
            )
            if eta == float("inf"):
                continue
            delay = self._squad_delay(node, nid, me, nodes_by_id, round_no, weather)
            if delay <= eta <= delay + SCOUT_MARKER_LIFETIME:
                candidates.append((-saving, eta, nid))

        if not candidates:
            return []
        candidates.sort()
        target = candidates[0][2]
        self._scout_sent.add(target)
        return [M.squad_scout(target)]

    def _has_own_scout(self, node, nodes_by_id) -> bool:
        for marker in nodes_by_id.get(node, {}).get("scouted") or []:
            if marker.get("teamId") == self._my_team and int(marker.get("remainingTriggers", 1) or 0) > 0:
                return True
        return False

    def _squad_delay(self, node, target, me, nodes_by_id, round_no=0, weather=None) -> int:
        origin = me.get("currentNodeId") or node
        tx, ty = self._node_xy(target, nodes_by_id)
        ox, oy = self._node_xy(origin, nodes_by_id)
        dist = max(abs(tx - ox), abs(ty - oy))
        delay = min(15, max(3, math.ceil(dist / 3)))
        if self._mountain_fog_on_node(target, nodes_by_id, round_no, weather):
            delay = min(15, delay + 2)
        return delay

    @staticmethod
    def _node_xy(node, nodes_by_id) -> tuple[int, int]:
        n = nodes_by_id.get(node, {})
        return int(n.get("x", 0) or 0), int(n.get("y", 0) or 0)

    def _mountain_fog_on_node(self, node, nodes_by_id, round_no=0, weather=None) -> bool:
        n = nodes_by_id.get(node, {})
        if "MOUNTAIN" not in str(n.get("nodeType", "")):
            return False
        for w in self._weather_entries(weather, round_no):
            if not (w["start"] <= round_no < w["end"]):
                continue
            if w["type"] == "MOUNTAIN_FOG" and w["region"] in (None, "ALL", "MOUNTAIN"):
                return True
        return False

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
            if nxt in self._squad_sent:
                return [M.wait()]
            return self._opening_obstacle_action(node, nxt, tasks or [])
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

    def _task_priority_action(self, me, node, state, phase, round_no, tasks, nodes_by_id, weather=None):
        """Farm phase (after the freeze landed, or the first choke became
        unwinnable): claim worthwhile tasks and ice-boxes under the normal
        delivery buffer, then complete delivery."""
        if state in BUSY_STATES:
            return []
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return self._advance_to(
                self.gate_node, me, node, state, phase, nodes_by_id, tasks,
                round_no, weather
            )
        task = self._claimable_task_here(node, tasks, me, round_no)
        if task is not None:
            return self._claim_task_action(task)
        ice = self._ice_claim_frames_here(node, me, nodes_by_id, round_no)
        if ice is not None and round_no + ice + self._frames_to_deliver(
            node, me, nodes_by_id, round_no, weather
        ) + DELIVER_MARGIN < TOTAL_ROUNDS:
            return [M.claim_resource(node, ICE_BOX)]
        if node == self.gate_node and not me.get("verified") and phase != "RUSH":
            return [M.wait()]
        if self._needs_process(node, nodes_by_id) and node not in self.processed:
            return [M.process(node)]
        dest = self._best_task_waypoint(node, me, tasks, nodes_by_id, round_no, weather)
        return self._advance_to(
            dest or self.gate_node, me, node, state, phase, nodes_by_id, tasks,
            round_no, weather
        )

    def _claim_task_action(self, task):
        task_id = task["taskId"]
        self._task_attempts[task_id] = self._task_attempts.get(task_id, 0) + 1
        return [M.claim_task(task_id)]

    def _claimable_task_here(self, node, tasks, me, round_no) -> Optional[dict[str, Any]]:
        if not self._delivery_abandoned and self._task_base_score(me) >= TASK_BASE_TARGET:
            return None
        best = None
        for t in tasks:
            if t.get("nodeId") != node or not self._task_claimable(t, me, round_no):
                continue
            if best is None or int(t.get("score", 0) or 0) > int(best.get("score", 0) or 0):
                best = t
        return best

    def _task_claimable(self, task, me, round_no) -> bool:
        task_id = task.get("taskId")
        if not isinstance(task_id, str):
            return False
        if not task.get("active") or task.get("completed") or task.get("failed"):
            return False
        owner = task.get("ownerPlayerId", 0)
        if owner not in (0, None, self.player_id):
            return False
        protected = task.get("protectionPlayerId", 0)
        if protected not in (0, None, self.player_id):
            return False
        expire = int(task.get("expireRound", 0) or 0)
        if expire and round_no >= expire:
            return False
        if task.get("taskTemplateId") == "T06" and self._held_horse(me) is None:
            return False
        if self._task_attempts.get(task_id, 0) >= 3:
            return False
        return True

    def _task_process_frames(
        self, task, nodes_by_id=None, actor=None, start_round=0,
        weather_base_round=0
    ) -> int:
        frames = int(task.get("processRound", TASK_TIME) or TASK_TIME)
        target = task.get("nodeId")
        if not target or nodes_by_id is None:
            return frames
        reduce = self._scout_process_reduce(
            target, nodes_by_id, actor, start_round, weather_base_round
        )
        return self._apply_scout_process_reduce(frames, reduce)

    def _best_task_waypoint(
        self, node, me, tasks, nodes_by_id, round_no, weather=None,
        route_avoid: Optional[set[str]] = None
    ) -> Optional[str]:
        if not self._delivery_abandoned and self._task_base_score(me) >= TASK_BASE_TARGET:
            return None
        direct = self._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        # farm FORWARD only: never route back across our own freeze guard (the
        # frozen opponent unfreezes the moment the guard drops, and re-entry of a
        # guarded node is not a modelled move)
        avoid = self._guard_blocked | (self.route_avoid if route_avoid is None else route_avoid)
        if self._first_guard_node:
            avoid = avoid | {self._first_guard_node}
        best_node = None
        best_net = 0.0
        for task in tasks:
            if not self._task_claimable(task, me, round_no):
                continue
            target = task.get("nodeId")
            if not target or target == node:
                continue
            to_task = self._eta_to_node(
                me, target, nodes_by_id, round_no=round_no,
                weather=weather, avoid=avoid
            )
            if to_task == float("inf"):
                continue
            task_frames = self._task_process_frames(
                task, nodes_by_id, me, round_no + to_task, round_no
            )
            finish_task_round = round_no + to_task + task_frames
            expire = int(task.get("expireRound", 0) or 0)
            if expire and finish_task_round >= expire:
                continue
            if self._delivery_abandoned:
                total = to_task + task_frames
                detour = total
            else:
                deliver_after = self._frames_to_deliver(
                    target, me, nodes_by_id, finish_task_round, weather
                )
                if deliver_after == float("inf"):
                    continue
                total = to_task + task_frames + deliver_after
                if round_no + total + DELIVER_MARGIN >= TOTAL_ROUNDS:
                    continue
                detour = max(0.0, total - direct) if direct != float("inf") else total
            net = self._task_value(task, me) - detour * TASK_FRAME_SCORE_COST
            if net > best_net:
                best_node = target
                best_net = net
        return best_node

    def _task_value(self, task, me) -> float:
        score = float(task.get("score", 0) or 0)
        if self._delivery_abandoned:
            return score * 2.5
        base = self._task_base_score(me)
        if base < 90:
            return score * 2.5
        if base < TASK_BASE_TARGET:
            return score
        return 0.0

    def _task_base_score(self, me) -> int:
        score = me.get("taskScore")
        if isinstance(score, (int, float)):
            return max(self.task_base, int(score))
        return self.task_base

    def _account_tasks(self, tasks) -> None:
        for task in tasks:
            task_id = task.get("taskId")
            if (
                task.get("completed")
                and task.get("ownerPlayerId") == self.player_id
                and task_id not in self._counted_tasks
            ):
                self._counted_tasks.add(task_id)
                self.task_base += int(task.get("score", 0) or 0)

    # ---- delivery-time safety ----
    def _rush_speed_action(self, me, state, phase) -> bool:
        # RUSH_SPEED is a main-car action valid only DURING a move (state MOVING).
        if phase != "RUSH" or state != "MOVING":
            return False
        if me.get("delivered") or me.get("retired"):
            return False
        if int(me.get("rushTacticUsedCount", 0) or 0) > 0:
            return False
        if me.get("goodFruit", 0) < 2:
            return False
        if self._active_horse(me):
            return False
        # Do not spend a main action on speed when the next useful action is
        # already a zero-distance terminal delivery.
        if me.get("verified") and me.get("currentNodeId") == self.terminal_node:
            return False
        return True

    def _should_abandon_delivery(self, node, me, round_no, nodes_by_id, weather=None) -> bool:
        if self._delivery_abandoned or me.get("verified"):
            return False
        need = self._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        return round_no + need >= TOTAL_ROUNDS + DELIVERY_ABANDON_MARGIN

    def _must_deliver(self, node, me, opp, round_no, nodes_by_id, weather=None) -> bool:
        if self._delivery_abandoned:
            return False
        need = self._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        if need == float("inf"):
            return False
        if round_no + need >= TOTAL_ROUNDS + DELIVERY_ABANDON_MARGIN:
            return False
        margin = DELIVER_MARGIN
        if self._deny_still_matters(node, opp, round_no, nodes_by_id, weather):
            margin = DENY_DELIVER_MARGIN
        return round_no + need + margin >= TOTAL_ROUNDS

    def _deny_still_matters(self, node, opp, round_no, nodes_by_id, weather=None) -> bool:
        """True while leaving now gives the opponent a fastest-route finish and we
        still have a choke ahead/underfoot that can deny that finish."""
        if self._task_priority_mode:
            return False
        return (
            self._opponent_can_still_deliver(opp, round_no, nodes_by_id, weather)
            and self._live_deny_choke_exists(node, opp)
        )

    def _live_deny_choke_exists(self, node, opp) -> bool:
        if opp is None:
            return False
        for c in reversed(self.chokes):  # start-side first, same race order as tasks
            if not self._opp_must_cross(c, opp):
                continue
            # Only chokes we are at or still before are useful. If removing c still
            # leaves us a route from here to the gate, then we have already passed it.
            if node != c and self.graph.path_frames(node, self.gate_node, avoid={c}) != float("inf"):
                continue
            return True
        return False

    def _opponent_can_still_deliver(self, opp, round_no, nodes_by_id, weather=None) -> bool:
        frames = self._opponent_frames_to_deliver(opp, nodes_by_id, round_no, weather)
        return round_no + frames < TOTAL_ROUNDS

    def _opponent_frames_to_deliver(self, opp, nodes_by_id, round_no=0, weather=None) -> float:
        """Optimistic opponent delivery ETA. Optimistic is intentional: if even this
        fastest estimate misses the deadline, we can safely leave the blockade."""
        if opp is None or opp.get("retired"):
            return float("inf")
        if opp.get("delivered"):
            return 0

        avoid = self._my_active_guards(nodes_by_id)
        if opp.get("routeEdgeId") and opp.get("nextNodeId") in avoid:
            return float("inf")

        if opp.get("verified"):
            to_term = self._eta_to_node(
                opp, self.terminal_node, nodes_by_id, round_no=round_no,
                weather=weather, avoid=avoid
            )
            return to_term + DELIVER_FRAMES

        to_gate = self._eta_to_node(
            opp, self.gate_node, nodes_by_id, round_no=round_no,
            weather=weather, avoid=avoid
        )
        if to_gate == float("inf"):
            return float("inf")
        verify = self._verify_frames(opp, nodes_by_id, round_no + to_gate, round_no)
        to_term = self._route_frames(
            self.gate_node, self.terminal_node, opp, nodes_by_id,
            avoid=avoid, round_no=round_no + to_gate + verify,
            weather=weather, weather_base_round=round_no
        )
        if to_term == float("inf"):
            return float("inf")
        return to_gate + verify + to_term + DELIVER_FRAMES

    def _frames_to_deliver(self, node, me, nodes_by_id, round_no=0, weather=None) -> float:
        to_gate = 0 if me.get("verified") else self._route_frames(
            node, self.gate_node, me, nodes_by_id, round_no=round_no,
            weather=weather, weather_base_round=round_no
        )
        if to_gate == float("inf"):
            return float("inf")
        verify = 0 if me.get("verified") else self._verify_frames(
            me, nodes_by_id, round_no + to_gate, round_no
        )
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
                nd = d + self._resource_claim_frames(
                    u, claim, nodes_by_id, round_no + d, actor,
                    weather_base_round
                )
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
                        weather_base_round, actor
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

    def _eta_to_node(self, actor, dst, nodes_by_id, round_no=0, weather=None, avoid=None) -> float:
        """Arrival ETA to a node, respecting current edge progress.

        Route plans normally include mandatory processing on the destination because
        delivery routing needs through-node costs. Choke races need the arrival
        moment instead: a guard can be set as soon as we stand on the choke, and the
        opponent reaches it before any local processing completes.
        """
        avoid = avoid or set()
        src = actor.get("currentNodeId")
        if not src:
            return float("inf")
        if src == dst and not actor.get("routeEdgeId"):
            return 0
        next_node = actor.get("nextNodeId")
        if not actor.get("routeEdgeId") or not next_node:
            return self._route_frames(
                src, dst, actor, nodes_by_id, round_no=round_no, weather=weather,
                process_destination=False, avoid=avoid
            )

        edge = self._edge_info(src, next_node)
        if edge is None:
            return self._route_frames(
                src, dst, actor, nodes_by_id, round_no=round_no, weather=weather,
                process_destination=False, avoid=avoid
            )
        if next_node in avoid:
            return float("inf")
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
            next_node, nodes_by_id, round_no + edge_frames, weather, round_no,
            actor
        )
        horse, horse_left = self._spend_horse_wait(
            horse, horse_left, process_frames
        )
        actor_at_next = self._actor_after_travel(
            actor, next_node, horse, horse_left, held
        )
        rest = self._route_frames(
            next_node, dst, actor_at_next, nodes_by_id, avoid=avoid,
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

    def _resource_claim_frames(
        self, node, resource_type, nodes_by_id=None, start_round=0, actor=None,
        weather_base_round=0
    ) -> int:
        frames = self._resource_claim_rounds.get((node, resource_type), RESOURCE_CLAIM_FRAMES)
        if nodes_by_id is None:
            return frames
        reduce = self._scout_process_reduce(
            node, nodes_by_id, actor, start_round, weather_base_round
        )
        return self._apply_scout_process_reduce(frames, reduce)

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

    def _process_frames(
        self, node, nodes_by_id, start_round, weather=None, weather_base_round=0,
        actor=None
    ) -> int:
        base = self._node_process_round(node, nodes_by_id)
        if base <= 0:
            return 0
        process_type = nodes_by_id.get(node, {}).get("processType")
        extra = self._weather_process_extra(process_type, start_round, weather, weather_base_round)
        frames = base + extra
        reduce = self._scout_process_reduce(
            node, nodes_by_id, actor, start_round, weather_base_round
        )
        return self._apply_scout_process_reduce(frames, reduce)

    def _node_process_round(self, node, nodes_by_id) -> int:
        if node in self.graph.process_rounds:
            return int(self.graph.process_rounds.get(node, 0) or 0)
        return int(nodes_by_id.get(node, {}).get("processRound", 0) or 0)

    def _verify_frames(self, actor, nodes_by_id, start_round, weather_base_round=0) -> int:
        reduce = self._scout_process_reduce(
            self.gate_node, nodes_by_id, actor, start_round, weather_base_round
        )
        return self._apply_scout_process_reduce(VERIFY_FRAMES, reduce)

    def _scout_process_reduce(
        self, node, nodes_by_id, actor=None, start_round=0, weather_base_round=0
    ) -> int:
        team_id = None
        if actor is not None:
            team_id = actor.get("teamId")
        if team_id is None:
            team_id = self._my_team
        if not team_id:
            return 0

        elapsed = max(0, int(start_round - weather_base_round))
        best = 0
        for marker in nodes_by_id.get(node, {}).get("scouted") or []:
            if marker.get("teamId") != team_id:
                continue
            if int(marker.get("remainingTriggers", 1) or 0) <= 0:
                continue
            remain = marker.get("remainRound")
            if remain is not None and int(remain or 0) <= elapsed:
                continue
            best = max(
                best,
                int(marker.get("processReduceRound", SCOUT_DEFAULT_PROCESS_REDUCE)
                    or SCOUT_DEFAULT_PROCESS_REDUCE)
            )
        return best

    @staticmethod
    def _apply_scout_process_reduce(frames: int, reduce: int) -> int:
        if frames <= 0 or reduce <= 0:
            return frames
        return min(frames, max(SCOUT_PROCESS_MIN_FRAMES, frames - reduce))

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
        card = self._window_card_choice(me, c)
        return [M.window_card(c["contestId"], card)]

    def _window_card_choice(self, me, contest) -> str:
        if self._freshness(me) < 80:
            if self._contest_points(contest)[0] >= 2:
                return "ABSTAIN"
            if me.get("guardActionPoint", 0) > 0:
                return "BING_ZHENG"
            return "ABSTAIN"
        # already won this contest 2-0 -> the 3rd tap is moot, save the card
        if contest.get("roundIndex") == 3 and self._contest_points(contest) == (2, 0):
            return "ABSTAIN"
        return pick_card(me, contest)

    @staticmethod
    def _freshness(me) -> float:
        try:
            return float(me.get("freshness", 100) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _contest_points(self, contest) -> tuple[int, int]:
        red = int(contest.get("redPoint", 0) or 0)
        blue = int(contest.get("bluePoint", 0) or 0)
        if contest.get("redPlayerId") == self.player_id:
            return red, blue
        return blue, red

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

    def _my_active_guards(self, nodes_by_id) -> set:
        return {
            nid for nid, n in nodes_by_id.items()
            if (g := n.get("guard")) and g.get("active") and g.get("defense", 0) > 0
            and g.get("ownerTeamId") == self._my_team
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
