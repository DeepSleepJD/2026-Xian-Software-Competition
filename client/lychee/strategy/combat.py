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
PRIORITY_SQUAD_WEAKEN = 128
PRIORITY_WINDOW_CARD = 125

_STATIONARY_STATES = {"IDLE", "WAITING"}
_KEY_CONTEST_SCORES = {"GATE": 50, "PASS": 45, "DOCK": 40}


class CombatStrategy(Strategy):
    def propose(self, state: GameState) -> list[Intent]:
        if state.me.delivered or state.me.retired:
            return []

        intents: list[Intent] = []
        main = self._propose_break_guard(state)
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
