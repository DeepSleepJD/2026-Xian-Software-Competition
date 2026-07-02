from typing import Any, Optional


class MovementStrategy:
    def __init__(self, player_id: int) -> None:
        self._player_id = player_id
        self._edges: list[dict[str, Any]] = []
        self._nodes_by_id: dict[str, dict[str, Any]] = {}
        self._last_rejected_payload: Optional[dict[str, Any]] = None
        self._last_current_node_id: Optional[str] = None
        self._previous_node_id: Optional[str] = None
        self._processed_nodes: set[str] = set()
        self._gate_node_id: Optional[str] = None
        self._terminal_node_ids: set[str] = set()
        self._claimed_resource_keys: set[str] = set()
        self._used_resource_types: set[str] = set()
        self._claimed_task_ids: set[str] = set()

    def update_start(self, data: dict[str, Any]) -> None:
        self._update_map(data)

    def choose_action(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        self._update_map(data)
        self._remember_rejected_payload(data)

        player = self._find_player(data.get("players", []))
        if not player:
            return []

        state = player.get("state")
        current_node_id = player.get("currentNodeId")
        if state != "IDLE" or not isinstance(current_node_id, str):
            return []

        self._remember_current_node(current_node_id)
        if self._can_deliver(player, current_node_id):
            return [{"action": "DELIVER"}]

        if self._needs_gate_verification(data, player, current_node_id):
            return [{"action": "VERIFY_GATE", "targetNodeId": current_node_id}]

        if self._is_waiting_for_rush_at_gate(data, player, current_node_id):
            return []

        if self._needs_processing(current_node_id):
            return [{"action": "PROCESS", "targetNodeId": current_node_id}]

        task_action = self._task_action(data, current_node_id)
        if task_action:
            return [task_action]

        resource_action = self._resource_action(player, current_node_id)
        if resource_action:
            return [resource_action]

        target_node_id = self._next_step_toward_score(player, current_node_id)
        if not target_node_id:
            return []
        if self._has_obstacle(target_node_id):
            return [{"action": "CLEAR", "targetNodeId": target_node_id}]
        return [{"action": "MOVE", "targetNodeId": target_node_id}]

    def _update_map(self, data: dict[str, Any]) -> None:
        gameplay = self._gameplay(data)
        roles = gameplay.get("roles") if isinstance(gameplay, dict) else None
        if isinstance(roles, dict):
            gate_node_id = roles.get("gateNodeId")
            if isinstance(gate_node_id, str):
                self._gate_node_id = gate_node_id
            terminal_node_ids = roles.get("terminalNodeIds")
            if isinstance(terminal_node_ids, list):
                self._terminal_node_ids.update(node_id for node_id in terminal_node_ids if isinstance(node_id, str))

        edges = data.get("edges")
        if isinstance(edges, list):
            self._edges = [edge for edge in edges if isinstance(edge, dict)]

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

    def _gameplay(self, data: dict[str, Any]) -> dict[str, Any]:
        map_data = data.get("map")
        if isinstance(map_data, dict):
            gameplay = map_data.get("gameplay")
            if isinstance(gameplay, dict):
                return gameplay
        return {}

    def _find_player(self, players: Any) -> Optional[dict[str, Any]]:
        if not isinstance(players, list):
            return None
        for player in players:
            if isinstance(player, dict) and player.get("playerId") == self._player_id:
                return player
        return None

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

    def _next_step_toward_score(self, player: dict[str, Any], current_node_id: str) -> Optional[str]:
        goals = self._delivery_goals(player)
        if goals:
            path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=False)
            if not path:
                path = self._path_to_any_goal(current_node_id, goals, allow_obstacles=True)
            if len(path) >= 2:
                return path[1]
        return self._first_reachable_neighbor(current_node_id)

    def _delivery_goals(self, player: dict[str, Any]) -> set[str]:
        if player.get("verified") is True:
            return set(self._terminal_node_ids)
        if self._gate_node_id:
            return {self._gate_node_id}
        return set(self._terminal_node_ids)

    def _path_to_any_goal(self, start_node_id: str, goal_node_ids: set[str], allow_obstacles: bool) -> list[str]:
        if start_node_id in goal_node_ids:
            return [start_node_id]
        queue: list[list[str]] = [[start_node_id]]
        visited = {start_node_id}
        while queue:
            path = queue.pop(0)
            for neighbor in self._neighbors(path[-1]):
                if neighbor in visited:
                    continue
                if not allow_obstacles and self._has_obstacle(neighbor):
                    continue
                next_path = path + [neighbor]
                if neighbor in goal_node_ids:
                    return next_path
                visited.add(neighbor)
                queue.append(next_path)
        return []

    def _neighbors(self, current_node_id: str) -> list[str]:
        neighbors = []
        for edge in self._edges:
            neighbor = self._neighbor_for_edge(edge, current_node_id)
            if neighbor:
                neighbors.append(neighbor)
        return neighbors

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

    def _remember_rejected_payload(self, data: dict[str, Any]) -> None:
        for event in data.get("events", []) or []:
            if not isinstance(event, dict) or event.get("type") != "ACTION_REJECTED":
                continue
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("playerId") == self._player_id:
                self._last_rejected_payload = payload
                if payload.get("errorCode") == "PROCESS_REQUIRED":
                    self._processed_nodes.discard(str(payload.get("targetNodeId", "")))

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
        self._processed_nodes.add(current_node_id)
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
