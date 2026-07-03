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
SQUAD_RESERVE_EARLY = 4        # 开局留两波削卡，剩余人手优先转化为探路收益
SQUAD_RESERVE_RELAXED = 2      # 150 帧未见设卡后降低对手设卡先验
SQUAD_RESERVE_GUARDER = 6      # 削穿一张满防卡（防御 6）需 6 支（2 支/次削 2 点）
SQUAD_RESERVE_FOR_WEAKEN = SQUAD_RESERVE_GUARDER
SQUAD_RELAX_ROUND = 150
SQUAD_SPEND_ALL_ROUND = 350
# G6 动态好果地板（拦截封锁流 §6.5）：满防卡仅烧 ≤3 好果，freeze EV 远超好果分损；
# 40 保护交付好果主体（好果<42 才拦设卡），不再像旧值 90 近乎不设卡。旋钮：回 90 即
# 一键退化到近乎不设卡。
GUARD_GOOD_FLOOR = 40
GUARD_GOOD_FRAME_COST = 15
GUARD_MIN_NET_FRAMES = 30


class CombatStrategy(Strategy):
    def __init__(self, economy=None) -> None:
        self._scout_markers: dict[str, int] = {}
        self._scout_pending: dict[str, int] = {}
        self._seen_window_reveals: set[str] = set()
        self._last_window_cards: dict[str, tuple[int, str, str]] = {}
        self._opponent_card_counts: dict[str, int] = {}
        self._opponent_card_total = 0
        self._opponent_ever_set_guard = False
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
        return action

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
        # set-on-commit 时序闸（§6.4）：只在对手已 commit 上边、到站前设卡能生效时才设。
        # 早设（对手还停在相邻节点）会让他停节点上强通逃脱——继续 camp 别设。
        if not safety.freeze_window_open(state, cur):
            return None

        extra, defense, good_cost = self._guard_investment(state, cur)
        if defense < 4:
            return None
        delay = self._guard_weathering_frames(state, cur, defense)
        net = delay - safety.GUARD_SETUP_FRAMES - good_cost * GUARD_GOOD_FRAME_COST
        if net < GUARD_MIN_NET_FRAMES:
            return None
        action = {"action": "SET_GUARD", "targetNodeId": cur, "extraGoodFruit": extra}
        return Intent(kind="combat.guard", priority=PRIORITY_SET_GUARD,
                      actions=[action], note=f"设卡@{cur}")

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
        needed = ceil(guard.defense / 2)
        if me.squad_in_flight >= needed:
            return None
        action = {"action": "SQUAD_WEAKEN", "targetNodeId": me.next_node_id}
        return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_WEAKEN,
                      actions=[action], note=f"小分队削卡@{me.next_node_id}")

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
        if self._opponent_xian_gong_tendency():
            order = ("QIANG_XING", "XIAN_GONG", "BING_ZHENG")
            default = self._first_playable_card(state, contest, order)
        elif self._opponent_bing_zheng_tendency():
            order = ("XIAN_GONG", "BING_ZHENG", "YAN_DIE")
            default = self._first_playable_card(state, contest, order)
        else:
            order = ("BING_ZHENG", "YAN_DIE", "XIAN_GONG")
            default = self._first_playable_card(state, contest, order)
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

    def _opponent_bing_zheng_tendency(self) -> bool:
        if self._opponent_card_total < 2:
            return False
        return self._opponent_card_counts.get("BING_ZHENG", 0) / self._opponent_card_total >= 0.60

    def _opponent_xian_gong_tendency(self) -> bool:
        if self._opponent_card_total < 2:
            return False
        return self._opponent_card_counts.get("XIAN_GONG", 0) / self._opponent_card_total >= 0.60

    def _read_events(self, state: GameState) -> None:
        self._observe_opponent_guard(state)
        self._read_scout_events(state)
        self._read_window_card_reveals(state)

    def _observe_opponent_guard(self, state: GameState) -> None:
        if self._opponent_ever_set_guard:
            return
        my_team = state.my_team_id or state.me.team_id
        for ns in state.node_states.values():
            guard = ns.guard
            if guard and guard.owner_team_id and guard.owner_team_id != my_team \
                    and (guard.active or guard.defense > 0):
                self._opponent_ever_set_guard = True
                return

    def _read_scout_events(self, state: GameState) -> None:
        for node_id, expire in list(self._scout_markers.items()):
            if expire and expire < state.round:
                self._scout_markers.pop(node_id, None)
        for node_id, dispatch_round in list(self._scout_pending.items()):
            if dispatch_round + SCOUT_PENDING_TIMEOUT < state.round:
                self._scout_pending.pop(node_id, None)

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
        my_team = state.my_team_id or state.me.team_id
        for reveal in state.window_card_reveals():
            key = reveal.event_id or f"{reveal.contest_id}:{reveal.round_index}"
            if key in self._seen_window_reveals:
                continue
            self._seen_window_reveals.add(key)
            self._last_window_cards[reveal.contest_id] = (
                reveal.round_index, reveal.red_card, reveal.blue_card)
            card = reveal.blue_card if my_team == "RED" else reveal.red_card
            if not card:
                continue
            self._opponent_card_counts[card] = self._opponent_card_counts.get(card, 0) + 1
            self._opponent_card_total += 1

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

    def _squad_reserve(self, state: GameState) -> int:
        if self._opponent_ever_set_guard:
            return SQUAD_RESERVE_GUARDER
        if state.round >= SQUAD_SPEND_ALL_ROUND:
            return 0
        if state.round >= SQUAD_RELAX_ROUND:
            return SQUAD_RESERVE_RELAXED
        return SQUAD_RESERVE_EARLY

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
