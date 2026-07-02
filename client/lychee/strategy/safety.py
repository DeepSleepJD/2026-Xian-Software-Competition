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
