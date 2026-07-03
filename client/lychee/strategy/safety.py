"""「送达优先」全局硬约束（P4d 兜底）。

判定：已用帧数 + 到终点预计帧数 + 安全余量 ≥ 总帧数（durationRound）即触发 must_rush，
经济层候选与对抗层设卡让路，直奔终点；攻坚/削卡/探路/用马/用冰保留（都是送达
的一部分，见任务 design.md 接线表）。

- 到终点帧数用最短路 path_frames（已含沿途处理读条），不建模守卫——余量覆盖清卡等待。
- 无状态每帧重算，不做迟滞锁存：触发边界抖动最多让个别帧多/少一个候选提案，
  经济层自身的候选时限账（ENDGAME_MARGIN）仍在，无实害。
"""

from math import ceil
from weakref import WeakKeyDictionary

from .. import pathing
from ..state import GameState

GUARD_SETUP_FRAMES = 4
HOLD_MAX_FRAMES = 12
RUSH_SAFETY_MARGIN = 60   # 帧。覆盖削卡等待+验核读条+处理中断重来+暂停损耗+抖动；
                          # 比经济层候选级 ENDGAME_MARGIN=40 更保守（全局最后防线），
                          # P5 自对弈可调；置 0 即近似退化为无兜底
_INF = 10 ** 9
_HOLD_MEMORY: "WeakKeyDictionary[GameState, dict]" = WeakKeyDictionary()


def _terminals(state: GameState) -> list[str]:
    return state.roles.terminal_node_ids or \
        [n.node_id for n in state.nodes.values() if n.is_terminal]


def frames_to_terminal(state: GameState) -> int:
    """当前位置到最近终点的预计帧数；半路（含被守卫暂停）从 next_node_id 起算
    并计入剩余边帧数；不可达返回大数（视同时间不够，触发直奔/停止绕路）。"""
    me = state.me
    extra = 0
    if me.next_node_id:
        remaining = max(0, me.edge_total_ms - me.edge_progress_ms)
        extra = ceil(remaining / pathing.BASE_MOVE_PER_FRAME) if remaining else 0
        start = me.next_node_id
    else:
        start = me.current_node_id
    if not start:
        return _INF

    best: int | None = None
    for terminal in _terminals(state):
        path = pathing.shortest_path(state, start, terminal)
        if path is None:
            continue
        frames = pathing.path_frames(state, path)
        if best is None or frames < best:
            best = frames
    if best is None:
        return _INF
    return extra + best


def must_rush(state: GameState) -> bool:
    return state.round + frames_to_terminal(state) + RUSH_SAFETY_MARGIN \
        >= state.duration_round


def _best_frames_from(state: GameState, src: str) -> int:
    best: int | None = None
    for terminal in _terminals(state):
        path = pathing.shortest_path(state, src, terminal)
        if path is None:
            continue
        frames = pathing.path_frames(state, path)
        if best is None or frames < best:
            best = frames
    return best if best is not None else _INF


def ahead_of_opponent(state: GameState, margin: int = 0) -> bool:
    """按双方到最近终点的最短路帧数比较竞速位次。

    无在场对手（缺席/已交付/已退赛）返回 True——竞速压力不存在，行为只受
    时间账约束。对手设卡值不值得（combat 设卡）语义相反，调用侧自行先判。
    """
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired or not opp.current_node_id:
        return True
    cur = state.me.current_node_id
    if not cur:
        return False
    return _best_frames_from(state, cur) + margin < \
        _best_frames_from(state, opp.current_node_id)


def _edge_frames_between(state: GameState, src: str, dst: str) -> int:
    for node_id, edge in state.neighbors(src):
        if node_id == dst:
            return pathing.edge_frames_for_state(state, edge)
    return _INF


def remaining_edge_frames(state: GameState, player) -> int:
    """半路玩家走完当前边还需的帧数；不在边上返回大数（economy 竞争折扣共用）。"""
    if not player.current_node_id or not player.next_node_id:
        return _INF
    remaining = max(0, player.edge_total_ms - player.edge_progress_ms)
    if remaining > 0:
        return ceil(remaining / pathing.BASE_MOVE_PER_FRAME)
    return _edge_frames_between(state, player.current_node_id, player.next_node_id)


def _can_opponent_set_guard_before_arrival(state: GameState, next_node: str) -> bool:
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired:
        return False
    if opp.guard_action_point < 1:
        return False
    if opp.current_node_id == next_node and not opp.next_node_id:
        return True
    if opp.next_node_id != next_node:
        return False
    my_eta = _edge_frames_between(state, state.me.current_node_id, next_node)
    if my_eta >= _INF:
        return False
    opp_eta = remaining_edge_frames(state, opp)
    return opp_eta + GUARD_SETUP_FRAMES <= my_eta


def _hold_memory(state: GameState) -> dict:
    mem = _HOLD_MEMORY.get(state)
    if mem is None or mem.get("match_id") != state.match_id:
        mem = {"match_id": state.match_id, "guard_ever_seen": False, "streaks": {}}
        _HOLD_MEMORY[state] = mem
    return mem


def _observe_enemy_guard(state: GameState, mem: dict) -> None:
    if mem.get("guard_ever_seen"):
        return
    my_team = state.my_team_id or state.me.team_id
    for ns in state.node_states.values():
        guard = ns.guard
        if guard and guard.owner_team_id and guard.owner_team_id != my_team:
            mem["guard_ever_seen"] = True
            return


def _hold_streak_allows(state: GameState, next_node: str, mem: dict) -> bool:
    streaks = mem.setdefault("streaks", {})
    count, last_round = streaks.get(next_node, (0, -1))
    if last_round == state.round:
        return count <= HOLD_MAX_FRAMES
    if last_round == state.round - 1:
        count += 1
    else:
        count = 1
    streaks[next_node] = (count, state.round)
    return count <= HOLD_MAX_FRAMES


def _clear_hold_streak(state: GameState, next_node: str) -> None:
    mem = _HOLD_MEMORY.get(state)
    if mem is not None:
        mem.setdefault("streaks", {}).pop(next_node, None)


def hold_before_choke(state: GameState, next_node: str) -> bool:
    """防陷阱闸门（P4e）：True = 本帧别提交进入 next_node 的 MOVE，原地等。

    败因场景（现网 match_2751 r361）：对手车队停在我方交付路径咽喉上、握着
    guardActionPoint，我方上边后它离站前设卡——半路禁止原路折返（任务书 8.2）、
    攻坚需停稳相邻，小分队不足时只能干等风化（防御 6 = 180 帧）。停在边外等它
    走人：亮卡则停稳攻坚当帧清（坏果 3 攻坚值/篓），没设卡照走，最多亏它的
    停站帧数。

    有界状态：只在本局已见过对手设卡后启用，且同一咽喉最多连续 hold 12 帧。
    """
    if not next_node:
        return False
    mem = _hold_memory(state)
    _observe_enemy_guard(state, mem)
    if must_rush(state):                 # 时间账吃紧：接受风化风险也要走（保底交付）
        _clear_hold_streak(state, next_node)
        return False
    if not _can_opponent_set_guard_before_arrival(state, next_node):
        _clear_hold_streak(state, next_node)
        return False                     # 对手不能抢先在下一跳完成设卡
    if not mem.get("guard_ever_seen"):
        _clear_hold_streak(state, next_node)
        return False                     # 本局从未见对手设卡：按刷任务对手处理，别自冻
    if state.enemy_guard_at(next_node) is not None:
        _clear_hold_streak(state, next_node)
        return False                     # 已亮卡：停稳攻坚链接管，蹲着反而白等
    if state.me.squad_available >= pathing.guard_max_defense(state, next_node):
        _clear_hold_streak(state, next_node)
        return False                     # 半路被设卡也削得穿，进边风险可控
    cur = state.me.current_node_id
    if not cur:
        _clear_hold_streak(state, next_node)
        return False
    # 咽喉过滤：非咽喉对手不值得设卡，不过滤会在它每个处理站后面跟停
    is_choke = any(next_node in pathing.choke_nodes(state, cur, terminal)
                   for terminal in _terminals(state))
    if not is_choke:
        _clear_hold_streak(state, next_node)
        return False
    return _hold_streak_allows(state, next_node, mem)
