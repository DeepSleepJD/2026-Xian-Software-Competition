"""Decision logic: navigate S01 -> ... -> S14 (verify) -> S15 (deliver)."""
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
ICE_BOX_CAP = 3


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

        # opportunistic: stock ice boxes if this node has any (no detour)
        if self._should_claim_ice(node, nodes_by_id, me):
            return [M.claim_resource(node, ICE_BOX)]

        # otherwise advance along the shortest route toward the gate
        return self._advance(node, nodes_by_id)

    def _should_claim_ice(
        self, node: str, nodes_by_id: dict[str, Any], me: dict[str, Any]
    ) -> bool:
        if me.get("resources", {}).get(ICE_BOX, 0) >= ICE_BOX_CAP:
            return False
        stock = nodes_by_id.get(node, {}).get("resourceStock", {}) or {}
        return stock.get(ICE_BOX, 0) > 0

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

    def _claimable_task_here(
        self, node: str, tasks: list[dict[str, Any]], me: dict[str, Any], round_no: int
    ) -> Optional[dict[str, Any]]:
        """Highest-value imperial task claimable at the current node, or None."""
        if self.task_base >= TASK_BASE_TARGET:
            return None
        horses = sum(me.get("resources", {}).get(k, 0) for k in HORSE_KEYS)
        best = None
        for t in tasks:
            if t.get("nodeId") != node:
                continue
            if not t.get("active") or t.get("completed") or t.get("failed"):
                continue
            owner = t.get("ownerPlayerId", 0)
            if owner not in (0, self.player_id):
                continue
            prot = t.get("protectionPlayerId", 0)
            if prot not in (0, self.player_id):
                continue  # window-protected for the opponent
            expire = t.get("expireRound", 0)
            if expire and round_no >= expire:
                continue
            if t.get("taskTemplateId") == "T06" and horses <= 0:
                continue  # needs a horse to claim
            if self._task_attempts.get(t.get("taskId"), 0) >= 3:
                continue  # give up after repeated rejects (loop guard)
            if best is None or int(t.get("score", 0)) > int(best.get("score", 0)):
                best = t
        return best

    def _advance(self, node: str, nodes_by_id: dict[str, Any]) -> list[dict[str, Any]]:
        """Step toward the gate; force through a road obstacle / enemy guard."""
        nxt = self.graph.next_hop(node, self.gate_node)
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
