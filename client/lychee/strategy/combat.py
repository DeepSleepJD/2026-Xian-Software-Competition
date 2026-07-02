"""对抗层：攻坚破卡 + 窗口出牌。

核心规则：
- 任务书 6.3.1：攻坚只能打当前相邻节点的敌方有效设卡，且当帧结算。
- 任务书 8.2：MOVING 不能攻坚，所以上边前发现下一跳有守卫时必须拦截 MOVE。
- 窗口出牌独立于主车队动作，但每张牌必须带 contestId + card。
"""

from math import ceil

from .. import pathing
from ..state import Contest, GameState
from . import Intent, Strategy

PRIORITY_COMBAT_MAIN = 130
PRIORITY_SET_GUARD = 129
PRIORITY_SQUAD_WEAKEN = 128
PRIORITY_WINDOW_CARD = 125

_STATIONARY_STATES = {"IDLE", "WAITING"}
_KEY_CONTEST_SCORES = {"GATE": 50, "PASS": 45, "DOCK": 40}
GUARD_GOOD_FLOOR = 90
GUARD_SETUP_FRAMES = 4
GUARD_GOOD_FRAME_COST = 15
GUARD_MIN_NET_FRAMES = 30


class CombatStrategy(Strategy):
    def propose(self, state: GameState) -> list[Intent]:
        if state.me.delivered or state.me.retired:
            return []

        intents: list[Intent] = []
        main = self._propose_break_guard(state)
        if main is None:
            main = self._propose_set_guard(state)
        if main is not None:
            intents.append(main)

        squad = self._propose_squad_weaken(state)
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
        bad = min(2, state.my_bad)
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

    def _propose_set_guard(self, state: GameState) -> Intent | None:
        me = state.me
        if state.phase != "NORMAL" or me.verified:
            return None
        if me.current_process is not None or me.state != "IDLE":
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
        delay = self._guard_weathering_frames(state, cur, defense)
        net = delay - GUARD_SETUP_FRAMES - good_cost * GUARD_GOOD_FRAME_COST
        if net < GUARD_MIN_NET_FRAMES:
            return None
        action = {"action": "SET_GUARD", "targetNodeId": cur, "extraGoodFruit": extra}
        return Intent(kind="combat.guard", priority=PRIORITY_SET_GUARD,
                      actions=[action], note=f"设卡@{cur}")

    def _propose_squad_weaken(self, state: GameState) -> Intent | None:
        me = state.me
        if me.state != "MOVING" or not me.next_node_id:
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

    def _propose_window_cards(self, state: GameState) -> list[dict]:
        contests = [c for c in state.my_open_contests() if c.contest_id]
        if not contests:
            return []
        scored = [(self._contest_score(state, c), c) for c in contests]
        score, contest = max(scored, key=lambda item: item[0])
        if score <= 0:
            return []
        card = "ABSTAIN"
        if state.me.freshness >= 80 and state.my_good > 0:
            card = "XIAN_GONG"
        elif state.my_guard_points > 1:
            card = "BING_ZHENG"
        return [{"action": "WINDOW_CARD", "contestId": contest.contest_id, "card": card}]

    def _contest_score(self, state: GameState, contest: Contest) -> int:
        score = _KEY_CONTEST_SCORES.get(contest.contest_type, 0)
        target = contest.target_node_id
        path = self._terminal_path(state, state.me.current_node_id)
        if target and path and target in path:
            score = max(score, 30)
            if len(path) >= 2 and target == path[1]:
                score += 10
        return score

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

    @staticmethod
    def _best_path_frames(state: GameState, src: str) -> int:
        best: int | None = None
        for terminal in CombatStrategy._terminals(state):
            path = pathing.shortest_path(state, src, terminal)
            if path is None:
                continue
            frames = pathing.path_frames(state, path)
            if best is None or frames < best:
                best = frames
        return best if best is not None else 10 ** 9

    def _ahead_of_opponent(self, state: GameState, cur: str) -> bool:
        opponent = state.opponent
        if opponent.delivered or opponent.retired or not opponent.current_node_id:
            return False
        my_frames = self._best_path_frames(state, cur)
        opp_frames = self._best_path_frames(state, opponent.current_node_id)
        return my_frames + GUARD_SETUP_FRAMES < opp_frames

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
        node = state.nodes.get(node_id)
        ns = state.node_states.get(node_id)
        if ns is not None and ns.has_obstacle:
            return 5
        if node and node.node_type == "KEY_PASS":
            return 7
        if node and node.node_type == "GATE":
            return 4
        return 6

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
