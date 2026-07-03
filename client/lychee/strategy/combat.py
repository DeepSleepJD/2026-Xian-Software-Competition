"""对抗层：攻坚破卡 + 窗口出牌。

核心规则：
- 任务书 6.3.1：攻坚只能打当前相邻节点的敌方有效设卡，且当帧结算。
- 任务书 8.2：MOVING 不能攻坚，所以上边前发现下一跳有守卫时必须拦截 MOVE。
- 窗口出牌独立于主车队动作，但每张牌必须带 contestId + card。
"""

from math import ceil

from .. import pathing
from ..state import Contest, GameState
from . import Intent, Strategy, safety
from .economy import RESOURCE_BASE_VALUES, RESOURCE_CLAIM_CAPS, _task_points

PRIORITY_COMBAT_MAIN = 130
# 设卡让位经济动作（P4/07-03 复盘：现网两连败均在咽喉先 SET_GUARD 再抢任务，
# 30 分任务被对手先锁；设卡本身两局 bounty=0 纯亏）。落在 economy(110) 与
# delivery(100) 之间：有抢任务/领资源/用冰鉴/用马时先做，无经济动作时（raw 拿满/
# 无可行任务）设卡仍先于纯走位触发，保留巡航中在咽喉设卡的能力。破卡/削卡/清障不动。
PRIORITY_SET_GUARD = 108
PRIORITY_SQUAD_WEAKEN = 128
PRIORITY_SQUAD_REINFORCE = 127   # 维持拦截卡 > 预清障 > 探路；squad 类别每帧仅一动作，
                                 # 由 propose 回退链 weaken→reinforce→clear→scout 保证次序
PRIORITY_SQUAD_CLEAR = 127
PRIORITY_SQUAD_SCOUT = 127
PRIORITY_WINDOW_CARD = 125

_STATIONARY_STATES = {"IDLE", "WAITING"}
_KEY_CONTEST_SCORES = {"GATE": 50, "PASS": 45, "DOCK": 40}
DOCUMENT_RESOURCES = ("PASS_TOKEN", "OFFICIAL_PERMIT")
HORSE_RESOURCES = ("FAST_HORSE", "SHORT_HORSE")
FREE_QIANG_XING_BUFFS = frozenset({"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"})
CARD_COUNTERS = {
    "YAN_DIE": ("BING_ZHENG", "XIAN_GONG"),
    "QIANG_XING": ("BING_ZHENG", "YAN_DIE"),
    "XIAN_GONG": ("QIANG_XING",),
    "BING_ZHENG": ("XIAN_GONG",),
}
SCOUT_MIN_PROC_FRAMES = 4
SCOUT_ETA_MAX = 25
SCOUT_GATE_ETA_SLACK = 45
SCOUT_LAND_MARGIN = 2
SCOUT_PENDING_TIMEOUT = 16
SQUAD_RESERVE_BEFORE_GATE = 6  # 用户铁律（2026-07-03）：宫门验核前永远留 ≥6 支小分队——
                               # 削穿一张满防卡（防御 6）需 6 支（2 支/次削 2 防），
                               # 被终点前设卡钉死比探路省帧致命；验核后设卡威胁消失
SQUAD_RESERVE_LOCKED = 2       # P4m：对手被我方有效卡锁死在竞争咽喉远侧时，6 支保险
                               # 所防的威胁被结构性排除，降为 2 腾 4 支给 G3 REINFORCE
REINFORCE_SQUAD_FLOOR = 2       # G3：增援后至少留这么多支（防一张卡吃光人手、下张无兵/无法削卡）
CLEAR_SQUAD_FLOOR = 4           # 预清障后至少留这么多支（护满防削卡预算 6 支的大部分）
CLEAR_PENDING_TIMEOUT = SCOUT_PENDING_TIMEOUT  # 预清派队去重超时（复用探路）
# G6 动态好果地板（拦截封锁流 §6.5）：满防卡仅烧 ≤3 好果，freeze EV 远超好果分损；
# 40 保护交付好果主体（好果<42 才拦设卡），不再像旧值 90 近乎不设卡。旋钮：回 90 即
# 一键退化到近乎不设卡。
GUARD_GOOD_FLOOR = 40
# P4m 第四刀·滚动设卡（用户点名"领先帧数足够就连续设卡"）：
ROLLING_GUARD_MIN_LEAD = 20        # 对手到本咽喉 ETA ≥此值才先手设卡——4 帧读条期间他追
                                   # 不上；更近时留给 set-on-commit 半路关门（冻结更狠）
ROLLING_GUARD_MIN_ARRIVAL_DEF = 3  # 对手到达时卡剩余防值下限：太远的卡到货前风化成渣=白设
GUARD_GOOD_FRAME_COST = 15
GUARD_MIN_NET_FRAMES = 30


class CombatStrategy(Strategy):
    def __init__(self, economy=None) -> None:
        self._scout_markers: dict[str, int] = {}
        self._scout_pending: dict[str, int] = {}
        self._clear_pending: dict[str, int] = {}
        self._seen_window_reveals: set[str] = set()
        self._last_window_cards: dict[str, tuple[int, str, str]] = {}
        self._opponent_card_counts: dict[str, int] = {}
        self._opponent_card_total = 0
        # P4m 削卡止损：对手会增援的证据（本局粘滞）+ 敌卡防值追踪（兜底探测）
        self._opp_reinforces = False
        self._enemy_guard_defense: dict[str, int] = {}
        self._economy = economy

    def propose(self, state: GameState) -> list[Intent]:
        if state.me.delivered or state.me.retired:
            return []

        self._read_events(state)

        intents: list[Intent] = []
        main = self._propose_break_guard(state)
        if main is None:
            main = self._propose_clear_obstacle(state)
        if main is None and not safety.delivery_deadline_hit(state):
            # 送达死线（路程线∪鲜度线）：吃紧时设卡（4 帧架设+烧好果）纯亏，让路直冲；
            # 攻坚/削卡/清障/探路保留——只处理终点路径上的阻挡，是送达的一部分
            main = self._propose_set_guard(state)
        if main is not None:
            intents.append(main)

        squad = self._propose_squad_weaken(state)
        if squad is None:
            squad = self._propose_squad_reinforce(state)
        if squad is None:
            squad = self._propose_squad_clear(state)
        if squad is None:
            squad = self._propose_squad_scout(state)
        if squad is not None:
            intents.append(squad)

        cards = self._propose_window_cards(state)
        if cards:
            intents.append(Intent(kind="combat.window", priority=PRIORITY_WINDOW_CARD,
                                  actions=cards, note="窗口出牌"))
        return intents

    def _propose_break_guard(self, state: GameState) -> Intent | None:
        me = state.me
        if me.current_process is not None:
            return None
        if state.my_state() not in _STATIONARY_STATES:
            return None
        # 任务书 8.2：半路视同 MOVING，攻坚非法。被守卫拦停时服务器置
        # WAITING+PAUSED 且 nextNodeId 保留（P4d 死锁根因①），不能当停稳；
        # nextNodeId 非空即在边上，PAUSED 兜底字段组合变体
        if me.next_node_id or me.move_direction == "PAUSED":
            return None
        cur = me.current_node_id
        if not cur:
            return None

        target = self._guarded_next_hop(state, cur)
        if not target:
            return None
        guard = state.enemy_guard_at(target)
        if guard is None:
            return None

        action = self._break_action(state, target, guard.defense)
        if action is None:
            return None
        note = f"攻坚破卡@{target}"
        return Intent(kind="combat", priority=PRIORITY_COMBAT_MAIN, actions=[action], note=note)

    def _guarded_next_hop(self, state: GameState, cur: str) -> str:
        blocked = state.blocked_by_guard()
        if blocked and self._is_neighbor(state, cur, blocked) and state.enemy_guard_at(blocked):
            return blocked

        path = self._terminal_path(state, cur)
        if path and len(path) >= 2 and state.enemy_guard_at(path[1]):
            return path[1]

        guarded = [node_id for node_id, _ in state.neighbors(cur)
                   if state.enemy_guard_at(node_id) is not None]
        if len(guarded) == 1 and self._is_terminal_choke(state, cur, guarded[0]):
            return guarded[0]
        return ""

    def _break_action(self, state: GameState, target: str, defense: int) -> dict | None:
        bad = min(2, state.my_bad, ceil(defense / 3))
        remain = max(0, defense - bad * 3)
        good = min(2, state.my_good, ceil(remain / 2)) if remain > 0 else 0
        attack = bad * 3 + good * 2
        if attack <= 0:
            return None
        action = {
            "action": "BREAK_GUARD",
            "targetNodeId": target,
            "goodFruit": good,
            "badFruit": bad,
        }
        can_break_order = (
            state.phase == "RUSH"
            and state.me.break_order_ready
            and state.me.rush_tactic_used_count < 1
            and attack < defense
            and defense - attack <= 3
        )
        if can_break_order:
            action["rushTactic"] = "BREAK_ORDER"
        # P4m 一击闸：火力不足以清零且对手还能远程增援（SQUAD_REINFORCE 不限距离、
        # 同帧序先于削弱落地）时不出手——半血卡会被 +2 回满，白丢果子还休整 5 帧；
        # 攻坚值 ≥ 防值则一击清零，清零的卡失效移除、增援不可复活（任务书 936/970）
        effective = attack + (3 if can_break_order else 0)
        if effective < defense and self._opp_can_repump(state):
            return None
        return action

    @staticmethod
    def _opp_can_repump(state: GameState) -> bool:
        """对手能否把半血卡增援回去：未交付/未退赛且有 ≥2 支小分队；RUSH 后
        禁新提交小分队动作（任务书 1157），增援威胁消失。"""
        opp = state.opponent
        return (opp is not None and not opp.delivered and not opp.retired
                and opp.squad_available >= 2 and state.phase != "RUSH")

    def _propose_clear_obstacle(self, state: GameState) -> Intent | None:
        """主车队清障（任务书 2.4.4/5.2 动作表）：交付路径下一跳被道路障碍挡住时
        花 6 帧读条 + 1 好果清掉。障碍开局生成、不清不消（P4d 实测：咽喉障碍无人清
        = MOVE 永拒 = 永久卡死未送达）。小分队清障（2 支）不用——人手全留给削卡，
        它是半路被守卫暂停时唯一的快速清卡手段。"""
        me = state.me
        if me.current_process is not None:
            return None
        if state.my_state() not in _STATIONARY_STATES:
            return None
        if me.next_node_id or me.move_direction == "PAUSED":
            return None
        cur = me.current_node_id
        if not cur or state.my_good < 1:
            return None
        path = self._terminal_path(state, cur)
        if not path or len(path) < 2:
            return None
        target = path[1]
        ns = state.node_states.get(target)
        if ns is None or not ns.has_obstacle:
            return None
        action = {"action": "CLEAR", "targetNodeId": target}
        return Intent(kind="combat.clear", priority=PRIORITY_COMBAT_MAIN,
                      actions=[action], note=f"清障@{target}")

    def _propose_set_guard(self, state: GameState) -> Intent | None:
        me = state.me
        if state.phase != "NORMAL" or me.verified:
            return None
        if me.current_process is not None or me.state != "IDLE":
            return None
        # G6 放宽领先闸（拦截封锁流 §1 EV：领先也要拦，freeze 远值过 10/18 悬赏喂分）；
        # 只保留"已领先且对手已判死"时不再徒增悬赏的弱化版
        if me.total_score > state.opponent.total_score and safety.opponent_cannot_finish(state):
            return None
        cur = me.current_node_id
        if not cur or self._is_terminal(state, cur) or self._has_active_guard(state, cur):
            return None
        node = state.nodes.get(cur)
        if node is None or node.node_type not in ("KEY_PASS", "PASS"):
            return None
        if self._friendly_guard_count(state) >= 2:
            return None
        if not self._ahead_of_opponent(state, cur):
            return None
        if not self._is_opponent_choke(state, cur):
            return None
        extra, defense, good_cost = self._guard_investment(state, cur)
        if defense < 4:
            return None
        # set-on-commit 时序闸（§6.4）：对手已 commit 上边、到站前设卡能生效 → 半路
        # 关门（最狠：冻结态攻坚/强通全废，M2 实证只剩改道绕行）。
        # P4m 第四刀·滚动设卡：对手未 commit 但我领先足够（4 帧读条期间他追不上、
        # 到货时卡还有肉）→ 先手关门再走。他到卡前只能节点上强通吃时间税/烧果攻坚，
        # 我 4 帧 + ≤3 好果换他 ≥30 帧或等值资源；沿途每个咽喉如此 = "连续设卡"，
        # 上限 2 张在场（任务书 921）由上方 _friendly_guard_count 闸把守。
        delay = self._guard_weathering_frames(state, cur, defense)
        if not safety.freeze_window_open(state, cur):
            opp_eta = safety.opp_eta(state, cur)
            if opp_eta < ROLLING_GUARD_MIN_LEAD or opp_eta >= 10 ** 8:
                return None
            arrival_def = defense - self._weathering_decays(state, cur, defense, opp_eta)
            if arrival_def < ROLLING_GUARD_MIN_ARRIVAL_DEF:
                return None   # 到货前风化成渣 = 白设（对手太远不值先手）
            # 先手卡对他的价值 = 他到达时刻卡的剩余风化寿命（等要等这么久；
            # 强通税/攻坚烧果是等值资源替代，口径与 set-on-commit 一致）
            delay = max(0, delay - opp_eta)
        net = delay - safety.GUARD_SETUP_FRAMES - good_cost * GUARD_GOOD_FRAME_COST
        if net < GUARD_MIN_NET_FRAMES:
            return None
        action = {"action": "SET_GUARD", "targetNodeId": cur, "extraGoodFruit": extra}
        return Intent(kind="combat.guard", priority=PRIORITY_SET_GUARD,
                      actions=[action], note=f"设卡@{cur}")

    @staticmethod
    def _weathering_decays(state: GameState, node_id: str, defense: int,
                           frames_ahead: int) -> int:
        """从设卡完成起 frames_ahead 帧内会发生几次风化 -1（任务书 924-936）。"""
        node = state.nodes.get(node_id)
        first = 45 if node and node.node_type == "KEY_PASS" and defense >= 4 else 30
        if frames_ahead < first:
            return 0
        return 1 + (frames_ahead - first) // 30

    def _propose_squad_weaken(self, state: GameState) -> Intent | None:
        me = state.me
        if state.phase == "RUSH":
            return None
        # 被守卫拦停（WAITING+PAUSED）时削卡是唯一快速清卡手段，只认 MOVING
        # 会导致只剩干等风化（P4d 死锁根因②）
        en_route = bool(me.next_node_id) and (
            me.state == "MOVING" or me.move_direction == "PAUSED")
        if not en_route:
            return None
        guard = state.enemy_guard_at(me.next_node_id)
        if guard is None or me.squad_available < 2:
            return None
        # P4m 止损闸：对手已证实会增援且还有兵——削卡消耗战必败（同帧序增援(1)
        # 先于削弱(2)落地，13:22 局 6 支白扔反把卡续长 60 帧）。首支削卡照常放行
        # 当探针，对手的增援反应会置位 _opp_reinforces
        if self._opp_reinforces and self._opp_can_repump(state):
            return None
        needed = ceil(guard.defense / 2)
        if me.squad_in_flight >= needed:
            return None
        action = {"action": "SQUAD_WEAKEN", "targetNodeId": me.next_node_id}
        return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_WEAKEN,
                      actions=[action], note=f"小分队削卡@{me.next_node_id}")

    def _propose_squad_reinforce(self, state: GameState) -> Intent | None:
        """G3 维持拦截卡：己方仍挡在对手前面的有效卡被削/风化到低于上限时，
        SQUAD_REINFORCE(+2/次，不限距离) 补回来——前压后仍能远程增援身后冻结卡。
        只补"仍是对手必经咽喉"的卡（对手已越过的卡补了白费）。"""
        me = state.me
        if state.phase == "RUSH":
            return None
        # 铁律：增援同样不得击穿验核前 6 支保留（对手被锁死时 _squad_reserve 降 2 自然放开）
        if me.squad_available - 2 < max(self._squad_reserve(state), REINFORCE_SQUAD_FLOOR):
            return None
        my_team = state.my_team_id or state.me.team_id
        for node_id, ns in state.node_states.items():
            guard = ns.guard
            if not (guard and guard.active and guard.defense > 0
                    and guard.owner_team_id == my_team):
                continue
            target = pathing.guard_max_defense(state, node_id)
            if guard.defense >= target:
                continue
            if not self._is_opponent_choke(state, node_id):
                continue
            needed = ceil((target - int(guard.defense)) / 2)
            if me.squad_in_flight >= needed:
                return None
            action = {"action": "SQUAD_REINFORCE", "targetNodeId": node_id}
            return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_REINFORCE,
                          actions=[action], note=f"小分队增援@{node_id}")
        return None

    def _propose_squad_clear(self, state: GameState) -> Intent | None:
        """小队提前破障：交付路径上 2+ 跳外的障碍(path[1] 留主车队反应式 CLEAR)派小分队
        并行预清，主车队到站不再停 6 帧清障、也免咽喉障碍卡死风险(SQUAD_CLEAR 延迟清除、
        2 支、清障方使对手 30 帧内过该点 +6 残留税)。留 CLEAR_SQUAD_FLOOR 支护削卡。"""
        me = state.me
        if state.phase == "RUSH":
            return None
        # 铁律：预清障同样不得击穿验核前 6 支保留（P4m 陪练局实证：r1-2 两次预清
        # 8→4，削卡本钱只剩两刀，差 2 防干等风化 70 帧）。8 满编时首次预清仍放行
        if me.squad_available - 2 < max(self._squad_reserve(state), CLEAR_SQUAD_FLOOR):
            return None
        cur = me.current_node_id
        if not cur:
            return None
        path = self._terminal_path(state, cur)
        if not path or len(path) < 3:
            return None
        for node_id in path[2:]:
            ns = state.node_states.get(node_id)
            if ns is None or not ns.has_obstacle:
                continue
            if self._has_active_clear_task(state, node_id):
                continue    # 有 T04 清障任务 → 留给做任务的清(领任务分)，别白派小分队
            pending = self._clear_pending.get(node_id)
            if pending is not None and pending + CLEAR_PENDING_TIMEOUT >= state.round:
                continue
            self._clear_pending[node_id] = state.round
            return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_CLEAR,
                          actions=[{"action": "SQUAD_CLEAR", "targetNodeId": node_id}],
                          note=f"小分队预清障@{node_id}")
        return None

    @staticmethod
    def _has_active_clear_task(state: GameState, node_id: str) -> bool:
        for t in state.tasks:
            if not t.active or t.completed or t.failed or t.node_id != node_id:
                continue
            if t.process_type == "CLEAR_OBSTACLE" or t.task_template_id == "T04":
                return True
        return False

    def _propose_squad_scout(self, state: GameState) -> Intent | None:
        me = state.me
        if state.phase == "RUSH":
            return None
        if me.squad_available - 1 < self._squad_reserve(state):
            return None
        cur = me.current_node_id
        if not cur:
            return None

        candidates: list[tuple[int, str]] = []
        seen: set[str] = set()

        path = self._terminal_path(state, cur)
        if path and len(path) >= 2:
            for idx, node_id in enumerate(path[1:], start=1):
                proc = state.process_nodes.get(node_id)
                if proc is None or proc.process_round < SCOUT_MIN_PROC_FRAMES:
                    continue
                candidates.append((self._eta_to_path_index(state, path[:idx + 1]), node_id))
                seen.add(node_id)

        plan = getattr(self._economy, "current_plan", None)
        if plan:
            spot, proc_frames = plan
            if spot not in seen and proc_frames >= SCOUT_MIN_PROC_FRAMES:
                spot_path = pathing.shortest_path(state, cur, spot)
                if spot_path and len(spot_path) >= 2:
                    candidates.append((self._eta_to_path_index(state, spot_path), spot))

        best: tuple[int, str] | None = None
        for eta, node_id in candidates:
            if self._has_scout_marker(state, node_id) or self._has_pending_scout(state, node_id):
                continue
            delay = self._squad_delay(state, cur, node_id)
            eta_cap = delay + SCOUT_GATE_ETA_SLACK if self._is_gate_like(state, node_id) \
                else SCOUT_ETA_MAX
            if not (delay + SCOUT_LAND_MARGIN <= eta <= eta_cap):
                continue
            if best is None or eta < best[0]:
                best = (eta, node_id)

        if best is None:
            return None
        node_id = best[1]
        self._scout_pending[node_id] = state.round
        action = {"action": "SQUAD_SCOUT", "targetNodeId": node_id}
        return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_SCOUT,
                      actions=[action], note=f"小分队探路@{node_id}")

    def _propose_window_cards(self, state: GameState) -> list[dict]:
        contests = [c for c in state.my_open_contests() if c.contest_id]
        if not contests:
            return []
        scored = [(self._contest_score(state, c), c) for c in contests]
        score, contest = max(scored, key=lambda item: item[0])
        if score <= 0:
            return []
        card = self._choose_window_card(state, contest)
        return [{"action": "WINDOW_CARD", "contestId": contest.contest_id, "card": card}]

    def _choose_window_card(self, state: GameState, contest: Contest) -> str:
        """G7 强制三联献贡（用户决策 2026-07-03）：能出献贡就一律出，不再按对手出牌
        倾向切走（献贡赢验牒+兵征、只输强行；对手要强行须有马/疾行令，出不了几次）。
        仅保留 mirror-break switcher 作镜像同牌死锁（S02 DOCK 0:0，见 [[mirror-dock-deadlock]]）
        的破对称安全阀。鲜度<80 或好果≤1 献贡出不了时退化尽量出牌。"""
        if self._can_play_card(state, contest, "XIAN_GONG"):
            return self._mirror_break_card(state, contest, "XIAN_GONG")
        default = self._first_playable_card(state, contest, ("BING_ZHENG", "YAN_DIE"))
        if default == "ABSTAIN" and self._can_play_free_qiang_xing(state):
            default = "QIANG_XING"
        return self._mirror_break_card(state, contest, default)

    def _first_playable_card(self, state: GameState, contest: Contest,
                             order: tuple[str, ...]) -> str:
        for card in order:
            if self._can_play_card(state, contest, card):
                return card
        return "ABSTAIN"

    def _mirror_break_card(self, state: GameState, contest: Contest, default: str) -> str:
        reveal = self._last_window_cards.get(contest.contest_id)
        if reveal is None:
            return default
        round_index, red_card, blue_card = reveal
        if not contest.round_index or round_index != contest.round_index - 1:
            return default
        if not red_card or red_card != blue_card:
            return default
        same_card = red_card
        switcher = state.player_id == max(contest.red_player_id, contest.blue_player_id)
        if not switcher:
            return same_card if self._can_play_card(state, contest, same_card) else default
        for card in CARD_COUNTERS.get(same_card, ()):
            if self._can_play_card(state, contest, card):
                return card
        return default

    def _can_play_card(self, state: GameState, contest: Contest, card: str) -> bool:
        if card == "BING_ZHENG":
            reserve = 0 if state.phase == "RUSH" or contest.contest_type in ("GATE", "PASS") else 1
            return state.my_guard_points > reserve
        if card == "YAN_DIE":
            return self._document_resource_count(state) >= 1
        if card == "XIAN_GONG":
            return state.me.freshness >= 80 and state.my_good > 1
        if card == "QIANG_XING":
            if self._can_play_free_qiang_xing(state):
                return True
            if self._contest_score(state, contest) < 20:
                return False
            return any(state.me.resources.get(resource_type, 0) > 0
                       for resource_type in HORSE_RESOURCES)
        return False

    @staticmethod
    def _can_play_free_qiang_xing(state: GameState) -> bool:
        return any(b.type in FREE_QIANG_XING_BUFFS and b.remaining_round > 0
                   for b in state.me.buffs)

    @staticmethod
    def _document_resource_count(state: GameState) -> int:
        return sum(state.me.resources.get(resource_type, 0) for resource_type in DOCUMENT_RESOURCES)

    def _read_events(self, state: GameState) -> None:
        self._read_scout_events(state)
        self._read_window_card_reveals(state)
        self._read_reinforce_evidence(state)

    def _read_reinforce_evidence(self, state: GameState) -> None:
        """P4m：对手'会增援'证据探测（本局粘滞）。

        证据一（事件流，派出即证据不等落地）：对手 SQUAD_REINFORCE 派遣/落地事件；
        证据二（兜底）：非新设的敌卡防值不降反升（13:22 局 r317 形态 2→4）。
        """
        if not self._opp_reinforces:
            my_id = state.player_id
            for e in state.events:
                if e.payload.get("playerId") == my_id:
                    continue
                if "REINFORCE" in (e.type or "") \
                        or e.payload.get("action") == "SQUAD_REINFORCE":
                    self._opp_reinforces = True
                    break
        my_team = state.my_team_id or state.me.team_id
        for node_id, ns in state.node_states.items():
            guard = ns.guard
            if guard and guard.active and guard.defense > 0 \
                    and guard.owner_team_id and guard.owner_team_id != my_team:
                prev = self._enemy_guard_defense.get(node_id)
                if prev is not None and guard.defense > prev and guard.age_round > 0:
                    self._opp_reinforces = True
                self._enemy_guard_defense[node_id] = int(guard.defense)
            else:
                self._enemy_guard_defense.pop(node_id, None)

    def _read_scout_events(self, state: GameState) -> None:
        for node_id, expire in list(self._scout_markers.items()):
            if expire and expire < state.round:
                self._scout_markers.pop(node_id, None)
        for node_id, dispatch_round in list(self._scout_pending.items()):
            if dispatch_round + SCOUT_PENDING_TIMEOUT < state.round:
                self._scout_pending.pop(node_id, None)
        for node_id, dispatch_round in list(self._clear_pending.items()):
            if dispatch_round + CLEAR_PENDING_TIMEOUT < state.round:
                self._clear_pending.pop(node_id, None)

        my_player_id = state.player_id
        for event in state.scout_marker_events():
            if event.player_id != my_player_id or not event.target_node_id:
                continue
            if event.type == "SCOUT_MARKER_ADD":
                expire = event.expire_round or state.round + 45
                self._scout_markers[event.target_node_id] = expire
                self._scout_pending.pop(event.target_node_id, None)
            elif event.type in ("SCOUT_MARKER_EXPIRE", "SCOUT_MARKER_CONSUME"):
                self._scout_markers.pop(event.target_node_id, None)
                self._scout_pending.pop(event.target_node_id, None)

    def _read_window_card_reveals(self, state: GameState) -> None:
        for reveal in state.window_card_reveals():
            key = reveal.event_id or f"{reveal.contest_id}:{reveal.round_index}"
            if key in self._seen_window_reveals:
                continue
            self._seen_window_reveals.add(key)
            self._last_window_cards[reveal.contest_id] = (
                reveal.round_index, reveal.red_card, reveal.blue_card)

    def _has_scout_marker(self, state: GameState, node_id: str) -> bool:
        expire = self._scout_markers.get(node_id, 0)
        if expire >= state.round:
            return True
        ns = state.node_states.get(node_id)
        if ns is None:
            return False
        my_player_id = state.player_id
        for marker in ns.scouted:
            player_id = marker.get("playerId", 0)
            expire_round = marker.get("expireRound", 0)
            if player_id == my_player_id and (not expire_round or expire_round >= state.round):
                return True
        return False

    def _has_pending_scout(self, state: GameState, node_id: str) -> bool:
        dispatch_round = self._scout_pending.get(node_id)
        return dispatch_round is not None and dispatch_round + SCOUT_PENDING_TIMEOUT >= state.round

    @staticmethod
    def _squad_reserve(state: GameState) -> int:
        if state.me.verified:
            return 0
        # 铁律（2026-07-03）：验核前恒 6。唯一豁免（P4m 决策#1，已报备）：对手被
        # 我方有效卡锁死在咽喉远侧——6 支保险所防的"被关门"威胁被结构性排除，
        # 降到 2 腾 4 支给 G3 REINFORCE 维持锁门卡
        if safety.opponent_locked(state):
            return SQUAD_RESERVE_LOCKED
        return SQUAD_RESERVE_BEFORE_GATE

    @staticmethod
    def _squad_delay(state: GameState, cur: str, target: str) -> int:
        a, b = state.nodes.get(cur), state.nodes.get(target)
        if a is None or b is None:
            return 15
        d = max(abs(a.x - b.x), abs(a.y - b.y))
        return min(15, max(3, ceil(d / 3)))

    @staticmethod
    def _is_gate_like(state: GameState, node_id: str) -> bool:
        if node_id == state.roles.gate_node_id:
            return True
        proc = state.process_nodes.get(node_id)
        return bool(proc and proc.process_type == "VERIFY")

    @staticmethod
    def _eta_to_path_index(state: GameState, prefix: list[str]) -> int:
        """Estimated frames until arrival at prefix[-1], excluding its processing time."""
        if len(prefix) < 2:
            return 0
        target = prefix[-1]
        target_proc = state.process_nodes.get(target)
        target_proc_frames = target_proc.process_round if target_proc else 0
        frames = max(0, pathing.path_frames(state, prefix) - target_proc_frames)

        me = state.me
        if me.state == "MOVING" and me.next_node_id and len(prefix) >= 2 and prefix[1] == me.next_node_id:
            remaining = max(0, me.edge_total_ms - me.edge_progress_ms)
            remaining_frames = ceil(remaining / pathing.BASE_MOVE_PER_FRAME) if remaining else 0
            if len(prefix) == 2:
                return remaining_frames
            tail = prefix[1:]
            tail_target_proc = state.process_nodes.get(tail[-1])
            tail_proc_frames = tail_target_proc.process_round if tail_target_proc else 0
            return remaining_frames + max(0, pathing.path_frames(state, tail) - tail_proc_frames)

        return frames

    def _contest_score(self, state: GameState, contest: Contest) -> float:
        score = float(_KEY_CONTEST_SCORES.get(contest.contest_type, 0))
        if contest.contest_type == "TASK":
            score = max(score, self._task_contest_score(state, contest.task_id))
        elif contest.contest_type == "RESOURCE":
            score = max(score, self._resource_contest_score(state, contest.resource_type))
        target = contest.target_node_id
        path = self._terminal_path(state, state.me.current_node_id)
        if contest.contest_type not in ("TASK", "RESOURCE") and target and path and target in path:
            score = max(score, 30)
            if len(path) >= 2 and target == path[1]:
                score += 10
        return score

    @staticmethod
    def _task_contest_score(state: GameState, task_id: str) -> float:
        if not task_id:
            return 0.0
        task = next((t for t in state.tasks if t.task_id == task_id), None)
        if task is None:
            return 0.0
        raw = state.me.task_score
        return float(_task_points(raw + int(task.score)) - _task_points(raw))

    @staticmethod
    def _resource_contest_score(state: GameState, resource_type: str) -> float:
        if not resource_type:
            return 0.0
        cap = RESOURCE_CLAIM_CAPS.get(resource_type)
        if cap is not None and state.me.resources.get(resource_type, 0) >= cap:
            return 0.0
        return float(RESOURCE_BASE_VALUES.get(resource_type, 1.0))

    @staticmethod
    def _is_neighbor(state: GameState, cur: str, target: str) -> bool:
        return any(node_id == target for node_id, _ in state.neighbors(cur))

    @staticmethod
    def _terminal_path(state: GameState, cur: str) -> list[str] | None:
        terminals = state.roles.terminal_node_ids or \
            [n.node_id for n in state.nodes.values() if n.is_terminal]
        best: list[str] | None = None
        best_cost: tuple[float, int] | None = None
        for terminal in terminals:
            path = pathing.shortest_path(state, cur, terminal)
            if path is None:
                continue
            cost = pathing.path_cost(state, path)
            if best_cost is None or cost < best_cost:
                best, best_cost = path, cost
        return best

    @staticmethod
    def _is_terminal_choke(state: GameState, cur: str, node_id: str) -> bool:
        terminals = state.roles.terminal_node_ids or \
            [n.node_id for n in state.nodes.values() if n.is_terminal]
        return any(node_id in pathing.choke_nodes(state, cur, terminal) for terminal in terminals)

    @staticmethod
    def _terminals(state: GameState) -> list[str]:
        return state.roles.terminal_node_ids or \
            [n.node_id for n in state.nodes.values() if n.is_terminal]

    @staticmethod
    def _is_terminal(state: GameState, node_id: str) -> bool:
        node = state.nodes.get(node_id)
        return bool(node and node.is_terminal) or node_id in CombatStrategy._terminals(state)

    @staticmethod
    def _has_active_guard(state: GameState, node_id: str) -> bool:
        ns = state.node_states.get(node_id)
        return bool(ns and ns.guard and ns.guard.active and ns.guard.defense > 0)

    @staticmethod
    def _friendly_guard_count(state: GameState) -> int:
        my_team = state.my_team_id or state.me.team_id
        count = 0
        for ns in state.node_states.values():
            guard = ns.guard
            if guard and guard.active and guard.defense > 0 and guard.owner_team_id == my_team:
                count += 1
        return count

    def _ahead_of_opponent(self, state: GameState, cur: str) -> bool:
        opponent = state.opponent
        # 对手缺席/已交付/已退赛时 safety 侧视同"领先"，但设卡拦不到人 → False
        if opponent.delivered or opponent.retired or not opponent.current_node_id:
            return False
        return safety.ahead_of_opponent(state, safety.GUARD_SETUP_FRAMES)

    def _is_opponent_choke(self, state: GameState, cur: str) -> bool:
        opponent = state.opponent
        if not opponent.current_node_id:
            return False
        for terminal in self._terminals(state):
            if cur in pathing.choke_nodes(state, opponent.current_node_id, terminal):
                return True
        return False

    @staticmethod
    def _guard_max_defense(state: GameState, node_id: str) -> int:
        return pathing.guard_max_defense(state, node_id)

    @staticmethod
    def _guard_base_cost(state: GameState, node_id: str) -> int:
        node = state.nodes.get(node_id)
        if node and node.node_type in ("KEY_PASS", "GATE"):
            return 1
        return 0

    def _guard_investment(self, state: GameState, node_id: str) -> tuple[int, int, int]:
        max_defense = self._guard_max_defense(state, node_id)
        base_cost = self._guard_base_cost(state, node_id)
        for extra in (2, 1, 0):
            good_cost = base_cost + extra
            if state.my_good - good_cost < GUARD_GOOD_FLOOR:
                continue
            defense = min(max_defense, 2 + extra * 2)
            return extra, defense, good_cost
        return 0, 0, 0

    @staticmethod
    def _guard_weathering_frames(state: GameState, node_id: str, defense: int) -> int:
        node = state.nodes.get(node_id)
        first = 45 if node and node.node_type == "KEY_PASS" and defense >= 4 else 30
        return first + max(0, defense - 1) * 30
