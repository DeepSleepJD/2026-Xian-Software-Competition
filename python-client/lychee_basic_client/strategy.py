"""Strategy (feature/blockade-strategy) -- clean rewrite.

Doc: see 策略与注意点.md.  One-line model: score = freshness(<=180) + goodFruit(<=180)
+ task(<=180) + deliveryBase + time(<=90).  So we optimise for: deliver FAST & fresh,
keep good fruit, grab tasks up to the cap -- and if we can seal the opponent (true/pseudo
choke), that's a bonus that buys us uncontested scavenge time.

Phase machine (main car), highest priority first:
  BUSY / MID-EDGE -> let the engine run / keep moving (no node action)
  VERIFIED        -> committed to delivery: rush to the terminal, ice, DELIVER
  DEADLINE        -> our own precise ETA says leave now: rush to the gate
  RACE            -> race (fast, no detours) to the first true choke the opponent must cross
  AT-CHOKE        -> if we lead by >= RACE_LEAD, drop a delay guard (set-and-go); else move on
  SCORE           -> scavenge tasks/ice within the delivery budget, then deliver

Robustness (never stall, always deliver): break past an enemy guard on an unavoidable
node (FORCED_PASS, no two in a row); self-clear an obstacle the squad didn't clear in
time (T04 -> CLAIM_TASK for +30, else CLEAR); abandon a process that won't complete.
"""
import math
from typing import Any, Optional

from . import messages as M
from .contest import active_contest, pick_card
from .graph import Graph

TOTAL_ROUNDS = 600
DELIVER_MARGIN = 40          # safety frames kept before the 600-frame delivery deadline
VERIFY_FRAMES = 6            # ~frames to VERIFY_GATE (RUSH)
DELIVER_FRAMES = 2           # move-into-terminal + DELIVER
GUARD_KEEP_FRUIT = 6         # keep >= this many good fruit for a guard's bonus / delivery
GUARD_SETUP_FRAMES = 5       # SET_GUARD read-bar (4) + activates next frame
RACE_LEAD = 8                # min frame lead at a choke to bother dropping the delay guard
TASK_TIME = 8                # rough frames a task claim costs (its own read-bar, never free)
OPP_SPEED = 1.25             # a horse-capable opponent's speed (conservative ETA)
WEATHER_ROUTE_MULT = {       # weather -> per-route move-cost multiplier (only these slow moves)
    "HEAVY_RAIN": {"WATER": 1.35},
    "MOUNTAIN_FOG": {"MOUNTAIN": 1.10},
}
ICE_BOX = "ICE_BOX"
HORSES = ("FAST_HORSE", "SHORT_HORSE")   # move-buff resources (fast first)
# horse -> (frame multiplier <1 = faster, buff duration in rounds)
HORSE_BUFF = {"FAST_HORSE": (0.80, 20), "SHORT_HORSE": (0.85, 14)}
RESOURCE_CLAIM_FRAMES = 4    # ~read-bar to CLAIM_RESOURCE a horse en route
RESOURCE_USE_FRAMES = 1      # ~to USE a held horse
TASK_ROUTE_CAP = 130         # routeTaskScore beyond which task score is already maxed
                             # (130 + milestones 15/20/15 = 180 cap): stop grabbing tasks,
                             # spend the time on freshness / faster delivery instead
OBSTACLE_PENALTY = 0         # obstacles are squad-cleared in parallel -> don't route around them
XIAN_GONG_FLOOR = 1          # play XIAN_GONG whenever legally affordable (keep 1 fruit token)
SQUAD_CLEAR_LEAD_HOPS = 2    # only pre-clear obstacles within this many hops ahead
PROCESS_STUCK_LIMIT = 14     # abandon a process that won't complete after this many tries
OBSTACLE_WAIT_LIMIT = 8      # wait this long for the squad to clear, then self-clear
START_OBSTACLE_CLEAR_FRAMES = 6   # main CLEAR/T04 read-bar (used as the T04 processRound gate)

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
        self._first_guard_node: Optional[str] = None
        self._opp_prev_node: Optional[str] = None
        self._opp_prev_edge: Optional[str] = None
        self._guarded_round: dict[str, int] = {}
        self._squad_sent: set[str] = set()
        self._scout_sent: set[str] = set()
        self._guard_blocked: set[str] = set()
        self.route_avoid: set[str] = set()
        self._weather_windows: list = []
        self._round = 0
        self._opp = None
        self._tasks: list = []
        self._stuck_node: Optional[str] = None
        self._stuck_tries = 0
        self._obs_wait_node: Optional[str] = None
        self._obs_wait_tries = 0
        self._last_forced_pass = -10
        self._route_task_score = 0   # our cumulative routeTaskScore (from TASK_COMPLETE)

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
        # true chokes (cut-vertices) the opponent must cross, nearest the gate first
        self.chokes = self.graph.choke_points(self.start_node, self.gate_node)

    # ---- per-frame entry ----
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
        # weather is intentionally NOT used in routing (unpredictable at route time -- if we
        # hit bad weather that's just bad luck; modelling it added churn without a clear win).

        if me.get("delivered") or me.get("retired"):
            return []

        # window card + squad ride alongside the main-car action (separate quotas).
        card = self._card(me, contests, round_no)
        squad = self._squad_action(node, me, opp, nodes_by_id)
        main = self._main_action(me, opp, node, state, phase, round_no, tasks, nodes_by_id)
        if opp is not None:
            self._opp_prev_node = opp.get("currentNodeId")
            self._opp_prev_edge = opp.get("routeEdgeId")
        # main-car FIRST in the request body (server CLAIM_TASK ordering bug), then quotas.
        return main + card + squad

    # ================= main-car phase machine =================
    def _main_action(self, me, opp, node, state, phase, round_no, tasks, nodes_by_id):
        if state in BUSY_STATES:
            return []
        # MID-EDGE: node actions are forbidden while travelling -> just keep moving.
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return [M.move(me["nextNodeId"])]

        # VERIFIED -> finish the delivery run (rush, never scavenge).
        if me.get("verified"):
            return self._advance_to(self.terminal_node, me, node, state, phase, nodes_by_id)

        # DEADLINE -> our own precise ETA says we must leave now to still deliver.
        if self._must_deliver(node, me, round_no):
            return self._advance_to(self.gate_node, me, node, state, phase, nodes_by_id)

        # RACE / AT-CHOKE -> the first true choke the opponent must still cross that we
        # haven't passed. Race there fast (no scavenge detour); on arrival, drop a delay
        # guard only if we lead by >= RACE_LEAD (own guards don't block us; opponent must
        # FORCED_PASS it -> time tax / can't cheap-detour).
        N = self._race_choke(node, opp, nodes_by_id)
        if N is not None:
            if node != N:
                return self._advance_to(N, me, node, state, phase, nodes_by_id)
            if not self._we_hold(N, nodes_by_id) and self._lead_at(N, me, opp, nodes_by_id) >= RACE_LEAD:
                self._first_guard_node = self._first_guard_node or N
                self._guarded_round[N] = round_no
                return [M.set_guard(N, extra_good_fruit=self._guard_fruit(me))]
            # race too close / already held -> fall through to SCORE

        # SCORE -> convert our time lead into points: scavenge the nearest affordable task,
        # else run to the gate and deliver (ice-box on arrival keeps freshness high).
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

    def _race_choke(self, node, opp, nodes_by_id):
        """First (start-side) true choke the opponent must still cross that we don't hold
        and haven't passed -- always race to it. None -> nothing to intercept -> SCORE."""
        if opp is None or self._opp_walled_off(opp, nodes_by_id):
            return None
        for c in reversed(self.chokes):
            if self._we_hold(c, nodes_by_id) or not self._opp_must_cross(c, opp):
                continue
            if node != c and self.graph.path_frames(node, self.gate_node, avoid={c}) != float("inf"):
                continue  # already passed it
            return c
        return None

    # ================= navigation =================
    def _advance_to(self, dest, me, node, state, phase, nodes_by_id):
        if state in BUSY_STATES:
            return []
        if node == dest:
            return self._arrive(dest, me, phase, nodes_by_id)
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return [M.move(me["nextNodeId"])]
        if node == self.gate_node and not me.get("verified"):
            return self._arrive(self.gate_node, me, phase, nodes_by_id)
        # mandatory process at this node (forced stop) -- grab a task here if we have spare;
        # anti-stuck: abandon a process that won't complete (co-occupation contest).
        if self._needs_process(node, nodes_by_id) and node not in self.processed:
            if node != self._stuck_node:
                self._stuck_node, self._stuck_tries = node, 0
            self._stuck_tries += 1
            if self._stuck_tries > PROCESS_STUCK_LIMIT:
                self.processed.add(node)
            else:
                if self._route_task_score < TASK_ROUTE_CAP \
                        and self._spare_for_task(node, me, self._opp, self._round, nodes_by_id):
                    t = self._free_task_here(node, self._tasks, me)
                    if t:
                        return t
                return [M.process(node)]
        # grab/mount a horse to win the race (and deny it to the opponent).
        horse = self._horse_action(me, node, nodes_by_id)
        if horse:
            return horse
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        avoid = self._guard_blocked | self.route_avoid
        nxt = self.graph.fastest_hop(node, dest, avoid=avoid, obstacles=obstacles,
                                     obstacle_penalty=OBSTACLE_PENALTY) \
            or self.graph.fastest_hop(node, dest, obstacles=obstacles,
                                      obstacle_penalty=OBSTACLE_PENALTY)
        if not nxt:
            return []
        # ENEMY GUARD on an unavoidable next hop -> break through (single FORCED_PASS; two
        # in a row are rejected, so alternate with a wait). Never blockaded to death.
        if nxt in self._guard_blocked:
            if self._last_forced_pass == self._round - 1:
                return [M.wait()]
            self._last_forced_pass = self._round
            return [M.forced_pass(nxt)]
        # OBSTACLE on the next hop -> the squad clears in parallel; but never stall: after a
        # short grace the MAIN clears it (T04 -> CLAIM_TASK for +30, else CLEAR).
        if nodes_by_id.get(nxt, {}).get("hasObstacle"):
            if nxt != self._obs_wait_node:
                self._obs_wait_node, self._obs_wait_tries = nxt, 0
            self._obs_wait_tries += 1
            if self._obs_wait_tries > OBSTACLE_WAIT_LIMIT:
                t04 = self._t04_task(nxt)
                return [M.claim_task(t04)] if t04 else [M.clear(nxt)]
            return [M.wait()]
        return [M.move(nxt)]

    def _arrive(self, dest, me, phase, nodes_by_id):
        if dest == self.terminal_node or me.get("currentNodeId") == self.terminal_node:
            if not me.get("verified"):
                return [M.move(self.gate_node)]
            # freshness scores (<=180): top it up with a held ICE_BOX before delivering.
            if (me.get("resources", {}) or {}).get(ICE_BOX, 0) > 0 and me.get("freshness", 100) < 100:
                return [M.use_resource(ICE_BOX)]
            return [M.deliver()]
        if dest == self.gate_node:
            if me.get("verified"):
                return [M.move(self.terminal_node)]
            if phase == "RUSH":
                return [M.verify_gate()]
            return [M.wait()]
        return []

    # ================= squad (separate quota): clear + scout =================
    def _squad_action(self, node, me, opp, nodes_by_id) -> list:
        avail = me.get("squadAvailable", 0)
        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        path = self.graph.fastest_path(node, self.gate_node, obstacles=obstacles,
                                       obstacle_penalty=OBSTACLE_PENALTY) or []
        # 1) just-in-time obstacle clear (2 manpower) within a couple of hops. Leave a T04
        # obstacle for the MAIN to CLAIM (it scores 30; a squad clear would forfeit it).
        if avail >= 2:
            for i, nid in enumerate(path[1:], start=1):
                if nid in obstacles and nid not in self._squad_sent:
                    if self._t04_task(nid):
                        continue
                    if i <= SQUAD_CLEAR_LEAD_HOPS:
                        self._squad_sent.add(nid)
                        return [M.squad_clear(nid)]
                    break
        # 2) scout the next un-scouted process/claim node ahead (1 manpower) -> cuts its
        # process/claim time by 3 for 45 rounds: speeds the race and the scavenge.
        if avail >= 1:
            for nid in path[1:]:
                if nid in self._scout_sent or nid == self.gate_node:
                    continue
                if self._needs_process(nid, nodes_by_id) or self._free_task_here(nid, self._tasks, me):
                    self._scout_sent.add(nid)
                    return [M.squad_scout(nid)]
        return []

    # ================= score / scavenge =================
    def _scavenge_target(self, node, me, round_no, nodes_by_id):
        """Nearest node with a claimable task we can detour to, grab, and still deliver in
        time. None -> nothing affordable -> go deliver (fast delivery scores freshness+time)."""
        # cap-aware: once our routeTaskScore maxes the task cap, more tasks score 0 -> stop
        # scavenging and spend the time on freshness / faster delivery instead.
        if self._route_task_score >= TASK_ROUTE_CAP:
            return None
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
            if round_no + f + TASK_TIME + self._frames_to_deliver(tn, me) + DELIVER_MARGIN < TOTAL_ROUNDS:
                best, best_f = tn, f
        return best

    def _free_task_here(self, node, tasks, me):
        for t in tasks:
            if t.get("nodeId") == node and t.get("active") and not t.get("completed") \
               and not t.get("failed") and not t.get("ownerPlayerId"):
                return [M.claim_task(t["taskId"])]
        return None

    def _t04_task(self, nid):
        """taskId of a claimable T04 (CLEAR_OBSTACLE) task on this obstacle node -- claiming
        it clears the obstacle AND scores 30 (a plain CLEAR / squad clear would forfeit it)."""
        for t in self._tasks:
            if t.get("nodeId") != nid or not t.get("active") \
               or t.get("completed") or t.get("failed") or t.get("ownerPlayerId"):
                continue
            if t.get("processType") != "CLEAR_OBSTACLE" and t.get("taskTemplateId") != "T04":
                continue
            if int(t.get("processRound", START_OBSTACLE_CLEAR_FRAMES)) <= START_OBSTACLE_CLEAR_FRAMES:
                return t.get("taskId")
        return None

    def _spare_for_task(self, node, me, opp, round_no, nodes_by_id) -> bool:
        """Task only with genuine spare: it must not miss our delivery deadline nor lose
        us the race to a choke the opponent must still cross."""
        if round_no + TASK_TIME + self._frames_to_deliver(node, me) + DELIVER_MARGIN >= TOTAL_ROUNDS:
            return False
        if opp is None:
            return True
        opp_node = opp.get("currentNodeId")
        for c in reversed(self.chokes):
            if self._we_hold(c, nodes_by_id) or not self._opp_must_cross(c, opp):
                continue
            if node != c and self.graph.path_frames(node, self.gate_node, avoid={c}) != float("inf"):
                continue
            our_eta = self._eta(me, c, nodes_by_id, "slow") + GUARD_SETUP_FRAMES
            opp_eta = self._eta(opp, c, nodes_by_id, "fast")
            return opp_eta - our_eta > TASK_TIME + RACE_LEAD
        return True

    # ================= horse =================
    def _horse_action(self, me, node, nodes_by_id):
        res = me.get("resources") or {}
        buffed = self._has_horse_buff(me)
        held = [h for h in HORSES if res.get(h, 0) > 0]
        if not buffed and held:
            return [M.use_resource(held[0])]
        if not buffed and not held:
            stock = nodes_by_id.get(node, {}).get("resourceStock") or {}
            for h in HORSES:
                if stock.get(h, 0) > 0:
                    return [M.claim_resource(node, h)]
        return None

    def _has_horse_buff(self, player) -> bool:
        return any((b.get("type") or "").endswith("HORSE") or b.get("type") == "MOVE_BUFF"
                   for b in (player.get("buffs") or []))

    def _active_buff(self, actor):
        """Active move-buff as (frame_mult<1, rounds_left); (1.0, 0) if none."""
        for b in actor.get("buffs") or []:
            t = (b.get("type") or "")
            if t.endswith("HORSE") or t == "MOVE_BUFF":
                hb = HORSE_BUFF.get(t) or HORSE_BUFF.get(t.replace("_BUFF", ""))
                mult = hb[0] if hb else 0.85
                rem = b.get("remainRound", b.get("remainRounds"))
                return (mult, int(rem) if rem is not None else 8)
        return (1.0, 0)

    @staticmethod
    def _held_horse(actor):
        res = actor.get("resources") or {}
        for h in HORSES:
            if res.get(h, 0) > 0:
                return h
        return None

    @staticmethod
    def _stock_horse(node, nodes_by_id):
        stock = nodes_by_id.get(node, {}).get("resourceStock") or {}
        for h in HORSES:
            if stock.get(h, 0) > 0:
                return h
        return None

    # ================= ETA (horse-pickup aware; mode = slow|fast) =================
    def _eta(self, actor, dst, nodes_by_id, mode) -> float:
        """Frames for `actor` to travel to `dst`, modelling the move-buff (held horse, and
        in FAST mode horses grabbed en route, with their limited buff window).
          mode="slow": only the actor's CERTAIN speed (held/active horse) -- for OUR
                       safety judgments (deadline / do-I-win-the-race), never overpromise.
          mode="fast": also grab horses sitting on the route -- for OUR route choice and
                       for the OPPONENT (never underestimate them)."""
        if actor is None:
            return float("inf")
        node = actor.get("currentNodeId")
        if not node:
            return float("inf")
        if node == dst:
            return 0.0
        path = self.graph.fastest_path(node, dst)
        if not path or len(path) < 2:
            return float("inf")
        mult, left = self._active_buff(actor)
        held = None if left > 0 else self._held_horse(actor)
        total = 0.0
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            if left <= 0 and i == 0 and held:                 # use our held horse now
                mult, left = HORSE_BUFF[held]; total += RESOURCE_USE_FRAMES; held = None
            if left <= 0 and mode == "fast":                  # grab a horse on the route
                h = self._stock_horse(a, nodes_by_id)
                if h:
                    mult, left = HORSE_BUFF[h]; total += RESOURCE_CLAIM_FRAMES + RESOURCE_USE_FRAMES
            ef = self.graph.edge_frames(a, b) or 0
            if left > 0:
                buffed = ef * mult
                if left >= buffed:
                    total += buffed; left -= buffed
                else:                                         # buff runs out mid-edge
                    base_covered = left / mult
                    total += left + max(0.0, ef - base_covered); left = 0.0
            else:
                total += ef
            total += self.graph.process_rounds.get(b, 0)
        return total

    # ================= choke / ETA helpers =================
    def _lead_at(self, c, me, opp, nodes_by_id) -> float:
        # our safety: slow/conservative; opponent: fast (don't underestimate them).
        our_eta = self._eta(me, c, nodes_by_id, "slow")
        opp_eta = self._eta(opp, c, nodes_by_id, "fast") if opp else float("inf")
        return opp_eta - our_eta

    def _opp_must_cross(self, node, opp) -> bool:
        if opp is None:
            return False
        opp_node = opp.get("currentNodeId")
        if not opp_node:
            return True
        return self.graph.path_frames(opp_node, self.gate_node, avoid={node}) == float("inf")

    def _we_hold(self, node, nodes_by_id) -> bool:
        g = nodes_by_id.get(node, {}).get("guard") or {}
        return bool(g.get("active") and g.get("ownerTeamId") == self._my_team and g.get("defense", 0) > 0)

    def _opp_walled_off(self, opp, nodes_by_id) -> bool:
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
        return bool(my_guards) and self.graph.path_frames(opp_node, self.gate_node, avoid=my_guards) == float("inf")

    def _guard_fruit(self, me) -> int:
        return max(0, min(2, me.get("goodFruit", 0) - GUARD_KEEP_FRUIT))

    # ================= delivery deadline (our own precise ETA, no weather guess) =================
    def _must_deliver(self, node, me, round_no) -> bool:
        return round_no + self._frames_to_deliver(node, me) + DELIVER_MARGIN >= TOTAL_ROUNDS

    def _frames_to_deliver(self, node, me) -> float:
        to_gate = 0 if me.get("verified") else self.graph.path_frames(node, self.gate_node)
        verify = 0 if me.get("verified") else VERIFY_FRAMES
        start = self.gate_node if not me.get("verified") else node
        to_term = self.graph.path_frames(start, self.terminal_node)
        return to_gate + verify + to_term + DELIVER_FRAMES

    # ================= cards (window contest) =================
    def _card(self, me, contests, round_no):
        c = active_contest(self.player_id, contests, round_no)
        if c is None:
            return []
        tap = (c.get("contestId"), c.get("roundIndex"))
        if tap in self._contest_played:
            return []
        self._contest_played.add(tap)
        card = pick_card(me, c)
        # XIAN_GONG (献贡): strongest single card; play whenever legally affordable.
        if me.get("freshness", 0) >= 80 and me.get("goodFruit", 0) > XIAN_GONG_FLOOR:
            card = "XIAN_GONG"
        return [M.window_card(c["contestId"], card)]

    # ================= weather =================
    def _ingest_weather(self, weather, round_no) -> None:
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
        mult = 1.0
        for m, start, end in self._weather_windows:
            if start <= at_round <= end and route_type in m:
                mult = max(mult, m[route_type])
        return mult

    # ================= misc =================
    def _needs_process(self, node, nodes_by_id) -> bool:
        if node in (self.gate_node, self.terminal_node):
            return False
        return nodes_by_id.get(node, {}).get("processRound", 0) > 0 or node in self.graph.process_rounds

    def _account_process(self, events) -> None:
        for e in events:
            et = e.get("type")
            pl = e.get("payload") or {}
            if pl.get("playerId") != self.player_id:
                continue
            if et == "PROCESS_COMPLETE" and pl.get("targetNodeId"):
                self.processed.add(pl["targetNodeId"])
            elif et == "TASK_COMPLETE":
                # taskScore is cumulative in the payload; track the running total.
                self._route_task_score = max(self._route_task_score, int(pl.get("taskScore", 0)))

    def _enemy_guards(self, nodes_by_id) -> set:
        return {
            nid for nid, n in nodes_by_id.items()
            if (g := n.get("guard")) and g.get("active") and g.get("defense", 0) > 0
            and g.get("ownerTeamId") not in (None, self._my_team)
        }

    @staticmethod
    def _find(players, pid):
        return next((p for p in players if p.get("playerId") == pid), None)

    def _find_other(self, players):
        return next((p for p in players if p.get("playerId") != self.player_id), None)
