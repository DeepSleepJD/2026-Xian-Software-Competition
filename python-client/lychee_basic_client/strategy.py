import heapq
import math
from typing import Any, Optional

from .graph import Graph


TOTAL_ROUNDS = 600
DELIVERY_MARGIN_ROUNDS = 60
VERIFY_GATE_ROUNDS = 6
DELIVER_ROUNDS = 2
MOVE_COST_PER_ROUND = 1000
GUARD_KEEP_GOOD_FRUIT = 6
GUARD_SETUP_ROUNDS = 5
GUARD_FREEZE_SAFETY_ROUNDS = 2
WINDOW_CARD_GOOD_FRUIT_FLOOR = GUARD_KEEP_GOOD_FRUIT
HIGH_VALUE_WINDOW_PRIORITY = 90

WINDOW_CONTEST_PRIORITY = {
    "GATE": 100,
    "PASS": 90,
    "OBSTACLE": 40,
    "TASK": 30,
    "DOCK": 20,
    "RESOURCE": 15,
}

ROUTE_COST = {
    "ROAD": 1380,
    "WATER": 1250,
    "MOUNTAIN": 1780,
    "BRANCH": 1550,
}


class MovementStrategy:
    def __init__(self, player_id: int) -> None:
        self._player_id = player_id
        self._edges: list[dict[str, Any]] = []
        self._nodes_by_id: dict[str, dict[str, Any]] = {}
        self._last_rejected_payload: Optional[dict[str, Any]] = None
        self._last_current_node_id: Optional[str] = None
        self._previous_node_id: Optional[str] = None
        self._processed_nodes: set[str] = set()
        self._graph = Graph()
        self._start_node_id: Optional[str] = None
        self._gate_node_id: Optional[str] = None
        self._terminal_node_ids: set[str] = set()
        self._choke_node_ids: list[str] = []
        self._guarded_choke_node_ids: set[str] = set()
        self._claimed_resource_keys: set[str] = set()
        self._used_resource_types: set[str] = set()
        self._claimed_task_ids: set[str] = set()
        self._squad_order_keys: set[str] = set()
        self._played_window_keys: set[tuple[str, int]] = set()

    def update_start(self, data: dict[str, Any]) -> None:
        self._update_map(data)

    def choose_action(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        self._update_map(data)

        player = self._find_player(data.get("players", []))
        if not player:
            return []

        current_node_id = player.get("currentNodeId")
        if isinstance(current_node_id, str):
            self._remember_current_node(current_node_id)
        self._remember_process_events(data)

        waiting_action = self._waiting_resume_action(player)
        if waiting_action:
            return self._with_squad_action(data, player, current_node_id, [waiting_action])

        if not self._can_plan_from_node(player) or not isinstance(current_node_id, str):
            return self._with_squad_action(data, player, current_node_id, [])

        if self._can_deliver(player, current_node_id):
            return self._with_window_action(data, player, [{"action": "DELIVER"}])

        if self._needs_gate_verification(data, player, current_node_id):
            return self._with_squad_action(data, player, current_node_id, [self._gate_verification_action(player, current_node_id)])

        if self._is_waiting_for_rush_at_gate(data, player, current_node_id):
            return self._with_squad_action(data, player, current_node_id, [])

        deadline_action = self._deadline_delivery_action(data, player, current_node_id)
        if deadline_action is not None:
            return self._with_squad_action(data, player, current_node_id, deadline_action)

        if self._needs_processing(current_node_id):
            return self._with_squad_action(data, player, current_node_id, [{"action": "PROCESS", "targetNodeId": current_node_id}])

        choke_action = self._choke_rush_action(data, player, current_node_id)
        if choke_action is not None:
            return self._with_squad_action(data, player, current_node_id, choke_action)

        task_action = self._task_action(data, current_node_id)
        if task_action:
            return self._with_squad_action(data, player, current_node_id, [task_action])

        resource_action = self._resource_action(player, current_node_id)
        if resource_action:
            return self._with_squad_action(data, player, current_node_id, [resource_action])

        target_node_id = self._next_step_toward_score(data, player, current_node_id)
        if not target_node_id:
            return self._with_squad_action(data, player, current_node_id, [])
        guard_action = self._guard_breakthrough_action(data, player, target_node_id)
        if guard_action:
            return self._with_squad_action(data, player, current_node_id, [guard_action])
        if self._has_obstacle(target_node_id):
            t04_action = self._t04_obstacle_task_action(data, current_node_id, target_node_id)
            if t04_action:
                return self._with_squad_action(data, player, current_node_id, [t04_action])
            if self._active_t04_task_for_obstacle(data, target_node_id):
                return self._with_squad_action(data, player, current_node_id, [])
            return self._with_squad_action(data, player, current_node_id, [{"action": "CLEAR", "targetNodeId": target_node_id}])
        return self._with_squad_action(data, player, current_node_id, [{"action": "MOVE", "targetNodeId": target_node_id}])

    def _update_map(self, data: dict[str, Any]) -> None:
        gameplay = self._gameplay(data)
        roles = gameplay.get("roles") if isinstance(gameplay, dict) else None
        if isinstance(roles, dict):
            start_node_id = roles.get("startNodeId")
            if isinstance(start_node_id, str):
                self._start_node_id = start_node_id
            gate_node_id = roles.get("gateNodeId")
            if isinstance(gate_node_id, str):
                self._gate_node_id = gate_node_id
            terminal_node_ids = roles.get("terminalNodeIds")
            if isinstance(terminal_node_ids, list):
                self._terminal_node_ids.update(node_id for node_id in terminal_node_ids if isinstance(node_id, str))

        edges = data.get("edges")
        if isinstance(edges, list):
            self._edges = [edge for edge in edges if isinstance(edge, dict)]
            self._graph.load_edges(self._edges)

        nodes = data.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_id = node.get("nodeId")
                if isinstance(node_id, str):
                    self._nodes_by_id[node_id] = node
                    if node.get("terminal") is True:
                        self._terminal_node_ids.add(node_id)
        self._refresh_choke_points()

    def _gameplay(self, data: dict[str, Any]) -> dict[str, Any]:
        map_data = data.get("map")
        if isinstance(map_data, dict):
            gameplay = map_data.get("gameplay")
            if isinstance(gameplay, dict):
                return gameplay
        return {}

    def _refresh_choke_points(self) -> None:
        start_node_id = self._start_node_id or "S01"
        if not self._gate_node_id or not self._edges:
            self._choke_node_ids = []
            return
        self._choke_node_ids = self._graph.choke_points(start_node_id, self._gate_node_id)

    def _find_player(self, players: Any) -> Optional[dict[str, Any]]:
        if not isinstance(players, list):
            return None
        for player in players:
            if isinstance(player, dict) and player.get("playerId") == self._player_id:
                return player
        return None

    def _waiting_resume_action(self, player: dict[str, Any]) -> Optional[dict[str, Any]]:
        if player.get("state") != "WAITING":
            return None
        next_node_id = player.get("nextNodeId")
        if not isinstance(next_node_id, str) or not next_node_id:
            return None
        action: dict[str, Any] = {"action": "MOVE", "targetNodeId": next_node_id}
        if self._has_horse_buff(player):
            action["rushTactic"] = "RUSH_SPEED"
        return action

    def _can_plan_from_node(self, player: dict[str, Any]) -> bool:
        state = player.get("state")
        if state == "IDLE":
            return True
        if state != "WAITING":
            return False
        return (
            player.get("nextNodeId") is None
            and player.get("routeEdgeId") is None
            and int(player.get("edgeTotalMs", 0) or 0) == 0
        )

    def _first_reachable_neighbor(self, current_node_id: str) -> Optional[str]:
        fallback = None
        for edge in self._edges:
            neighbor = self._neighbor_for_edge(edge, current_node_id)
            if not neighbor or not self._is_node_open(neighbor):
                continue
            if fallback is None:
                fallback = neighbor
            if neighbor != self._previous_node_id:
                return neighbor
        return fallback

    def _next_step_toward_score(self, data: dict[str, Any], player: dict[str, Any], current_node_id: str) -> Optional[str]:
        goals = self._score_goals(data, player, current_node_id)
        if goals:
            path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=False, player=player)
            if not path:
                path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=True, player=player)
            if len(path) >= 2:
                return path[1]
        return self._first_reachable_neighbor(current_node_id)

    def _score_goals(self, data: dict[str, Any], player: dict[str, Any], current_node_id: str) -> set[str]:
        task_goals = self._task_goal_nodes(data, player, current_node_id)
        if task_goals:
            return task_goals
        return self._delivery_goals(player)

    def _delivery_goals(self, player: dict[str, Any]) -> set[str]:
        if player.get("verified") is True:
            return set(self._terminal_node_ids)
        if self._gate_node_id:
            return {self._gate_node_id}
        return set(self._terminal_node_ids)

    def _deadline_delivery_action(
        self, data: dict[str, Any], player: dict[str, Any], current_node_id: str
    ) -> Optional[list[dict[str, Any]]]:
        if not self._must_protect_delivery(data, player, current_node_id):
            return None
        if self._needs_processing(current_node_id):
            return [{"action": "PROCESS", "targetNodeId": current_node_id}]

        target_node_id = self._next_step_toward_delivery(player, current_node_id)
        if not target_node_id:
            return []
        guard_action = self._guard_breakthrough_action(data, player, target_node_id)
        if guard_action:
            return [guard_action]
        if self._has_obstacle(target_node_id):
            t04_action = self._t04_obstacle_task_action(data, current_node_id, target_node_id)
            if t04_action:
                return [t04_action]
            if self._active_t04_task_for_obstacle(data, target_node_id):
                return []
            return [{"action": "CLEAR", "targetNodeId": target_node_id}]
        return [{"action": "MOVE", "targetNodeId": target_node_id}]

    def _must_protect_delivery(self, data: dict[str, Any], player: dict[str, Any], current_node_id: str) -> bool:
        round_no = data.get("round")
        if not isinstance(round_no, int) or player.get("delivered") is True:
            return False
        remaining_rounds = self._estimated_delivery_rounds(player, current_node_id)
        if remaining_rounds == math.inf:
            return False
        return round_no + remaining_rounds + DELIVERY_MARGIN_ROUNDS >= TOTAL_ROUNDS

    def _estimated_delivery_rounds(self, player: dict[str, Any], current_node_id: str) -> float:
        if player.get("verified") is True:
            terminal_path = self._path_to_any_goal(current_node_id, set(self._terminal_node_ids), allow_obstacles=True, player=player)
            if not terminal_path:
                return math.inf
            return self._path_rounds(terminal_path) + DELIVER_ROUNDS

        if not self._gate_node_id:
            return math.inf
        gate_path = self._path_to_any_goal(current_node_id, {self._gate_node_id}, allow_obstacles=True, player=player)
        if not gate_path:
            return math.inf
        gate_to_terminal = self._path_to_any_goal(self._gate_node_id, set(self._terminal_node_ids), allow_obstacles=True, player=player)
        if not gate_to_terminal:
            return math.inf
        return self._path_rounds(gate_path) + VERIFY_GATE_ROUNDS + self._path_rounds(gate_to_terminal) + DELIVER_ROUNDS

    def _next_step_toward_delivery(self, player: dict[str, Any], current_node_id: str) -> Optional[str]:
        goals = self._delivery_goals(player)
        if not goals:
            return None
        path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=False, player=player)
        if not path:
            path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=True, player=player)
        if len(path) >= 2:
            return path[1]
        return None

    def _choke_rush_action(
        self, data: dict[str, Any], player: dict[str, Any], current_node_id: str
    ) -> Optional[list[dict[str, Any]]]:
        if player.get("verified") is True or not self._choke_node_ids:
            return None
        if current_node_id in self._choke_node_ids:
            guard_action = self._guard_choke_action(data, player, current_node_id)
            if guard_action:
                return [guard_action]
            return []

        target_node_id = self._next_step_toward_choke(player, current_node_id)
        if not target_node_id:
            return None
        guard_action = self._guard_breakthrough_action(data, player, target_node_id)
        if guard_action:
            return [guard_action]
        if self._has_obstacle(target_node_id):
            t04_action = self._t04_obstacle_task_action(data, current_node_id, target_node_id)
            if t04_action:
                return [t04_action]
            if self._active_t04_task_for_obstacle(data, target_node_id):
                return []
            return [{"action": "CLEAR", "targetNodeId": target_node_id}]
        return [{"action": "MOVE", "targetNodeId": target_node_id}]

    def _next_step_toward_choke(self, player: dict[str, Any], current_node_id: str) -> Optional[str]:
        best_path: list[str] = []
        best_cost: Optional[int] = None
        for choke_node_id in self._choke_node_ids:
            if choke_node_id == current_node_id:
                continue
            path = self._path_to_any_goal(current_node_id, {choke_node_id}, allow_obstacles=False, player=player)
            if not path:
                path = self._path_to_any_goal(current_node_id, {choke_node_id}, allow_obstacles=True, player=player)
            if len(path) < 2:
                continue
            cost = self._path_cost(path)
            if best_cost is not None and cost >= best_cost:
                continue
            best_path = path
            best_cost = cost
        if len(best_path) >= 2:
            return best_path[1]
        return None

    def _guard_choke_action(
        self, data: dict[str, Any], player: dict[str, Any], current_node_id: str
    ) -> Optional[dict[str, Any]]:
        if current_node_id in self._guarded_choke_node_ids:
            return None
        if int(player.get("goodFruit", 0) or 0) <= GUARD_KEEP_GOOD_FRUIT:
            return None
        if self._has_own_active_guard(current_node_id, player):
            return None
        opponent = self._find_opponent(data.get("players", []))
        if not self._opponent_must_cross_choke(opponent, current_node_id):
            return None
        if not self._freeze_window_open(opponent, current_node_id):
            return None

        self._guarded_choke_node_ids.add(current_node_id)
        return {
            "action": "SET_GUARD",
            "targetNodeId": current_node_id,
            "extraGoodFruit": self._guard_extra_good_fruit(player),
        }

    def _find_opponent(self, players: Any) -> Optional[dict[str, Any]]:
        if not isinstance(players, list):
            return None
        for player in players:
            if isinstance(player, dict) and player.get("playerId") != self._player_id:
                return player
        return None

    def _opponent_must_cross_choke(self, opponent: Optional[dict[str, Any]], choke_node_id: str) -> bool:
        if not opponent or not self._gate_node_id:
            return False
        opponent_node_id = opponent.get("currentNodeId")
        if not isinstance(opponent_node_id, str):
            return False
        return self._graph.path_frames(opponent_node_id, self._gate_node_id, avoid={choke_node_id}) == math.inf

    def _freeze_window_open(self, opponent: Optional[dict[str, Any]], choke_node_id: str) -> bool:
        if not opponent or opponent.get("state") != "MOVING" or opponent.get("nextNodeId") != choke_node_id:
            return False
        return self._opponent_remaining_edge_rounds(opponent) >= GUARD_SETUP_ROUNDS + GUARD_FREEZE_SAFETY_ROUNDS

    def _opponent_remaining_edge_rounds(self, opponent: dict[str, Any]) -> int:
        current_node_id = opponent.get("currentNodeId")
        next_node_id = opponent.get("nextNodeId")
        if not isinstance(current_node_id, str) or not isinstance(next_node_id, str):
            return 0
        edge_rounds = self._graph.edge_frames(current_node_id, next_node_id)
        if edge_rounds is None:
            edge = self._edge_between(current_node_id, next_node_id)
            edge_rounds = math.ceil(self._edge_cost(edge) / MOVE_COST_PER_ROUND) if edge else 0
        progress = opponent.get("edgeProgressPermille", 0)
        if not isinstance(progress, int):
            progress = 0
        progress = min(1000, max(0, progress))
        return math.ceil((1 - progress / 1000.0) * edge_rounds)

    def _has_own_active_guard(self, node_id: str, player: dict[str, Any]) -> bool:
        node = self._nodes_by_id.get(node_id) or {}
        guard = node.get("guard")
        if not isinstance(guard, dict):
            return False
        defense = guard.get("defense", 0)
        return (
            guard.get("ownerTeamId") == player.get("teamId")
            and guard.get("active") is not False
            and (not isinstance(defense, int) or defense > 0)
        )

    def _guard_extra_good_fruit(self, player: dict[str, Any]) -> int:
        spare = int(player.get("goodFruit", 0) or 0) - GUARD_KEEP_GOOD_FRUIT
        return max(0, min(2, spare))

    def _path_to_any_goal(
        self,
        start_node_id: str,
        goal_node_ids: set[str],
        allow_obstacles: bool,
        player: Optional[dict[str, Any]] = None,
    ) -> list[str]:
        if start_node_id in goal_node_ids:
            return [start_node_id]
        queue: list[tuple[int, str, list[str]]] = [(0, start_node_id, [start_node_id])]
        best_cost = {start_node_id: 0}
        while queue:
            cost, node_id, path = heapq.heappop(queue)
            if node_id in goal_node_ids:
                return path
            if cost > best_cost.get(node_id, cost):
                continue
            for edge, neighbor in self._neighbor_edges(node_id):
                if not allow_obstacles and self._has_obstacle(neighbor):
                    continue
                if player and self._has_blocking_guard(neighbor, player):
                    continue
                next_cost = cost + self._edge_cost(edge) + self._node_entry_cost(neighbor)
                if next_cost >= best_cost.get(neighbor, next_cost + 1):
                    continue
                best_cost[neighbor] = next_cost
                heapq.heappush(queue, (next_cost, neighbor, path + [neighbor]))
        return []

    def _neighbors(self, current_node_id: str) -> list[str]:
        return [neighbor for _, neighbor in self._neighbor_edges(current_node_id)]

    def _neighbor_edges(self, current_node_id: str) -> list[tuple[dict[str, Any], str]]:
        neighbors = []
        for edge in self._edges:
            neighbor = self._neighbor_for_edge(edge, current_node_id)
            if neighbor:
                neighbors.append((edge, neighbor))
        return neighbors

    def _edge_cost(self, edge: dict[str, Any]) -> int:
        distance = edge.get("distance", 1)
        if not isinstance(distance, int):
            distance = 1
        route_type = edge.get("routeType")
        cost = ROUTE_COST.get(route_type, 1600)
        return max(1, distance) * cost

    def _node_entry_cost(self, node_id: str) -> int:
        node = self._nodes_by_id.get(node_id) or {}
        process_round = node.get("processRound", 0)
        process_cost = process_round * 1000 if isinstance(process_round, int) else 0
        obstacle_cost = 6000 if node.get("hasObstacle") else 0
        return process_cost + obstacle_cost

    def _neighbor_for_edge(self, edge: dict[str, Any], current_node_id: str) -> Optional[str]:
        from_node_id = edge.get("fromNodeId") or edge.get("fromNode")
        to_node_id = edge.get("toNodeId") or edge.get("toNode")
        if from_node_id == current_node_id and isinstance(to_node_id, str):
            return to_node_id
        if to_node_id == current_node_id and edge.get("bidirectional") is not False and isinstance(from_node_id, str):
            return from_node_id
        return None

    def _is_node_open(self, node_id: str) -> bool:
        return not self._has_obstacle(node_id)

    def _has_obstacle(self, node_id: str) -> bool:
        node = self._nodes_by_id.get(node_id)
        if not node:
            return False
        return bool(node.get("hasObstacle"))

    def _t04_obstacle_task_action(
        self, data: dict[str, Any], current_node_id: str, target_node_id: str
    ) -> Optional[dict[str, Any]]:
        task = self._active_t04_task_for_obstacle(data, target_node_id)
        if not task:
            return None
        task_id = task.get("taskId")
        if not isinstance(task_id, str) or task_id in self._claimed_task_ids:
            return None
        if current_node_id != target_node_id and not self._edge_between(current_node_id, target_node_id):
            return None

        self._claimed_task_ids.add(task_id)
        return {"action": "CLAIM_TASK", "taskId": task_id}

    def _active_t04_task_for_obstacle(self, data: dict[str, Any], target_node_id: str) -> Optional[dict[str, Any]]:
        for task in data.get("tasks", []) or []:
            if not isinstance(task, dict):
                continue
            if task.get("taskTemplateId") != "T04":
                continue
            if task.get("nodeId") != target_node_id:
                continue
            if task.get("active") is False or task.get("completed") is True or task.get("failed") is True:
                continue
            return task
        return None

    def _has_blocking_guard(self, node_id: str, player: dict[str, Any]) -> bool:
        node = self._nodes_by_id.get(node_id)
        if not node:
            return False
        guard = node.get("guard")
        if not isinstance(guard, dict):
            return False
        owner_team_id = guard.get("ownerTeamId")
        defense = guard.get("defense", 1)
        return (
            isinstance(owner_team_id, str)
            and owner_team_id != player.get("teamId")
            and (not isinstance(defense, int) or defense > 0)
        )

    def _with_squad_action(
        self,
        data: dict[str, Any],
        player: dict[str, Any],
        current_node_id: Any,
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(current_node_id, str):
            return self._with_window_action(data, player, actions)
        squad_action = self._squad_action(data, player, current_node_id, actions)
        if squad_action:
            actions = actions + [squad_action]
        return self._with_window_action(data, player, actions)

    def _with_window_action(
        self, data: dict[str, Any], player: dict[str, Any], actions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        window_action = self._window_card_action(data, player)
        if window_action:
            return [window_action] + actions
        return actions

    def _squad_action(
        self,
        data: dict[str, Any],
        player: dict[str, Any],
        current_node_id: str,
        main_actions: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        round_no = data.get("round", 0)
        if isinstance(round_no, int) and round_no >= 390:
            return None

        squad_available = int(player.get("squadAvailable", 0) or 0)
        main_targets = self._main_action_targets(main_actions)
        if squad_available >= 2:
            weaken_target = self._squad_weaken_target(data, player, current_node_id, main_targets.get("BREAK_GUARD", set()))
            if weaken_target:
                return self._remember_squad_order("SQUAD_WEAKEN", weaken_target)

            clear_target = self._squad_clear_target(data, current_node_id, main_targets.get("CLEAR", set()))
            if clear_target:
                return self._remember_squad_order("SQUAD_CLEAR", clear_target)

        if squad_available >= 1:
            scout_target = self._squad_scout_target(data, player, current_node_id)
            if scout_target:
                return self._remember_squad_order("SQUAD_SCOUT", scout_target)
        return None

    def _main_action_targets(self, actions: list[dict[str, Any]]) -> dict[str, set[str]]:
        targets: dict[str, set[str]] = {}
        for action in actions:
            action_type = action.get("action")
            target_node_id = action.get("targetNodeId")
            if isinstance(action_type, str) and isinstance(target_node_id, str):
                targets.setdefault(action_type, set()).add(target_node_id)
        return targets

    def _squad_weaken_target(
        self,
        data: dict[str, Any],
        player: dict[str, Any],
        current_node_id: str,
        blocked_targets: set[str],
    ) -> Optional[str]:
        delivery_path = self._path_to_any_goal(
            current_node_id,
            self._delivery_goals(player),
            allow_obstacles=True,
            player=None,
        )
        for node_id in delivery_path[1:4]:
            if node_id in blocked_targets:
                continue
            if self._has_blocking_guard(node_id, player) and not self._has_squad_order("SQUAD_WEAKEN", node_id):
                return node_id
        return None

    def _squad_clear_target(
        self, data: dict[str, Any], current_node_id: str, blocked_targets: set[str]
    ) -> Optional[str]:
        delivery_goals = self._terminal_node_ids or ({self._gate_node_id} if self._gate_node_id else set())
        delivery_path = self._path_to_any_goal(current_node_id, set(delivery_goals), allow_obstacles=True)
        for node_id in delivery_path[1:5]:
            if node_id in blocked_targets:
                continue
            if self._is_squad_clear_candidate(data, node_id):
                return node_id
        return None

    def _is_squad_clear_candidate(self, data: dict[str, Any], node_id: str) -> bool:
        return (
            self._has_obstacle(node_id)
            and not self._active_t04_task_for_obstacle(data, node_id)
            and not self._has_squad_order("SQUAD_CLEAR", node_id)
        )

    def _squad_scout_target(
        self, data: dict[str, Any], player: dict[str, Any], current_node_id: str
    ) -> Optional[str]:
        round_no = data.get("round", 0)
        if isinstance(round_no, int) and round_no >= 330:
            return None

        goals = self._delivery_goals(player)
        path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=True, player=None)
        for node_id in path[1:6]:
            if self._is_squad_scout_candidate(player, node_id):
                return node_id
        return None

    def _is_squad_scout_candidate(self, player: dict[str, Any], node_id: str) -> bool:
        if self._has_squad_order("SQUAD_SCOUT", node_id):
            return False
        node = self._nodes_by_id.get(node_id) or {}
        if node.get("terminal") is True:
            return False
        process_round = node.get("processRound", 0)
        if node_id != self._gate_node_id and (not isinstance(process_round, int) or process_round < 4):
            return False
        return not self._has_own_scout_marker(node, player)

    def _has_own_scout_marker(self, node: dict[str, Any], player: dict[str, Any]) -> bool:
        team_id = player.get("teamId")
        for marker in node.get("scouted", []) or []:
            if not isinstance(marker, dict):
                continue
            if marker.get("teamId") == team_id or marker.get("ownerTeamId") == team_id:
                return True
            if marker.get("playerId") == self._player_id or marker.get("ownerPlayerId") == self._player_id:
                return True
        return False

    def _remember_squad_order(self, action: str, target_node_id: str) -> dict[str, Any]:
        self._squad_order_keys.add(f"{action}:{target_node_id}")
        return {"action": action, "targetNodeId": target_node_id}

    def _has_squad_order(self, action: str, target_node_id: str) -> bool:
        return f"{action}:{target_node_id}" in self._squad_order_keys

    def _guard_breakthrough_action(
        self, data: dict[str, Any], player: dict[str, Any], target_node_id: str
    ) -> Optional[dict[str, Any]]:
        if not self._has_blocking_guard(target_node_id, player):
            return None

        break_action = self._break_guard_action(data, player, target_node_id)
        if break_action:
            return break_action
        return {"action": "FORCED_PASS", "targetNodeId": target_node_id}

    def _break_guard_action(
        self, data: dict[str, Any], player: dict[str, Any], target_node_id: str
    ) -> Optional[dict[str, Any]]:
        node = self._nodes_by_id.get(target_node_id) or {}
        guard = node.get("guard")
        if not isinstance(guard, dict):
            return None
        defense = guard.get("defense")
        if not isinstance(defense, int) or defense <= 0:
            return None

        bad_fruit_available = max(0, min(2, int(player.get("badFruit", 0) or 0)))
        good_fruit_available = max(0, min(2, int(player.get("goodFruit", 0) or 0) - 1))
        rush_bonus = 3 if data.get("phase") == "RUSH" and player.get("breakOrderReady") is True else 0

        best_action: Optional[dict[str, Any]] = None
        best_cost: Optional[tuple[int, int, int]] = None
        for bad_fruit in range(bad_fruit_available + 1):
            for good_fruit in range(good_fruit_available + 1):
                attack = bad_fruit * 3 + good_fruit * 2 + rush_bonus
                if attack < defense:
                    continue
                cost = (good_fruit, bad_fruit, good_fruit + bad_fruit)
                if best_cost is not None and cost >= best_cost:
                    continue
                action: dict[str, Any] = {
                    "action": "BREAK_GUARD",
                    "targetNodeId": target_node_id,
                    "goodFruit": good_fruit,
                    "badFruit": bad_fruit,
                }
                if rush_bonus:
                    action["rushTactic"] = "BREAK_ORDER"
                best_action = action
                best_cost = cost
        return best_action

    def _remember_process_events(self, data: dict[str, Any]) -> None:
        for event in data.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            payload = event.get("payload")
            if not isinstance(payload, dict):
                payload = event
            if payload.get("playerId") != self._player_id:
                continue
            target_node_id = payload.get("targetNodeId")
            if not isinstance(target_node_id, str):
                continue
            if event_type == "PROCESS_COMPLETE":
                self._processed_nodes.add(target_node_id)
            elif event_type == "ACTION_REJECTED":
                self._last_rejected_payload = payload
                if payload.get("errorCode") in {"PROCESS_REQUIRED", "OBJECT_BUSY"}:
                    self._processed_nodes.discard(target_node_id)

    def _remember_current_node(self, current_node_id: str) -> None:
        if current_node_id != self._last_current_node_id:
            self._previous_node_id = self._last_current_node_id
            self._last_current_node_id = current_node_id
            self._processed_nodes.discard(current_node_id)

    def _needs_processing(self, current_node_id: str) -> bool:
        if current_node_id in self._processed_nodes:
            return False
        node = self._nodes_by_id.get(current_node_id)
        if not node or not node.get("processType") or node.get("processType") == "VERIFY":
            return False
        return True

    def _can_deliver(self, player: dict[str, Any], current_node_id: str) -> bool:
        return (
            current_node_id in self._terminal_node_ids
            and player.get("verified") is True
            and player.get("delivered") is not True
            and float(player.get("goodFruit", 0) or 0) > 0
            and float(player.get("freshness", 0) or 0) > 0
        )

    def _needs_gate_verification(self, data: dict[str, Any], player: dict[str, Any], current_node_id: str) -> bool:
        return (
            current_node_id == self._gate_node_id
            and data.get("phase") == "RUSH"
            and player.get("verified") is not True
        )

    def _gate_verification_action(self, player: dict[str, Any], current_node_id: str) -> dict[str, Any]:
        action: dict[str, Any] = {"action": "VERIFY_GATE", "targetNodeId": current_node_id}
        if player.get("breakOrderReady") is True:
            action["rushTactic"] = "BREAK_ORDER"
        return action

    def _is_waiting_for_rush_at_gate(self, data: dict[str, Any], player: dict[str, Any], current_node_id: str) -> bool:
        return (
            current_node_id == self._gate_node_id
            and data.get("phase") != "RUSH"
            and player.get("verified") is not True
        )

    def _resource_action(self, player: dict[str, Any], current_node_id: str) -> Optional[dict[str, Any]]:
        use_resource = self._resource_to_use(player)
        if use_resource:
            self._used_resource_types.add(use_resource)
            return {"action": "USE_RESOURCE", "resourceType": use_resource}

        claim_resource = self._resource_to_claim(player, current_node_id)
        if claim_resource:
            self._claimed_resource_keys.add(f"{current_node_id}:{claim_resource}")
            return {"action": "CLAIM_RESOURCE", "targetNodeId": current_node_id, "resourceType": claim_resource}
        return None

    def _resource_to_use(self, player: dict[str, Any]) -> Optional[str]:
        resources = player.get("resources")
        if not isinstance(resources, dict):
            return None

        if self._resource_count(resources, "ICE_BOX") > 0 and float(player.get("freshness", 100) or 0) <= 85:
            return "ICE_BOX"

        if self._has_horse_buff(player):
            return None
        for resource_type in ("FAST_HORSE", "SHORT_HORSE"):
            if resource_type not in self._used_resource_types and self._resource_count(resources, resource_type) > 0:
                return resource_type
        return None

    def _resource_to_claim(self, player: dict[str, Any], current_node_id: str) -> Optional[str]:
        resources = player.get("resources")
        if not isinstance(resources, dict):
            resources = {}
        node = self._nodes_by_id.get(current_node_id) or {}
        stock = node.get("resourceStock")
        if not isinstance(stock, dict):
            return None

        for resource_type in ("FAST_HORSE", "SHORT_HORSE", "ICE_BOX"):
            key = f"{current_node_id}:{resource_type}"
            if key in self._claimed_resource_keys:
                continue
            if self._resource_count(stock, resource_type) <= 0:
                continue
            if self._resource_count(resources, resource_type) > 0:
                continue
            return resource_type
        return None

    def _has_horse_buff(self, player: dict[str, Any]) -> bool:
        buffs = player.get("buffs")
        if not isinstance(buffs, list):
            return False
        return any(isinstance(buff, dict) and buff.get("type") in {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"} for buff in buffs)

    def _resource_count(self, values: dict[Any, Any], resource_type: str) -> int:
        value = values.get(resource_type, 0)
        return value if isinstance(value, int) else 0

    def _task_action(self, data: dict[str, Any], current_node_id: str) -> Optional[dict[str, Any]]:
        round_no = data.get("round", 0)
        if isinstance(round_no, int) and round_no >= 360:
            return None

        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            return None
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = task.get("taskId")
            if not isinstance(task_id, str) or task_id in self._claimed_task_ids:
                continue
            if task.get("nodeId") != current_node_id:
                continue
            if task.get("active") is False or task.get("completed") is True or task.get("failed") is True:
                continue
            self._claimed_task_ids.add(task_id)
            return {"action": "CLAIM_TASK", "taskId": task_id}
        return None

    def _task_goal_nodes(self, data: dict[str, Any], player: dict[str, Any], current_node_id: str) -> set[str]:
        if player.get("verified") is True:
            return set()
        round_no = data.get("round", 0)
        if isinstance(round_no, int) and round_no >= 330:
            return set()
        task_score = player.get("taskScore", 0)
        if isinstance(task_score, int) and task_score >= 110:
            return set()

        delivery_goals = self._delivery_goals(player)
        direct_path = self._path_to_any_goal(current_node_id, delivery_goals, allow_obstacles=True, player=player)
        direct_cost = self._path_cost(direct_path)
        task_nodes: set[str] = set()
        for task in data.get("tasks", []) or []:
            if not isinstance(task, dict):
                continue
            task_id = task.get("taskId")
            task_node = task.get("nodeId")
            score = task.get("score", 0)
            if not isinstance(task_id, str) or not isinstance(task_node, str):
                continue
            if task_id in self._claimed_task_ids or task_node == current_node_id:
                continue
            if task.get("active") is False or task.get("completed") is True or task.get("failed") is True:
                continue
            if not isinstance(score, int) or score < 15:
                continue
            to_task = self._path_to_any_goal(current_node_id, {task_node}, allow_obstacles=True, player=player)
            to_goal = self._path_to_any_goal(task_node, delivery_goals, allow_obstacles=True, player=player)
            detour_cost = self._path_cost(to_task) + self._path_cost(to_goal)
            if to_task and to_goal and detour_cost <= direct_cost + self._task_detour_budget(score, round_no):
                task_nodes.add(task_node)
        return task_nodes

    def _task_detour_budget(self, score: int, round_no: Any) -> int:
        budget = score * 3500
        if isinstance(round_no, int) and round_no > 240:
            budget //= 2
        return budget

    def _path_cost(self, path: list[str]) -> int:
        if len(path) < 2:
            return 0
        total = 0
        for index in range(len(path) - 1):
            edge = self._edge_between(path[index], path[index + 1])
            if edge:
                total += self._edge_cost(edge) + self._node_entry_cost(path[index + 1])
        return total

    def _path_rounds(self, path: list[str]) -> int:
        return math.ceil(self._path_cost(path) / MOVE_COST_PER_ROUND)

    def _edge_between(self, from_node_id: str, to_node_id: str) -> Optional[dict[str, Any]]:
        for edge, neighbor in self._neighbor_edges(from_node_id):
            if neighbor == to_node_id:
                return edge
        return None

    def _window_card_action(self, data: dict[str, Any], player: dict[str, Any]) -> Optional[dict[str, Any]]:
        contests = [contest for contest in data.get("contests", []) or [] if isinstance(contest, dict)]
        contests.sort(key=self._window_contest_priority, reverse=True)
        for contest in contests:
            if not isinstance(contest, dict):
                continue
            contest_id = contest.get("contestId")
            if not isinstance(contest_id, str):
                continue
            if contest.get("resolved") is True or contest.get("status") == "SUPPRESSED":
                continue
            if not self._is_own_contest(contest):
                continue
            cards = contest.get("cards")
            if isinstance(cards, dict) and (
                str(self._player_id) in cards or player.get("teamId") in cards
            ):
                continue
            window_key = self._window_key(contest)
            if window_key in self._played_window_keys:
                continue
            self._played_window_keys.add(window_key)
            return {"action": "WINDOW_CARD", "contestId": contest_id, "card": self._window_card(data, player, contest)}
        return None

    def _is_own_contest(self, contest: dict[str, Any]) -> bool:
        return contest.get("redPlayerId") == self._player_id or contest.get("bluePlayerId") == self._player_id

    def _window_key(self, contest: dict[str, Any]) -> tuple[str, int]:
        contest_id = contest.get("contestId")
        round_index = contest.get("roundIndex")
        return (
            contest_id if isinstance(contest_id, str) else "",
            round_index if isinstance(round_index, int) else 0,
        )

    def _window_contest_priority(self, contest: dict[str, Any]) -> int:
        return WINDOW_CONTEST_PRIORITY.get(contest.get("contestType"), 10)

    def _window_card(self, data: dict[str, Any], player: dict[str, Any], contest: dict[str, Any]) -> str:
        if self._should_spend_good_fruit_on_window(data, player, contest):
            return "XIAN_GONG"
        if int(player.get("guardActionPoint", 0) or 0) > 0:
            return "BING_ZHENG"
        resources = player.get("resources")
        if isinstance(resources, dict):
            if self._resource_count(resources, "PASS_TOKEN") > 0 or self._resource_count(resources, "OFFICIAL_PERMIT") > 0:
                return "YAN_DIE"
            if self._has_horse_buff(player) or self._resource_count(resources, "FAST_HORSE") > 0 or self._resource_count(resources, "SHORT_HORSE") > 0:
                return "QIANG_XING"
        return "ABSTAIN"

    def _should_spend_good_fruit_on_window(
        self, data: dict[str, Any], player: dict[str, Any], contest: dict[str, Any]
    ) -> bool:
        if float(player.get("freshness", 0) or 0) < 80:
            return False
        if int(player.get("goodFruit", 0) or 0) <= WINDOW_CARD_GOOD_FRUIT_FLOOR:
            return False
        if self._window_contest_priority(contest) >= HIGH_VALUE_WINDOW_PRIORITY:
            return True
        current_node_id = player.get("currentNodeId")
        return isinstance(current_node_id, str) and self._must_protect_delivery(data, player, current_node_id)
