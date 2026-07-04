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
DELIVER_MARGIN = 40          # safety frames before the delivery deadline; camp closer to
                             # the true extreme so a stalling opponent (who leaves after
                             # us) can't make their own 600-frame delivery
VERIFY_FRAMES = 6            # ~frames to VERIFY_GATE at the gate in RUSH
DELIVER_FRAMES = 2           # move-into-terminal + DELIVER
GUARD_KEEP_FRUIT = 6         # never spend guard fruit below this (keep some to deliver)
GUARD_SETUP_FRAMES = 5       # SET_GUARD read-bar (4) + activates next frame
TASK_TIME = 8                # rough frames a task claim+complete costs (spare-time gate)
RACE_SAFETY = 30             # only task pre-choke if we lead the race to it by > this
RACE_LEAD = 8                # min frame lead over the enemy at the choke to bother setting
                             # the S10 delay-guard (guard read-bar 4 + activate 1 + margin);
                             # below this the race is too close -> skip the guard, just go
OPP_SPEED = 1.25             # assume the opponent can use a fast horse (conservative:
                             # never overestimate our lead in the race to a choke)
# weather -> per-route-type move-cost multiplier (server config; only these slow moves;
# HOT only speeds freshness loss, no move effect)
WEATHER_ROUTE_MULT = {
    "HEAVY_RAIN": {"WATER": 1.35},
    "MOUNTAIN_FOG": {"MOUNTAIN": 1.10},
}
FREEZE_SAFETY = 2            # extra edge-frame margin so the guard is up before arrival
ICE_BOX = "ICE_BOX"
HORSES = ("FAST_HORSE", "SHORT_HORSE")   # move-buff resources (fast first)
OBSTACLE_PENALTY = 0         # routing cost of crossing an obstacle node: obstacles are
                             # squad-cleared in parallel now (near-free), so don't avoid
                             # them -- take the true shortest route (may use shortcuts)
XIAN_GONG_FLOOR = 1          # play XIAN_GONG whenever we can legally afford it (cost is
                             # 1 good fruit + freshness>=80): "能出就都出"; keep only a
                             # 1-fruit token so a tap never leaves us at zero good fruit
SQUAD_CLEAR_LEAD_HOPS = 2    # only pre-clear obstacles within this many hops ahead
                             # (just-in-time, per "别太早"): the immediate next-hop
                             # obstacle always qualifies (no wait-for-clear deadlock),
                             # while obstacles further along stay the squad's to defer
PROCESS_STUCK_LIMIT = 14     # if a process won't complete after this many tries (a
                             # co-occupation contest keeps blocking it), abandon it and
                             # move on -- delivery must never be held hostage to a process
OBSTACLE_WAIT_LIMIT = 8      # frames to wait for the squad to clear an obstacle ahead
                             # before the MAIN clears it itself -- never stall forever on
                             # an obstacle the squad didn't (or couldn't) clear

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
        self._weather_windows: list = []         # (route_mult, start_round, end_round)
        self._round = 0
        self._opp = None
        self._tasks: list = []
        self._stuck_node = None
        self._stuck_tries = 0
        self._obs_wait_node = None      # obstacle we're waiting on the squad to clear
        self._obs_wait_tries = 0
        self._last_forced_pass = -10   # round of our last FORCED_PASS (no two in a row)

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
        self._round = round_no
        self._opp = opp
        self._tasks = tasks
        self._ingest_weather(inquire_data.get("weather") or {}, round_no)

        if me.get("delivered") or me.get("retired"):
            return []

        # window card (XIAN_GONG when legal) + squad (obstacle clear) are SEPARATE
        # action quotas -- they ride alongside the main-car action.
        card = self._card(me, contests, round_no)
        squad = self._squad_action(node, me, opp, nodes_by_id)
        main = self._main_action(me, opp, node, state, phase, round_no, tasks, nodes_by_id)
        if opp is not None:  # remember opponent for next-frame "just committed" detection
            self._opp_prev_node = opp.get("currentNodeId")
            self._opp_prev_edge = opp.get("routeEdgeId")
        # main-car action FIRST in the request body (server-side ordering bug: a main
        # CLAIM_TASK must precede the window/squad entries), then the separate quotas.
        return main + card + squad

    # ---- main-car decision: one strict priority ladder ----
    def _main_action(self, me, opp, node, state, phase, round_no, tasks, nodes_by_id):
        """Goal: WE deliver, the opponent does NOT. Priority each frame:
          1. busy / mid-edge   -> let the engine run / keep moving (no node action)
          2. verified          -> committed to delivery: rush to the terminal
          3. delivery deadline -> our own precise ETA says leave now: rush to the gate
          4. blockade          -> camp the first common choke the opponent must cross;
                                  the instant they COMMIT onto its edge, SET_GUARD to
                                  freeze them mid-edge; else hold the choke
          5. otherwise         -> nothing to intercept: rush to the gate and deliver

        Leaving a choke happens ONLY via (3) our deadline or (4) after we've frozen it
        -- never otherwise. Tasks are the LOWEST priority: only while we are stationary
        ANYWAY (camping with the opponent still far, or the forced pre-RUSH gate wait)
        and only with genuine spare time; NEVER while advancing / rushing / on deadline.
        A task costs its own serial read-bar (it is never free)."""
        if state in BUSY_STATES:
            return []
        # mid-edge: SET_GUARD/PROCESS are forbidden while travelling -> just keep moving
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return [M.move(me["nextNodeId"])]

        # 2. committed to the delivery run -> finish it (rush, never task)
        if me.get("verified"):
            return self._advance_to(self.terminal_node, me, node, state, phase, nodes_by_id)

        # 3. our own delivery deadline (precise own ETA) -> rush to the gate (never task)
        if self._must_deliver(node, me, round_no):
            return self._advance_to(self.gate_node, me, node, state, phase, nodes_by_id)

        # 4. blockade-DELAY (set-and-go): race to the choke; the instant we're on it with
        # the required lead (RACE_LEAD, checked in _camp_choke), drop ONE guard to tax /
        # delay the enemy, then move straight on to scavenge + deliver. NO camping --
        # front-half speed buys back-half initiative. (A single guard can't seal on this
        # map -- the post-S10 branch + 2-guard cap defeat it -- so we don't try; we just
        # cost the enemy a forced-pass/weather delay and win on speed + score.)
        N = self._camp_choke(node, me, opp, nodes_by_id)
        if N is not None:
            if node != N:
                return self._advance_to(N, me, node, state, phase, nodes_by_id)  # RACE, no tasks
            # on the choke: drop the delay-guard only if we lead by >=RACE_LEAD (arm it
            # before the enemy arrives); else skip and move on to scavenge (race too close).
            if not self._we_hold(N, nodes_by_id) and self._lead_at(N, me, opp, nodes_by_id) >= RACE_LEAD:
                if self._first_guard_node is None:
                    self._first_guard_node = N
                self._guarded_round[N] = round_no
                return [M.set_guard(N, extra_good_fruit=self._guard_fruit(me))]
            # guard dropped (or race too close) -> fall through to deliver + scavenge

        # 5. no interception left -> SCAVENGE for score, then deliver. We have the back-
        # half initiative (front-half speed bought it): while there's delivery-margin
        # surplus, detour to the nearest claimable task and grab it; when nothing is
        # affordable (margin tight), run to the gate and deliver.
        tgt = self._scavenge_target(node, me, round_no, nodes_by_id)
        if tgt is not None and tgt != node:
            return self._advance_to(tgt, me, node, state, phase, nodes_by_id)
        if tgt == node:
            t = self._free_task_here(node, self._tasks, me)
            if t:
                return t
        if node == self.gate_node and phase != "RUSH":
            return [M.wait()]  # can't verify before RUSH
        return self._advance_to(self.gate_node, me, node, state, phase, nodes_by_id)

    def _camp_choke(self, node, me, opp, nodes_by_id):
        """The first (start-side) common choke the opponent must still cross that we
        don't already hold, haven't passed, AND can reach + arm a guard before the
        opponent does -- the one to race to and camp on. None when the opponent is
        walled off, past every choke, or already too close to any remaining choke for
        us to win the race (can't intercept -> stop chasing, go deliver)."""
        if opp is None or self._opp_walled_off(opp, nodes_by_id):
            return None
        for c in reversed(self.chokes):  # start-side first (the opponent hits it first)
            if self._we_hold(c, nodes_by_id) or not self._opp_must_cross(c, opp):
                continue
            # never backtrack to a choke we've already passed
            if node != c and self.graph.path_frames(node, self.gate_node, avoid={c}) != float("inf"):
                continue
            # ALWAYS race to it (front-half speed decides who camps vs gets frozen). Whether
            # we actually drop the delay-guard on arrival is the >=RACE_LEAD check in P4.
            return c
        return None

    def _lead_at(self, c, me, opp, nodes_by_id) -> float:
        """Frame lead over the opponent in reaching choke c (opp ETA - our ETA), horse-aware."""
        opp_node = opp.get("currentNodeId") if opp else None
        our_eta = self.graph.path_frames(me.get("currentNodeId"), c, speed=self._me_speed(me))
        opp_eta = self.graph.path_frames(opp_node, c, speed=self._opp_speed(opp, nodes_by_id)) \
            if opp_node else float("inf")
        return opp_eta - our_eta

    def _spare_for_task(self, node, me, opp, round_no, nodes_by_id) -> bool:
        """Do a task only with genuine spare time: it must not push us past our
        delivery deadline, and (before the blockade is secured) must not let the
        opponent reach the nearest choke we still need before we do."""
        # (a) delivery must survive the task's time cost
        if round_no + TASK_TIME + self._frames_to_deliver(node, me) + DELIVER_MARGIN >= TOTAL_ROUNDS:
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
            our_eta = self.graph.path_frames(node, c, speed=self._me_speed(me),
                                             weather_fn=self._wmult, base_round=round_no) + GUARD_SETUP_FRAMES
            # opponent speed informed by horse status; ETA weather-aware at traversal time
            opp_eta = self.graph.path_frames(opp_node, c, speed=self._opp_speed(opp, nodes_by_id),
                                             weather_fn=self._wmult, base_round=round_no) \
                if opp_node else float("inf")
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

    def _ingest_weather(self, weather, round_no) -> None:
        """Parse active + forecast weather into (route_mult, start, end) windows so we
        can look up the move multiplier for a route type at a future traversal round."""
        windows = []
        for a in weather.get("active", []):
            m = WEATHER_ROUTE_MULT.get(a.get("type"))
            if m:
                windows.append((m, round_no, round_no + int(a.get("remainRound", 0))))
        for f in weather.get("forecast", []):
            m = WEATHER_ROUTE_MULT.get(f.get("type"))
            if m:
                s = int(f.get("startRound", round_no))
                windows.append((m, s, s + int(f.get("durationRound", 0))))
        self._weather_windows = windows

    def _wmult(self, route_type, at_round) -> float:
        """Move-cost multiplier for a route type at a given (future) round."""
        mult = 1.0
        for m, start, end in self._weather_windows:
            if start <= at_round <= end and route_type in m:
                mult = max(mult, m[route_type])
        return mult

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

    def _has_horse_buff(self, player) -> bool:
        return any((b.get("type") or "").endswith("HORSE") or b.get("type") == "MOVE_BUFF"
                   for b in (player.get("buffs") or []))

    def _me_speed(self, me) -> float:
        """Our move multiplier: fast if we're horse-buffed or holding a horse to use."""
        if self._has_horse_buff(me):
            return OPP_SPEED
        res = me.get("resources") or {}
        return OPP_SPEED if any(res.get(h, 0) > 0 for h in HORSES) else 1.0

    def _opp_speed(self, opp, nodes_by_id) -> float:
        """Opponent move multiplier -- informed, not blindly conservative: fast only if
        they're horse-buffed, hold a horse, or can still grab one on their way; if we
        can see they have none and none is reachable, treat them as base speed."""
        if self._has_horse_buff(opp):
            return OPP_SPEED
        res = opp.get("resources") or {}
        if any(res.get(h, 0) > 0 for h in HORSES):
            return OPP_SPEED
        opp_node = opp.get("currentNodeId")
        path = self.graph.fastest_path(opp_node, self.gate_node) if opp_node else None
        for nid in (path or []):
            stock = nodes_by_id.get(nid, {}).get("resourceStock") or {}
            if any(stock.get(h, 0) > 0 for h in HORSES):
                return OPP_SPEED   # a horse still sits on their route -> could grab it
        return 1.0                 # provably no horse -> no need to be conservative

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
        path = self.graph.fastest_path(node, self.gate_node, obstacles=obstacles,
                                       obstacle_penalty=OBSTACLE_PENALTY) or []
        for i, nid in enumerate(path[1:], start=1):
            if nid in obstacles and nid not in self._squad_sent:
                # JUST-IN-TIME (per "别太早"): clear the obstacle only once it's within a
                # couple of hops. The immediate next-hop obstacle always qualifies, so we
                # never deadlock waiting on an un-dispatched clear; obstacles further out
                # are left for later (keeps the squad free for other uses).
                if i <= SQUAD_CLEAR_LEAD_HOPS:
                    self._squad_sent.add(nid)
                    return [M.squad_clear(nid)]
                break   # nearest obstacle still too far -> keep the squad free for now
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
        # mandatory fixed process at the node we're standing on: this is a forced STOP,
        # so grab a task here first IF we have genuine spare (task costs its own serial
        # read-bar -- never free -- so it's gated the same as anywhere else). During the
        # tight race to the choke _spare_for_task is False -> we just process and rush.
        # ANTI-STUCK (goal #1: we MUST deliver): if the process won't complete after
        # many tries (e.g. a co-occupation contest keeps blocking it), abandon it and
        # move on -- finishing the delivery outranks a process bonus.
        if self._needs_process(node, nodes_by_id) and node not in self.processed:
            if node != self._stuck_node:
                self._stuck_node, self._stuck_tries = node, 0
            self._stuck_tries += 1
            if self._stuck_tries > PROCESS_STUCK_LIMIT:
                self.processed.add(node)  # give up: keep moving so we still deliver
            else:
                if self._spare_for_task(node, me, self._opp, self._round, nodes_by_id):
                    t = self._free_task_here(node, self._tasks, me)
                    if t:
                        return t
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
        nxt = self.graph.fastest_hop(node, dest, avoid=avoid, obstacles=obstacles,
                                     obstacle_penalty=OBSTACLE_PENALTY,
                                     weather_fn=self._wmult, base_round=self._round) \
            or self.graph.fastest_hop(node, dest, obstacles=obstacles,
                                      obstacle_penalty=OBSTACLE_PENALTY,
                                      weather_fn=self._wmult, base_round=self._round)
        if not nxt:
            return []
        if nxt in self._guard_blocked:
            # ENEMY GUARD on the next hop. If we can reroute around it we already would
            # have (fastest_hop avoids _guard_blocked first); reaching here means it's on
            # a node we CAN'T avoid (a cut-vertex like S10) -> FORCED_PASS through it so we
            # never get blockaded to death. Two FORCED_PASSes in a row are rejected
            # (FORCED_PASS_REPEAT), so alternate with a single wait if we just did one.
            if self._last_forced_pass == self._round - 1:
                return [M.wait()]
            self._last_forced_pass = self._round
            return [M.forced_pass(nxt)]
        if nodes_by_id.get(nxt, {}).get("hasObstacle"):
            # The squad clears the obstacle in parallel (_squad_action) and we MOVE
            # through. But NEVER stall forever: if it isn't cleared after a short grace
            # (squad out of manpower, clearing a different path, or its dispatch was
            # rejected), the MAIN clears it itself so we always keep moving.
            if nxt != self._obs_wait_node:
                self._obs_wait_node, self._obs_wait_tries = nxt, 0
            self._obs_wait_tries += 1
            if self._obs_wait_tries > OBSTACLE_WAIT_LIMIT:
                return [M.clear(nxt)]
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

    def _scavenge_target(self, node, me, round_no, nodes_by_id):
        """Nearest node carrying a claimable task we can detour to, grab, and still
        deliver before the deadline. None when nothing is affordable -> go deliver."""
        best, best_f = None, float("inf")
        for t in self._tasks:
            if not t.get("active") or t.get("completed") or t.get("failed") or t.get("ownerPlayerId"):
                continue
            tn = t.get("nodeId")
            if not tn or tn == self.gate_node:
                continue
            f = self.graph.path_frames(node, tn)
            if f >= best_f or f == float("inf"):
                continue
            # affordable: reach it + claim + still deliver from there within the deadline
            if round_no + f + TASK_TIME + self._frames_to_deliver(tn, me) + DELIVER_MARGIN < TOTAL_ROUNDS:
                best, best_f = tn, f
        return best

    # ---- delivery-time safety ----
    def _must_deliver(self, node, me, round_no) -> bool:
        need = self._frames_to_deliver(node, me)
        return round_no + need + DELIVER_MARGIN >= TOTAL_ROUNDS

    def _frames_to_deliver(self, node, me) -> float:
        # OUR OWN precise ETA to deliver -- deterministic, no opponent, no weather guess
        # (per design: the "can we still make it" deadline is about us only).
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
