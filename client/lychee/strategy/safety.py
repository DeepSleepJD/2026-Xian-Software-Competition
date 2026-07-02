"""「送达优先」全局硬约束（P4d 兜底）。

判定：已用帧数 + 到终点预计帧数 + 安全余量 ≥ 总帧数（durationRound）即触发 must_rush，
经济层候选/蹲守与对抗层设卡让路，直奔终点；攻坚/削卡/探路/用马/用冰保留（都是送达
的一部分，见任务 design.md 接线表）。

- 到终点帧数用最短路 path_frames（已含沿途处理读条），不建模守卫——余量覆盖清卡等待。
- 无状态每帧重算，不做迟滞锁存：触发边界抖动最多让个别帧多/少一个候选提案，
  经济层自身的候选时限账（ENDGAME_MARGIN）仍在，无实害。
"""

from math import ceil

from .. import pathing
from ..state import GameState

RUSH_SAFETY_MARGIN = 60   # 帧。覆盖削卡等待+验核读条+处理中断重来+暂停损耗+抖动；
                          # 比经济层候选级 ENDGAME_MARGIN=40 更保守（全局最后防线），
                          # P5 自对弈可调；置 0 即近似退化为无兜底
_INF = 10 ** 9


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


def hold_before_choke(state: GameState, next_node: str) -> bool:
    """防陷阱闸门（P4e）：True = 本帧别提交进入 next_node 的 MOVE，原地等。

    败因场景（现网 match_2751 r361）：对手车队停在我方交付路径咽喉上、握着
    guardActionPoint，我方上边后它离站前设卡——半路禁止原路折返（任务书 8.2）、
    攻坚需停稳相邻，小分队不足时只能干等风化（防御 6 = 180 帧）。停在边外等它
    走人：亮卡则停稳攻坚当帧清（坏果 3 攻坚值/篓），没设卡照走，最多亏它的
    停站帧数。

    无状态：对手停站时长天然有界（它也要赶路）；恶意长蹲由 must_rush 兜底强行进。
    """
    if not next_node:
        return False
    if must_rush(state):                 # 时间账吃紧：接受风化风险也要走（保底交付）
        return False
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired:
        return False
    if opp.current_node_id != next_node or opp.next_node_id:
        return False                     # 对手不是正停在该节点
    if opp.guard_action_point < 1:
        return False
    if state.enemy_guard_at(next_node) is not None:
        return False                     # 已亮卡：停稳攻坚链接管，蹲着反而白等
    if state.me.squad_available >= pathing.guard_max_defense(state, next_node):
        return False                     # 半路被设卡也削得穿，进边风险可控
    cur = state.me.current_node_id
    if not cur:
        return False
    # 咽喉过滤：非咽喉对手不值得设卡，不过滤会在它每个处理站后面跟停
    return any(next_node in pathing.choke_nodes(state, cur, terminal)
               for terminal in _terminals(state))
