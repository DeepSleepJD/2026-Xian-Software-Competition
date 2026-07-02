"""GameState 世界模型：策略层的唯一输入（契约冻结点，改动需三人同步）。

对照通信协议第 5/7 章 + 附录 B/C/D/F 逐字段解析，并用 refs/debug-kit-v1/ 的
start消息.json / inquire消息.json 实测核对。文档与样例的已知差异（以样例为准）：
- start.players[] 用 `name`，inquire.players[] 用 `playerName` → 两者都认
- start 顶层 resources/taskTemplates 可能为空列表 → 回退 map.gameplay.resources
- edges 用 fromNodeId/toNodeId，缺失回退 fromNode/toNode
- inquire.edges 某帧缺失 → 沿用 start 的边表
- 附录 C 说 guard.active 由服务端序列化，实测样例 guard 不带该字段
  → 缺失时按文档口径推导（ownerTeamId 非空且 defense > 0）
解析原则：全部 .get() 容错缺省，绝不抛异常反杀铁律层；极少用的动态字段
（events.payload、contests 的 initial*）保留 dict 原样。
"""

from dataclasses import dataclass, field


# ---------- start 静态数据 ----------

@dataclass
class Node:
    node_id: str = ""
    name: str = ""
    x: int = 0
    y: int = 0
    node_type: str = ""          # START / DOCK / GATE / FINISH / KEY_PASS ...
    is_start: bool = False
    is_terminal: bool = False

    @staticmethod
    def from_dict(d: dict) -> "Node":
        return Node(
            node_id=d.get("nodeId", ""),
            name=d.get("name", ""),
            x=d.get("x", 0),
            y=d.get("y", 0),
            node_type=d.get("nodeType") or d.get("type") or "",
            is_start=bool(d.get("start")),
            is_terminal=bool(d.get("terminal")),
        )


@dataclass
class Edge:
    edge_id: str = ""
    from_node: str = ""
    to_node: str = ""
    route_type: str = ""         # ROAD / WATER / MOUNTAIN / BRANCH
    distance: int = 0
    bidirectional: bool = True

    @staticmethod
    def from_dict(d: dict) -> "Edge":
        return Edge(
            edge_id=d.get("edgeId", ""),
            from_node=d.get("fromNodeId") or d.get("fromNode") or "",
            to_node=d.get("toNodeId") or d.get("toNode") or "",
            route_type=d.get("routeType", ""),
            distance=d.get("distance", 0),
            bidirectional=bool(d.get("bidirectional", True)),
        )


@dataclass
class ResourceSpec:
    """start 下发的资源投放配置。"""
    node_id: str = ""
    resource_type: str = ""      # ICE_BOX / FAST_HORSE / SHORT_HORSE / PASS_TOKEN / INTEL / BOAT_RIGHT ...
    count: int = 0
    claim_round: int = 0

    @staticmethod
    def from_dict(d: dict) -> "ResourceSpec":
        return ResourceSpec(
            node_id=d.get("nodeId", ""),
            resource_type=d.get("resourceType", ""),
            count=d.get("count", 0),
            claim_round=d.get("claimRound", 0),
        )


@dataclass
class ProcessNode:
    """start 下发的读条处理点（换乘/登船/宫门验核等）。"""
    node_id: str = ""
    process_type: str = ""
    process_round: int = 0
    required_resource_types: list[str] = field(default_factory=list)
    can_window: bool = False

    @staticmethod
    def from_dict(d: dict) -> "ProcessNode":
        return ProcessNode(
            node_id=d.get("nodeId", ""),
            process_type=d.get("processType", ""),
            process_round=d.get("processRound", 0),
            required_resource_types=list(d.get("requiredResourceTypes") or []),
            can_window=bool(d.get("canWindow")),
        )


@dataclass
class TaskTemplate:
    task_template_id: str = ""
    name: str = ""
    candidate_node_ids: list[str] = field(default_factory=list)
    process_type: str = ""
    process_round: int = 0
    required_freshness: float = 0.0
    required_resource_types: list[str] = field(default_factory=list)
    score: int = 0

    @staticmethod
    def from_dict(d: dict) -> "TaskTemplate":
        return TaskTemplate(
            task_template_id=d.get("taskTemplateId", ""),
            name=d.get("name", ""),
            candidate_node_ids=list(d.get("candidateNodeIds") or []),
            process_type=d.get("processType", ""),
            process_round=d.get("processRound", 0),
            required_freshness=d.get("requiredFreshness", 0.0),
            required_resource_types=list(d.get("requiredResourceTypes") or []),
            score=d.get("score", 0),
        )


@dataclass
class MapRoles:
    """地图语义点（start.map.gameplay.roles）。"""
    start_node_id: str = ""
    terminal_node_ids: list[str] = field(default_factory=list)
    gate_node_id: str = ""
    safe_zone_node_ids: list[str] = field(default_factory=list)
    reverify_node_id: str = ""
    rush_excluded_node_ids: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> "MapRoles":
        return MapRoles(
            start_node_id=d.get("startNodeId", ""),
            terminal_node_ids=list(d.get("terminalNodeIds") or []),
            gate_node_id=d.get("gateNodeId", ""),
            safe_zone_node_ids=list(d.get("safeZoneNodeIds") or []),
            reverify_node_id=d.get("reverifyNodeId", ""),
            rush_excluded_node_ids=list(d.get("rushExcludedNodeIds") or []),
        )


# ---------- inquire 运行时数据 ----------

@dataclass
class Buff:
    type: str = ""               # FAST_HORSE / SHORT_HORSE / RUSH_SPEED / RUSH_PROTECT ...
    remaining_round: int = 0
    move_multiplier: float = 1.0
    freshness_multiplier: float = 1.0

    @staticmethod
    def from_dict(d: dict) -> "Buff":
        return Buff(
            type=d.get("type", ""),
            remaining_round=d.get("remainingRound", 0),
            move_multiplier=d.get("moveMultiplier", 1.0),
            freshness_multiplier=d.get("freshnessMultiplier", 1.0),
        )


@dataclass
class CurrentProcess:
    """读条中动作（players[].currentProcess，无读条时 GameState 里为 None）。"""
    action: str = ""
    object_key: str = ""
    target_node_id: str = ""
    task_id: str = ""
    resource_type: str = ""
    started_round: int = 0
    total_round: int = 0
    remain_round: int = 0
    progress: float = 0.0

    @staticmethod
    def from_dict(d: dict) -> "CurrentProcess":
        return CurrentProcess(
            action=d.get("action") or d.get("type") or "",
            object_key=d.get("objectKey", ""),
            target_node_id=d.get("targetNodeId") or "",
            task_id=d.get("taskId") or "",
            resource_type=d.get("resourceType") or "",
            started_round=d.get("startedRound", 0),
            total_round=d.get("totalRound", 0),
            remain_round=d.get("remainRound", d.get("remainingRound", 0)),
            progress=d.get("progress", 0.0),
        )


@dataclass
class PlayerState:
    """双方每帧公开状态（附录 B）。"""
    player_id: int = 0
    camp: int = 0
    team_id: str = ""            # RED / BLUE
    player_name: str = ""
    online: bool = True
    state: str = ""              # IDLE / MOVING / PROCESSING ...
    current_node_id: str = ""
    next_node_id: str = ""       # 停靠时空串
    route_edge_id: str = ""
    route_type: str = ""
    move_direction: str = ""     # NONE / FORWARD / PAUSED
    move_progress: float = 0.0
    edge_progress_ms: int = 0
    edge_total_ms: int = 0
    freshness: float = 0.0
    good_fruit: int = 0
    frozen_good_fruit: int = 0
    bad_fruit: int = 0
    squad_available: int = 0
    squad_in_flight: int = 0
    guard_action_point: int = 0
    verified: bool = False
    delivered: bool = False
    retired: bool = False
    missing_action_rounds: int = 0
    illegal_action_count: int = 0
    penalty_score: int = 0
    break_order_ready: bool = False
    rush_tactic_used_count: int = 0
    buffs: list[Buff] = field(default_factory=list)
    current_process: CurrentProcess | None = None
    resources: dict[str, int] = field(default_factory=dict)
    total_score: int = 0
    task_score: int = 0
    bounty_score: int = 0
    score_detail: dict = field(default_factory=dict)  # 分项得分（附录 B），动态结构保留原样

    @staticmethod
    def from_dict(d: dict) -> "PlayerState":
        cp = d.get("currentProcess")
        return PlayerState(
            player_id=d.get("playerId", 0),
            camp=d.get("camp", 0),
            team_id=d.get("teamId", ""),
            player_name=d.get("playerName") or d.get("name") or "",
            online=bool(d.get("online", True)),
            state=d.get("state", ""),
            current_node_id=d.get("currentNodeId") or "",
            next_node_id=d.get("nextNodeId") or "",
            route_edge_id=d.get("routeEdgeId") or "",
            route_type=d.get("routeType") or "",
            move_direction=d.get("moveDirection") or "",
            move_progress=d.get("moveProgress", 0.0),
            edge_progress_ms=d.get("edgeProgressMs", 0),
            edge_total_ms=d.get("edgeTotalMs", 0),
            freshness=d.get("freshness", 0.0),
            good_fruit=d.get("goodFruit", 0),
            frozen_good_fruit=d.get("frozenGoodFruit", 0),
            bad_fruit=d.get("badFruit", 0),
            squad_available=d.get("squadAvailable", 0),
            squad_in_flight=d.get("squadInFlight", 0),
            guard_action_point=d.get("guardActionPoint", 0),
            verified=bool(d.get("verified")),
            delivered=bool(d.get("delivered")),
            retired=bool(d.get("retired")),
            missing_action_rounds=d.get("missingActionRounds", 0),
            illegal_action_count=d.get("illegalActionCount", 0),
            penalty_score=d.get("penaltyScore", 0),
            break_order_ready=bool(d.get("breakOrderReady")),
            rush_tactic_used_count=d.get("rushTacticUsedCount", 0),
            buffs=[Buff.from_dict(b) for b in d.get("buffs") or []],
            current_process=CurrentProcess.from_dict(cp) if isinstance(cp, dict) else None,
            resources=dict(d.get("resources") or {}),
            total_score=d.get("totalScore", 0),
            task_score=d.get("taskScore", 0),
            bounty_score=d.get("bountyScore", 0),
            score_detail=dict(d.get("scoreDetail") or {}),
        )


@dataclass
class Guard:
    owner_team_id: str = ""
    defense: int = 0
    initial_defense: int = 0
    max_defense: int = 0
    complete_round: int = 0
    age_round: int = 0
    active: bool = False

    @staticmethod
    def from_dict(d: dict) -> "Guard":
        owner = d.get("ownerTeamId") or ""
        defense = d.get("defense") or 0
        active = d.get("active")
        if active is None:
            # 实测样例 guard 不下发 active，按附录 C 口径推导：有归属且防守值 > 0
            active = bool(owner) and isinstance(defense, (int, float)) and defense > 0
        return Guard(
            owner_team_id=owner,
            defense=defense,
            initial_defense=d.get("initialDefense", 0),
            max_defense=d.get("maxDefense", 0),
            complete_round=d.get("completeRound", 0),
            age_round=d.get("ageRound", 0),
            active=bool(active),
        )


@dataclass
class NodeState:
    """站点每帧公开状态（附录 C）。静态属性（坐标/类型）以 start 的 Node 为准。"""
    node_id: str = ""
    process_type: str = ""
    process_round: int = 0
    guard: Guard | None = None
    resource_stock: dict[str, int] = field(default_factory=dict)
    scouted: list[dict] = field(default_factory=list)   # 探路标记，动态结构保留原样
    has_obstacle: bool = False
    obstacle_type: str = ""
    obstacle_residue: dict | None = None
    can_window: bool = False
    effective_combat_count: int = 0
    guard_block_count: int = 0
    key_pass_combat_count: int = 0

    @staticmethod
    def from_dict(d: dict) -> "NodeState":
        g = d.get("guard")
        return NodeState(
            node_id=d.get("nodeId", ""),
            process_type=d.get("processType") or "",
            process_round=d.get("processRound", 0),
            guard=Guard.from_dict(g) if isinstance(g, dict) else None,
            resource_stock=dict(d.get("resourceStock") or {}),
            scouted=list(d.get("scouted") or []),
            has_obstacle=bool(d.get("hasObstacle")),
            obstacle_type=d.get("obstacleType") or "",
            obstacle_residue=d.get("obstacleResidue") if isinstance(d.get("obstacleResidue"), dict) else None,
            can_window=bool(d.get("canWindow")),
            effective_combat_count=d.get("effectiveCombatCount", 0),
            guard_block_count=d.get("guardBlockCount", 0),
            key_pass_combat_count=d.get("keyPassCombatCount", 0),
        )


@dataclass
class Task:
    """皇榜任务实例（inquire.tasks[]）。完成任务统一发 CLAIM_TASK + taskId。"""
    task_id: str = ""
    task_template_id: str = ""
    name: str = ""
    node_id: str = ""
    route_bucket: str = ""
    process_type: str = ""
    process_round: int = 0
    score: int = 0
    refresh_round: int = 0
    expire_round: int = 0        # 0 = 无自然过期
    active: bool = False
    completed: bool = False
    failed: bool = False
    owner_player_id: int = 0
    protection_player_id: int = 0

    @staticmethod
    def from_dict(d: dict) -> "Task":
        return Task(
            task_id=d.get("taskId", ""),
            task_template_id=d.get("taskTemplateId", ""),
            name=d.get("name", ""),
            node_id=d.get("nodeId", ""),
            route_bucket=d.get("routeBucket") or "",
            process_type=d.get("processType", ""),
            process_round=d.get("processRound", 0),
            score=d.get("score", 0),
            refresh_round=d.get("refreshRound", 0),
            expire_round=d.get("expireRound", 0),
            active=bool(d.get("active")),
            completed=bool(d.get("completed")),
            failed=bool(d.get("failed")),
            owner_player_id=d.get("ownerPlayerId", 0),
            protection_player_id=d.get("protectionPlayerId", 0),
        )


@dataclass
class Bounty:
    bounty_id: str = ""
    bounty_type: str = ""        # KEY_BOUNTY / NORMAL_BOUNTY / GUARD_BREAK ...
    node_id: str = ""
    owner_team_id: str = ""
    trigger_round: int = 0
    reward_score: int = 0
    reward_resource_type: str = ""
    active: bool = False
    completed: bool = False
    winner_player_id: int = 0

    @staticmethod
    def from_dict(d: dict) -> "Bounty":
        return Bounty(
            bounty_id=d.get("bountyId", ""),
            bounty_type=d.get("bountyType", ""),
            node_id=d.get("nodeId", ""),
            owner_team_id=d.get("ownerTeamId") or "",
            trigger_round=d.get("triggerRound", 0),
            reward_score=d.get("rewardScore", 0),
            reward_resource_type=d.get("rewardResourceType") or "",
            active=bool(d.get("active")),
            completed=bool(d.get("completed")),
            winner_player_id=d.get("winnerPlayerId", 0),
        )


@dataclass
class Contest:
    """窗口争夺（inquire.contests[]）。initial*/cards 等动态字段留在 raw 里按需取。"""
    contest_id: str = ""
    contest_type: str = ""       # RESOURCE / TASK / GATE / DOCK / PASS / OBSTACLE
    target_node_id: str = ""
    resource_type: str = ""
    task_id: str = ""
    red_player_id: int = 0
    blue_player_id: int = 0
    initiator_player_id: int = 0
    round_index: int = 0
    total_rounds: int = 0
    red_point: int = 0
    blue_point: int = 0
    deadline_round: int = 0
    resolved: bool = False
    winner_team_id: str = ""
    status: str = ""             # SUPPRESSED = 平局抑制中，勿出牌
    suppress_until_round: int = 0
    raw: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "Contest":
        return Contest(
            contest_id=d.get("contestId", ""),
            contest_type=d.get("contestType", ""),
            target_node_id=d.get("targetNodeId") or "",
            resource_type=d.get("resourceType") or "",
            task_id=d.get("taskId") or "",
            red_player_id=d.get("redPlayerId", 0),
            blue_player_id=d.get("bluePlayerId", 0),
            initiator_player_id=d.get("initiatorPlayerId", 0),
            round_index=d.get("roundIndex", 0),
            total_rounds=d.get("totalRounds", 0),
            red_point=d.get("redPoint", 0),
            blue_point=d.get("bluePoint", 0),
            deadline_round=d.get("deadlineRound", 0),
            resolved=bool(d.get("resolved")),
            winner_team_id=d.get("winnerTeamId") or "",
            status=d.get("status") or "",
            suppress_until_round=d.get("suppressUntilRound", 0),
            raw=d,
        )

    def involves(self, player_id: int) -> bool:
        return player_id in (self.red_player_id, self.blue_player_id)


@dataclass
class WeatherEvent:
    weather_id: str = ""
    type: str = ""               # HOT / HEAVY_RAIN / MOUNTAIN_FOG
    region: str = ""             # ALL / WATER / MOUNTAIN
    remain_round: int = 0        # 仅 active
    start_round: int = 0         # 仅 forecast
    duration_round: int = 0      # 仅 forecast

    @staticmethod
    def from_dict(d: dict) -> "WeatherEvent":
        return WeatherEvent(
            weather_id=d.get("weatherId", ""),
            type=d.get("type", ""),
            region=d.get("region", ""),
            remain_round=d.get("remainRound", 0),
            start_round=d.get("startRound", 0),
            duration_round=d.get("durationRound", 0),
        )


@dataclass
class Event:
    """公开事件（附录 F）。payload 动态结构，按 type 自行取字段。"""
    event_id: str = ""
    type: str = ""
    round: int = 0
    error_code: str = ""
    payload: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "Event":
        payload = dict(d.get("payload") or {})
        return Event(
            event_id=d.get("eventId", ""),
            type=d.get("type", ""),
            round=d.get("round", 0),
            error_code=d.get("errorCode") or payload.get("errorCode") or "",
            payload=payload,
        )


@dataclass(frozen=True)
class ScoutMarkerEvent:
    """探路标记事件的策略层投影。"""
    event_id: str = ""
    type: str = ""
    player_id: int = 0
    target_node_id: str = ""
    expire_round: int = 0


@dataclass(frozen=True)
class WindowCardReveal:
    """窗口明牌事件的策略层投影。"""
    event_id: str = ""
    contest_id: str = ""
    round_index: int = 0
    red_card: str = ""
    blue_card: str = ""
    winner: str = ""


@dataclass
class ActionResult:
    """上一帧动作结果摘要（第 10 章）。accepted=False 时读 error_code。"""
    round: int = 0
    player_id: int = 0
    action: str = ""
    accepted: bool = False
    result: str = ""
    error_code: str = ""
    message: str = ""

    @staticmethod
    def from_dict(d: dict) -> "ActionResult":
        return ActionResult(
            round=d.get("round", 0),
            player_id=d.get("playerId", 0),
            action=d.get("action", ""),
            accepted=bool(d.get("accepted")),
            result=d.get("result", ""),
            error_code=d.get("errorCode") or "",
            message=d.get("message") or "",
        )


# ---------- GameState 主体 ----------

class GameState:
    """每帧世界快照。update_start 一局一次，update_inquire 每帧调用。"""

    def __init__(self, player_id: int) -> None:
        self.player_id = player_id

        # --- start 静态（一局不变）---
        self.match_id = ""
        self.rules_version = ""
        self.duration_round = 600
        self.map_id = ""
        self.roles = MapRoles()
        self.nodes: dict[str, Node] = {}                  # nodeId → 静态站点
        self.edges: dict[str, Edge] = {}                  # edgeId → 路线边
        self.resource_specs: list[ResourceSpec] = []
        self.process_nodes: dict[str, ProcessNode] = {}   # nodeId → 处理点
        self.task_templates: dict[str, TaskTemplate] = {} # templateId → 模板
        self.task_candidates: dict[str, list[str]] = {}   # templateId → 候选站点
        self.route_task_buckets: dict[str, list[str]] = {}
        self.obstacle_candidate_node_ids: list[str] = []
        self.my_team_id = ""                              # RED / BLUE
        self.opponent_id = 0

        # --- inquire 运行时（每帧覆盖）---
        self.round = 0
        self.phase = ""                                   # NORMAL / RUSH / ENDED
        self.players: dict[int, PlayerState] = {}
        self.me = PlayerState(player_id=player_id)
        self.opponent = PlayerState()
        self.node_states: dict[str, NodeState] = {}
        self.weather_active: list[WeatherEvent] = []
        self.weather_forecast: list[WeatherEvent] = []
        self.tasks: list[Task] = []
        self.bounties: list[Bounty] = []
        self.contests: list[Contest] = []
        self.events: list[Event] = []
        self.action_results: list[ActionResult] = []
        self.score_preview: dict[str, int] = {}

    # -- start --

    def update_start(self, data: dict) -> None:
        self.match_id = data.get("matchId", "")
        self.rules_version = data.get("rulesVersion", "")
        self.duration_round = data.get("durationRound", 600)

        map_data = data.get("map") or {}
        gameplay = map_data.get("gameplay") or {}
        self.map_id = map_data.get("mapId", "")
        self.roles = MapRoles.from_dict(gameplay.get("roles") or {})

        # 顶层优先，缺失/为空回退 map 内层（实测样例顶层 resources/taskTemplates 为空）
        nodes = data.get("nodes") or map_data.get("nodes") or []
        edges = data.get("edges") or map_data.get("edges") or []
        resources = data.get("resources") or gameplay.get("resources") or []
        self.nodes = {n.node_id: n for n in (Node.from_dict(x) for x in nodes)}
        self.edges = {e.edge_id: e for e in (Edge.from_dict(x) for x in edges)}
        self.resource_specs = [ResourceSpec.from_dict(x) for x in resources]
        self.process_nodes = {p.node_id: p for p in
                              (ProcessNode.from_dict(x) for x in gameplay.get("processNodes") or [])}
        self.task_templates = {t.task_template_id: t for t in
                               (TaskTemplate.from_dict(x) for x in data.get("taskTemplates") or [])}
        self.task_candidates = {k: list(v) for k, v in (gameplay.get("taskCandidates") or {}).items()}
        self.route_task_buckets = {k: list(v) for k, v in (gameplay.get("routeTaskBuckets") or {}).items()}
        self.obstacle_candidate_node_ids = list(gameplay.get("obstacleCandidateNodeIds") or [])

        for p in data.get("players") or []:
            pid = p.get("playerId")
            if pid == self.player_id:
                self.my_team_id = p.get("teamId", "")
            elif isinstance(pid, int):
                self.opponent_id = pid

    # -- inquire --

    def update_inquire(self, data: dict) -> None:
        self.round = data.get("round", self.round)
        self.phase = data.get("phase", "")

        self.players = {}
        for p in data.get("players") or []:
            ps = PlayerState.from_dict(p)
            self.players[ps.player_id] = ps
        self.me = self.players.get(self.player_id, self.me)
        if self.opponent_id in self.players:
            self.opponent = self.players[self.opponent_id]
        else:  # start 里没识别到对手时兜底：取第一个非本方玩家
            for pid, ps in self.players.items():
                if pid != self.player_id:
                    self.opponent, self.opponent_id = ps, pid
                    break

        self.node_states = {ns.node_id: ns for ns in
                            (NodeState.from_dict(x) for x in data.get("nodes") or [])}
        # 边表每帧同步；某帧缺失沿用已有（协议第 7 章：回退 start.edges[]）
        edges = data.get("edges")
        if edges:
            self.edges = {e.edge_id: e for e in (Edge.from_dict(x) for x in edges)}

        weather = data.get("weather") or {}
        self.weather_active = [WeatherEvent.from_dict(x) for x in weather.get("active") or []]
        self.weather_forecast = [WeatherEvent.from_dict(x) for x in weather.get("forecast") or []]

        self.tasks = [Task.from_dict(x) for x in data.get("tasks") or []]
        self.bounties = [Bounty.from_dict(x) for x in data.get("bounties") or []]
        self.contests = [Contest.from_dict(x) for x in data.get("contests") or []]
        self.events = [Event.from_dict(x) for x in data.get("events") or []]
        self.action_results = [ActionResult.from_dict(x) for x in data.get("actionResults") or []]
        self.score_preview = dict(data.get("scorePreview") or {})

    # -- 常用派生查询 --

    def my_action_results(self) -> list[ActionResult]:
        return [r for r in self.action_results if r.player_id == self.player_id]

    def my_events(self) -> list[Event]:
        return [e for e in self.events if e.payload.get("playerId") == self.player_id]

    def scout_marker_events(self) -> list[ScoutMarkerEvent]:
        """Return normalized scout marker events from the current frame."""
        out: list[ScoutMarkerEvent] = []
        for e in self.events:
            if e.type not in ("SCOUT_MARKER_ADD", "SCOUT_MARKER_EXPIRE", "SCOUT_MARKER_CONSUME"):
                continue
            out.append(ScoutMarkerEvent(
                event_id=e.event_id,
                type=e.type,
                player_id=e.payload.get("playerId", 0),
                target_node_id=e.payload.get("targetNodeId") or e.payload.get("nodeId") or "",
                expire_round=e.payload.get("expireRound", 0),
            ))
        return out

    def window_card_reveals(self) -> list[WindowCardReveal]:
        """Return normalized WINDOW_CARD_REVEAL events from the current frame."""
        out: list[WindowCardReveal] = []
        for e in self.events:
            if e.type != "WINDOW_CARD_REVEAL":
                continue
            out.append(WindowCardReveal(
                event_id=e.event_id,
                contest_id=e.payload.get("contestId", ""),
                round_index=e.payload.get("roundIndex", 0),
                red_card=e.payload.get("redCard", ""),
                blue_card=e.payload.get("blueCard", ""),
                winner=e.payload.get("winner", ""),
            ))
        return out

    def my_state(self) -> str:
        return self.me.state

    @property
    def my_guard_points(self) -> int:
        return self.me.guard_action_point

    @property
    def my_good(self) -> int:
        return self.me.good_fruit

    @property
    def my_bad(self) -> int:
        return self.me.bad_fruit

    def enemy_guard_at(self, node_id: str) -> Guard | None:
        ns = self.node_states.get(node_id)
        if ns is None or ns.guard is None:
            return None
        guard = ns.guard
        my_team = self.my_team_id or self.me.team_id
        if guard.active and guard.defense > 0 and guard.owner_team_id and guard.owner_team_id != my_team:
            return guard
        return None

    def blocked_by_guard(self) -> str | None:
        """Return the likely target node when our last MOVE was blocked by a guard."""
        saw_block = False
        for e in self.my_events():
            if e.type == "ACTION_REJECTED" and e.error_code == "MOVE_BLOCKED_BY_GUARD":
                saw_block = True
                target = e.payload.get("targetNodeId") or e.payload.get("toNodeId")
                if target:
                    return target
        for r in self.my_action_results():
            if r.action == "MOVE" and not r.accepted and r.error_code == "MOVE_BLOCKED_BY_GUARD":
                saw_block = True
        if not saw_block:
            return None
        if self.me.next_node_id:
            return self.me.next_node_id
        guarded = [node_id for node_id, _ in self.neighbors(self.me.current_node_id)
                   if self.enemy_guard_at(node_id) is not None]
        return guarded[0] if len(guarded) == 1 else None

    def my_contests(self) -> list[Contest]:
        """本方在场且未结算、未被抑制的窗口。"""
        return [c for c in self.contests
                if c.involves(self.player_id) and not c.resolved and c.status != "SUPPRESSED"]

    def my_open_contests(self) -> list[Contest]:
        return self.my_contests()

    def neighbors(self, node_id: str) -> list[tuple[str, Edge]]:
        """相邻可达 (节点, 边) 列表，尊重单向边。"""
        result = []
        for edge in self.edges.values():
            if edge.from_node == node_id:
                result.append((edge.to_node, edge))
            elif edge.bidirectional and edge.to_node == node_id:
                result.append((edge.from_node, edge))
        return result
