"""Direct-run policy for tiny maps where choke racing has little leverage."""
from typing import Any, Optional

from . import messages as M
from .graph import move_frames

TOTAL_ROUNDS = 600
ICE_BOX = "ICE_BOX"
BUSY_STATES = {"PROCESSING", "VERIFYING", "FORCED_PASSING", "RESTING", "CONTESTING"}


class ShortPathStrategy:
    """Small-map fallback: skip blockade play and run a direct delivery plan.

    The owning Strategy still provides graph/ETA/weather/task helpers. Keeping this
    class thin lets the branch stay isolated without duplicating routing logic.
    """

    MAX_PATH_NODES = 4

    def __init__(self, opening_path: list[str]) -> None:
        self.opening_path = opening_path

    @classmethod
    def from_path(cls, path: Optional[list[str]]) -> Optional["ShortPathStrategy"]:
        if path and len(path) <= cls.MAX_PATH_NODES:
            return cls(path)
        return None

    def decide(
        self, owner, me: dict[str, Any], opp: Optional[dict[str, Any]], node: str,
        state: str, phase: str, round_no: int, tasks: list[dict[str, Any]],
        nodes_by_id: dict[str, dict[str, Any]], weather=None
    ) -> list[dict[str, Any]]:
        if state in BUSY_STATES:
            return []
        if me.get("delivered") or me.get("retired"):
            return []

        if owner._rush_speed_action(me, state, phase):
            return [M.rush_speed()]

        dest = owner.terminal_node if me.get("verified") else owner.gate_node
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            return self._advance(owner, dest, me, node, state, phase, tasks,
                                 nodes_by_id, round_no, weather)

        local = self._local_action(owner, me, node, round_no, tasks, nodes_by_id, weather)
        if local:
            return local

        process = owner._process_here_if_needed(node, nodes_by_id)
        if process:
            return process

        return self._advance(
            owner, dest, me, node, state, phase, tasks, nodes_by_id, round_no, weather
        )

    def _local_action(
        self, owner, me, node, round_no, tasks, nodes_by_id, weather=None
    ) -> list[dict[str, Any]]:
        task = owner._claimable_task_here(node, tasks, me, round_no)
        if task is not None and self._local_frames_fit_delivery(
            owner, me, node, round_no,
            owner._task_op_frames(task, me, round_no, nodes_by_id),
            nodes_by_id, weather,
        ):
            return owner._claim_task_action(task)

        if owner._held_resource(me, ICE_BOX) and owner._freshness(me) < 100:
            return [M.use_resource(ICE_BOX)]

        ice = owner._ice_claim_frames_here(node, me, nodes_by_id, round_no)
        if ice is not None and self._local_frames_fit_delivery(
            owner, me, node, round_no, ice, nodes_by_id, weather
        ):
            return [M.claim_resource(node, ICE_BOX)]

        horse = owner._claimable_horse_for_wait(node, me, nodes_by_id)
        if horse is not None:
            return [M.claim_resource(node, horse)]
        return []

    def _local_frames_fit_delivery(
        self, owner, me, node, round_no, local_frames, nodes_by_id, weather=None
    ) -> bool:
        process_after = 0
        if owner._needs_process(node, nodes_by_id) and node not in owner.processed:
            process_after = owner._process_frames(
                node, nodes_by_id, round_no + local_frames, weather, round_no, me
            )
        need = owner._frames_to_deliver(node, me, nodes_by_id, round_no, weather)
        if need == float("inf"):
            return False
        return round_no + local_frames + process_after + need < TOTAL_ROUNDS

    def _advance(
        self, owner, dest, me, node, state, phase, tasks, nodes_by_id, round_no,
        weather=None
    ) -> list[dict[str, Any]]:
        if node == dest:
            return owner._arrive(dest, me, phase, nodes_by_id)
        if me.get("routeEdgeId") and me.get("nextNodeId"):
            if me["nextNodeId"] in owner._guard_blocked:
                detour = self._adjacent_detour(owner, me, node)
                if detour:
                    return [M.move(detour)]
            held = owner._held_horse(me)
            if held and not owner._active_horse(me):
                return [M.use_resource(held)]
            return [M.move(me["nextNodeId"])]
        if node == owner.gate_node and not me.get("verified"):
            return owner._arrive(owner.gate_node, me, phase, nodes_by_id)

        obstacles = {nid for nid, n in nodes_by_id.items() if n.get("hasObstacle")}
        plan = owner._route_plan(
            node, dest, me, nodes_by_id, obstacles=obstacles,
            round_no=round_no, weather=weather
        )
        if plan.frames == float("inf"):
            plan = owner._route_plan(
                node, dest, me, nodes_by_id, avoid=set(owner._guard_blocked),
                obstacles=obstacles,
                round_no=round_no, weather=weather
            )

        if plan.first_claim:
            return [M.claim_resource(node, plan.first_claim)]
        nxt = plan.next_hop
        if not nxt:
            return []
        if nxt in owner._guard_blocked:
            return [M.forced_pass(nxt)]
        if nodes_by_id.get(nxt, {}).get("hasObstacle"):
            if nxt in owner._squad_sent:
                return [M.forced_pass(nxt)]
            return owner._opening_obstacle_action(node, nxt, tasks or [])
        return [M.move(nxt)]

    def _adjacent_detour(self, owner, me, node) -> Optional[str]:
        blocked_next = me.get("nextNodeId")
        best: Optional[tuple[int, str]] = None
        seen: set[str] = set()
        for target, route_type, distance in owner.graph.adj.get(node, []):
            if target in seen or target == blocked_next or target in owner._guard_blocked:
                continue
            seen.add(target)
            candidate = (move_frames(distance, route_type), target)
            if best is None or candidate < best:
                best = candidate
        return None if best is None else best[1]
