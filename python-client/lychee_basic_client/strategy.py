"""Decision logic: navigate S01 -> ... -> S14 (verify) -> S15 (deliver)."""
import math
from typing import Any, Optional

from . import messages as M
from .contest import active_contest, pick_card
from .graph import Graph

# main-car states where we are busy and should just let the engine run
BUSY_STATES = {"PROCESSING", "VERIFYING", "FORCED_PASSING", "RESTING", "CONTESTING"}

# Task base to chase: 90 fills the delivery/time bonus, 110 the top milestone;
# a bit past that (task score caps at 180) still turns cheap on-route tasks into
# points, and we have a lot of idle slack before the gate opens at rush.
TASK_BASE_TARGET = 150
# T06 (争马换乘) burns a horse on claim; skip unless we hold one.
HORSE_KEYS = ("FAST_HORSE", "SHORT_HORSE")
# Ice box raises delivery freshness (freshness score = floor(fresh/100*180)).
# Grab a few on-route and spend them right before delivery to lock in freshness.
ICE_BOX = "ICE_BOX"
# Resources worth stocking on-route (no detour), with a per-type cap.
# Ice box -> freshness; documents -> YAN_DIE ammo for gate/task windows.
STOCK_TARGETS = {
    ICE_BOX: 3,
    "PASS_TOKEN": 2,
    "OFFICIAL_PERMIT": 2,
}
# waypoint (orienteering) tuning
FRESH_SCORE_PER_POINT = 1.8   # freshness/goodfruit score per 1 freshness point
ICE_GAIN_SCORE = 18.0         # ~ +10 freshness locked at delivery (10 * 1.8)
WAYPOINT_MIN_NET = 8.0        # only detour when net score gain clears this


class Strategy:
    def __init__(self, player_id: int) -> None:
        self.player_id = player_id
        self.graph = Graph()
        self.gate_node = "S14"
        self.terminal_node = "S15"
        self.start_node = "S01"
        # nodes whose mandatory fixed-process we have already completed this run
        self.processed: set[str] = set()
        # per-node bookkeeping so we can tell "process finished" from "not started yet"
        self._saw_processing_at: Optional[str] = None
        # task accounting
        self.task_base = 0                       # sum of scores of tasks we completed
        self._counted_tasks: set[str] = set()    # taskIds already added to task_base
        self._task_attempts: dict[str, int] = {}  # per-task claim attempts (loop guard)
        # nodes an enemy guard is blocking us from entering (detected reactively)
        self._guard_blocked: set[str] = set()
        self._last_move_target: Optional[str] = None
        # obstacle nodes we've already sent a squad to clear (avoid re-dispatch)
        self._squad_clear_sent: set[str] = set()

    # ---- setup from the start message ----
    def ingest_start(self, start_data: dict[str, Any]) -> None:
        m = start_data.get("map", {})
        edges = start_data.get("edges") or m.get("edges") or []
        self.graph.load_edges(edges)
        roles = m.get("gameplay", {}).get("roles", {})
        self.gate_node = roles.get("gateNodeId", "S14")
        self.start_node = roles.get("startNodeId", "S01")
        terminals = roles.get("terminalNodeIds") or ["S15"]
        self.terminal_node = terminals[0]
        process_nodes = m.get("gameplay", {}).get("processNodes", [])
        self.graph.load_process_nodes(process_nodes, self.gate_node)

    # ---- per-frame decision ----
    def decide(self, inquire_data: dict[str, Any]) -> list[dict[str, Any]]:
        # refresh edges each frame in case adjacency is only exposed via inquire
        edges = inquire_data.get("edges")
        if edges:
            # keep process rounds; only rebuild adjacency
            proc = self.graph.process_rounds
            self.graph.load_edges(edges)
            self.graph.process_rounds = proc

        me = self._find_me(inquire_data.get("players", []))
        if me is None:
            return []

        state = me.get("state", "IDLE")
        node = me.get("currentNodeId") or ""
        phase = inquire_data.get("phase", "NORMAL")
        round_no = inquire_data.get("round", 0)
        tasks = inquire_data.get("tasks", [])
        contests = inquire_data.get("contests", [])
        nodes_by_id = {n["nodeId"]: n for n in inquire_data.get("nodes", [])}

        self._account_tasks(tasks)
        self._note_blocked_moves(inquire_data.get("actionResults", []), nodes_by_id)

        if me.get("delivered") or me.get("retired"):
            return []

        main = self._main_action(me, state, node, phase, round_no, tasks, contests, nodes_by_id)
        # a squad action is a separate category, so it can ride alongside the main
        # action: use it to pre-clear an upcoming road obstacle so the main car
        # never has to FORCED_PASS (saves the time tax and dodges the consecutive-
        # obstacle FORCED_PASS_REPEAT dead-lock). Squads are otherwise unused.
        squad = self._squad_action(node, nodes_by_id, me, phase)
        return main + ([squad] if squad else [])

    def _main_action(
        self,
        me: dict[str, Any],
        state: str,
        node: str,
        phase: str,
        round_no: int,
        tasks: list[dict[str, Any]],
        contests: list[dict[str, Any]],
        nodes_by_id: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Main-car / window action for this frame."""
        # play any window we're a party to first -- otherwise we abstain and lose
        # the contested object. Must precede the busy check so a forced-pass
        # attacker (state FORCED_PASSING) still plays its PASS window.
        contest = active_contest(self.player_id, contests)
        if contest is not None:
            return [M.window_card(contest["contestId"], pick_card(me, contest))]

        # travelling on an edge: keep pushing toward the current target end.
        # NB: WAITING while parked on a node is NOT travelling -> fall through.
        on_edge = state == "MOVING" or (state == "WAITING" and me.get("routeEdgeId"))
        if on_edge:
            self._saw_processing_at = None
            self._guard_blocked.discard(node)  # we're moving, no longer blocked here
            target = me.get("nextNodeId") or self.graph.next_hop(node, self.gate_node)
            return [self._mv(target)] if target else []

        # busy finishing something server-side: don't interrupt
        if state in BUSY_STATES:
            if state == "PROCESSING":
                self._saw_processing_at = node
            return []

        # here state is IDLE / WAITING-on-node / COST_BANKRUPT: pick a fresh action

        # at terminal: verify done -> deliver
        if node == self.terminal_node:
            if me.get("verified"):
                return [M.deliver()]
            # shouldn't normally get here before verifying; step back to the gate
            return [self._mv(self.gate_node)]

        # at gate: verify (rush only), then step into terminal.
        # The gate is a shared object: if the opponent is verifying it we get
        # OBJECT_BUSY, so just keep retrying until it frees (no penalty).
        if node == self.gate_node:
            if me.get("verified"):
                # spend ice boxes here (freshness is locked in at delivery, and
                # S15 only allows wait/deliver/return) then step into the terminal
                if me.get("resources", {}).get(ICE_BOX, 0) > 0 and me.get("freshness", 100) < 100:
                    return [M.use_resource(ICE_BOX)]
                return [self._mv(self.terminal_node)]
            if phase == "RUSH":
                # spend our one rush tactic on 护果令 (RUSH_PROTECT) here, before
                # verifying: it cuts freshness loss to x0.2 for 30 frames, which
                # covers verify + the hop to S15 + delivery (and the 4th weather
                # window at 440-480, often 酷暑 x1.5). It costs no fruit and speed
                # tactics are useless to us (delivery is gated by the rush frame).
                if me.get("rushTacticUsedCount", 0) == 0 and me.get("freshness", 100) < 100:
                    return [M.rush_protect()]
                return [M.verify_gate()]
            return []  # wait for the rush phase to open the gate

        # mandatory fixed-process node not yet cleared this visit -> finish it first
        if node in self.graph.process_rounds and node not in self.processed:
            if self._saw_processing_at == node:
                # we were PROCESSING here and are IDLE again -> finished
                self.processed.add(node)
                self._saw_processing_at = None
            else:
                return [M.process()]

        # opportunistic: grab an on-route imperial task at this node
        task = self._claimable_task_here(node, tasks, me, round_no)
        if task is not None:
            tid = task["taskId"]
            self._task_attempts[tid] = self._task_attempts.get(tid, 0) + 1
            return [M.claim_task(tid)]

        # opportunistic: stock useful resources this node has (no detour)
        res = self._resource_to_claim(node, nodes_by_id, me)
        if res is not None:
            return [M.claim_resource(node, res)]

        # head toward the best worth-it task/ice waypoint, else straight to the gate
        dest = self._best_waypoint(node, nodes_by_id, tasks, me, round_no)
        return self._advance(node, nodes_by_id, dest)

    def _resource_to_claim(
        self, node: str, nodes_by_id: dict[str, Any], me: dict[str, Any]
    ) -> Optional[str]:
        """A useful resource in stock here that we're still under our cap on
        (ice box prioritised over window-card documents), else None."""
        stock = nodes_by_id.get(node, {}).get("resourceStock", {}) or {}
        held = me.get("resources", {}) or {}
        for rtype, cap in STOCK_TARGETS.items():
            if stock.get(rtype, 0) > 0 and held.get(rtype, 0) < cap:
                return rtype
        return None

    def _account_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Tally task-base from tasks the engine reports as completed by us."""
        for t in tasks:
            tid = t.get("taskId")
            if (
                t.get("completed")
                and t.get("ownerPlayerId") == self.player_id
                and tid not in self._counted_tasks
            ):
                self._counted_tasks.add(tid)
                self.task_base += int(t.get("score", 0))

    def _squad_action(
        self, node: str, nodes_by_id: dict[str, Any], me: dict[str, Any], phase: str
    ) -> Optional[dict[str, Any]]:
        """Send a squad to pre-clear the nearest not-yet-handled road obstacle on
        our path to the gate. SQUAD_CLEAR costs 2 members, lands after a delay and
        (unlike main-car CLEAR) opens no contest window, so it's a safe way to make
        the obstacle gone before the main car gets there. New squads are barred once
        the rush phase starts."""
        if phase != "NORMAL" or me.get("squadAvailable", 0) < 2:
            return None
        for w in self.graph.shortest_path(node, self.gate_node) or []:
            if w == node or w in self._squad_clear_sent:
                continue
            if nodes_by_id.get(w, {}).get("hasObstacle"):
                self._squad_clear_sent.add(w)
                return M.squad_clear(w)
        return None

    def _task_claimable(self, t: dict[str, Any], me: dict[str, Any], round_no: int) -> bool:
        """Whether task instance t is one we could go and complete (ignoring where we
        currently stand)."""
        if not t.get("active") or t.get("completed") or t.get("failed"):
            return False
        if t.get("ownerPlayerId", 0) not in (0, self.player_id):
            return False
        if t.get("protectionPlayerId", 0) not in (0, self.player_id):
            return False  # window-protected for the opponent
        expire = t.get("expireRound", 0)
        if expire and round_no >= expire:
            return False
        if t.get("taskTemplateId") == "T06":
            if sum(me.get("resources", {}).get(k, 0) for k in HORSE_KEYS) <= 0:
                return False  # needs a horse to claim
        if self._task_attempts.get(t.get("taskId"), 0) >= 3:
            return False  # give up after repeated rejects (loop guard)
        return True

    def _claimable_task_here(
        self, node: str, tasks: list[dict[str, Any]], me: dict[str, Any], round_no: int
    ) -> Optional[dict[str, Any]]:
        """Highest-value imperial task claimable at the current node, or None."""
        if self.task_base >= TASK_BASE_TARGET:
            return None
        best = None
        for t in tasks:
            if t.get("nodeId") != node or not self._task_claimable(t, me, round_no):
                continue
            if best is None or int(t.get("score", 0)) > int(best.get("score", 0)):
                best = t
        return best

    def _task_value(self, t: dict[str, Any]) -> float:
        """Score value of completing t now, weighting tasks below 90 base higher
        because they also unlock the delivery base and time score."""
        s = float(t.get("score", 0))
        if self.task_base < 90:
            return s * 2.5  # also lifts delivery (x4/3) + unlocks time score
        if self.task_base < TASK_BASE_TARGET:
            return s
        return 0.0

    def _best_waypoint(
        self,
        node: str,
        nodes_by_id: dict[str, Any],
        tasks: list[dict[str, Any]],
        me: dict[str, Any],
        round_no: int,
    ) -> Optional[str]:
        """Pick a task/ice node worth detouring to before the gate: a detour pays
        off when its score gain beats the extra freshness it costs. Our huge frame
        slack (deliver ~470 vs 600) makes on-route collection the main score lever."""
        gate = self.gate_node
        base = self.graph.path_cost(node, gate)
        if not math.isfinite(base):
            return None

        gains: dict[str, float] = {}
        # claimable tasks (skip ones that would expire before we could arrive)
        if self.task_base < TASK_BASE_TARGET:
            for t in tasks:
                if not self._task_claimable(t, me, round_no):
                    continue
                w = t.get("nodeId")
                cost = self.graph.path_cost(node, w)
                if not math.isfinite(cost):
                    continue
                est_arrival = round_no + cost / 0.055  # rough frames from freshness cost
                expire = t.get("expireRound", 0)
                if expire and est_arrival >= expire:
                    continue
                gains[w] = gains.get(w, 0.0) + self._task_value(t)
        # ice boxes still under our cap
        if me.get("resources", {}).get(ICE_BOX, 0) < STOCK_TARGETS[ICE_BOX]:
            for nid, n in nodes_by_id.items():
                if (n.get("resourceStock", {}) or {}).get(ICE_BOX, 0) > 0:
                    gains[nid] = gains.get(nid, 0.0) + ICE_GAIN_SCORE

        best, best_net = None, WAYPOINT_MIN_NET
        for w, gain in gains.items():
            if w == node:
                continue
            detour = self.graph.path_cost(node, w) + self.graph.path_cost(w, gate) - base
            if not math.isfinite(detour):
                continue
            net = gain - max(0.0, detour) * FRESH_SCORE_PER_POINT
            if net > best_net:
                best, best_net = w, net
        return best

    def _advance(
        self, node: str, nodes_by_id: dict[str, Any], dest: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Step toward dest (default: the gate); force through a road obstacle /
        enemy guard on the next hop."""
        nxt = self.graph.next_hop(node, dest or self.gate_node)
        if not nxt:
            return []
        tgt = nodes_by_id.get(nxt, {})
        if tgt.get("hasObstacle"):
            # FORCED_PASS a pure road obstacle: it creates NO contest window
            # (task book 5.4.1), so it can't be dragged into a draw-retry loop
            # the way CLEAR can when the opponent contests the same obstacle.
            # It only costs an 8-frame time tax (refunded if the obstacle is
            # cleared mid-pass) and keeps our good fruit. The rare
            # FORCED_PASS_REPEAT on two obstacles in a row is a harmless
            # business reject (no penalty) that self-resolves.
            return [M.forced_pass(nxt)]
        if nxt in self._guard_blocked:
            # an enemy guard is blocking the only way forward: FORCED_PASS opens
            # a PASS window which our card policy then plays to get through.
            return [M.forced_pass(nxt)]
        return [self._mv(nxt)]

    def _mv(self, target: str) -> dict[str, Any]:
        """Emit a MOVE, remembering the target so we can detect if it's blocked."""
        self._last_move_target = target
        return M.move(target)

    def _note_blocked_moves(
        self, action_results: list[dict[str, Any]], nodes_by_id: dict[str, Any]
    ) -> None:
        """If our last MOVE was rejected and the target has no obstacle, an enemy
        guard is blocking it -> remember to FORCED_PASS it next time."""
        tgt = self._last_move_target
        if not tgt:
            return
        for r in action_results:
            if (
                r.get("playerId") == self.player_id
                and r.get("action") == "MOVE"
                and not r.get("accepted", True)
            ):
                if not nodes_by_id.get(tgt, {}).get("hasObstacle"):
                    self._guard_blocked.add(tgt)
                break

    def _find_me(self, players: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        for p in players:
            if p.get("playerId") == self.player_id:
                return p
        return None
