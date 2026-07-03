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

# 拦截层交付死线旋钮（拦截封锁流设计 §6.3/§6.6，出问题逐个回退）
FRESH_MIN_AT_DELIVER = 5   # 预计交付鲜度低于此 → 弃拦直冲（逼近报废悬崖）
GOOD_MIN_AT_DELIVER = 1    # 好果低于此 → 弃拦直冲（逼近好果归零，全货报废）
OPP_FINISH_MARGIN = 20     # 对手判死的验核/交付余量帧
FREEZE_SAFETY = 2          # 冻结窗口安全余量帧（§6.4，调大更保守=少设卡少白设）
# 对手"能用上的最好速度"上界（§6.1，保守取上界：宁可高估对手也别过早判他死）
_OPP_HORSE_PER_FRAME = {"FAST_HORSE": 1200, "SHORT_HORSE": 1150}
_RUSH_PER_FRAME = 1300
# 可 camp / 设卡的咽喉节点类型（与 combat._propose_set_guard 一致；非此类型不 camp，
# 否则站桩等不到设卡=自冻）
_GUARD_NODE_TYPES = ("KEY_PASS", "PASS")
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


# ---------- 拦截层观测器（第一刀：纯观测，不改行为）----------

def opp_move_per_frame(state: GameState) -> int:
    """对手"能用上的最好速度"（每帧移动量上界，拦截封锁流设计 §6.1）。

    保守取上界：在用或持有的马/疾行令都计入，取最大——ETA 引擎算对手 ETA 时宁可高估
    他的速度（少判他死、多拦一会儿），也别低估导致过早弃拦。
    """
    opp = state.opponent
    best = pathing.BASE_MOVE_PER_FRAME
    if opp is None:
        return best
    for b in opp.buffs:
        if b.remaining_round <= 0:
            continue
        if b.type in _OPP_HORSE_PER_FRAME:
            best = max(best, _OPP_HORSE_PER_FRAME[b.type])
        elif b.type == "RUSH_SPEED":
            best = max(best, _RUSH_PER_FRAME)
    for rt, per in _OPP_HORSE_PER_FRAME.items():
        if opp.resources.get(rt, 0) > 0:
            best = max(best, per)
    return best


def opp_min_frames_to_finish(state: GameState) -> int:
    """对手到最近终点的理论最短帧数（按其最好速度；半路计入剩余边）。

    只算干净行程（移动+固定处理），不含我方卡的时间税——后者由
    opponent_cannot_finish 另行叠加。对手缺席/退赛/位置未知返回 _INF。
    """
    opp = state.opponent
    if opp is None or opp.retired:
        return _INF
    speed = opp_move_per_frame(state)
    if opp.next_node_id:
        remaining = max(0, opp.edge_total_ms - opp.edge_progress_ms)
        extra = ceil(remaining / speed) if remaining else 0
        start = opp.next_node_id
    else:
        extra = 0
        start = opp.current_node_id
    if not start:
        return _INF
    best: int | None = None
    for terminal in _terminals(state):
        frames = pathing.min_frames(state, start, terminal, speed)
        if frames >= pathing.INF_FRAMES:
            continue
        if best is None or frames < best:
            best = frames
    if best is None:
        return _INF
    return extra + best


def _force_pass_tax(state: GameState, node_id: str, defense: int) -> int:
    """对手强制通过我方一张有效卡的时间税（任务书 6.3.2 :1000-1001）。"""
    node = state.nodes.get(node_id)
    if node and node.node_type == "KEY_PASS":
        return min(50, 15 + defense * 5)
    return min(40, 10 + defense * 5)


def _my_guard_tax_on_opponent_path(state: GameState, opp_start: str) -> int:
    """我方仍挡在对手前面（其必经咽喉上）的有效卡对他造成的时间税之和（§6.6）。"""
    my_team = state.my_team_id or state.me.team_id
    speed = opp_move_per_frame(state)
    best_terminal, best_frames = "", None
    for terminal in _terminals(state):
        frames = pathing.min_frames(state, opp_start, terminal, speed)
        if best_frames is None or frames < best_frames:
            best_terminal, best_frames = terminal, frames
    if not best_terminal:
        return 0
    tax = 0
    for node_id in pathing.choke_nodes(state, opp_start, best_terminal):
        ns = state.node_states.get(node_id)
        guard = ns.guard if ns else None
        if guard and guard.active and guard.defense > 0 and guard.owner_team_id == my_team:
            tax += _force_pass_tax(state, node_id, int(guard.defense))
    return tax


def opponent_cannot_finish(state: GameState) -> bool:
    """对手已不可能完赛（或无需拦截）→ 拦截无意义，弃拦全力送达（§6.6）。

    True：对手缺席/退赛/终点不可达，或"剩余帧 < 干净行程 + 我方卡时间税 + 交付余量"。
    False：对手已交付（他完成了），或仍在有效竞速且时间账够完赛。
    """
    opp = state.opponent
    if opp is None or (not opp.current_node_id and not opp.next_node_id):
        return True
    if opp.delivered:
        return False
    if opp.retired:
        return True
    finish = opp_min_frames_to_finish(state)
    if finish >= _INF:
        return True
    opp_start = opp.next_node_id or opp.current_node_id
    tax = _my_guard_tax_on_opponent_path(state, opp_start)
    return state.round + finish + tax + OPP_FINISH_MARGIN > state.duration_round


def _predicted_delivery_freshness(state: GameState) -> float:
    """预计交付到 S15 时的剩余鲜度（沿鲜度最优路估损耗；半路含剩余边损耗）。"""
    me = state.me
    start = me.next_node_id or me.current_node_id
    if not start:
        return me.freshness
    extra_loss = 0.0
    if me.next_node_id:
        remaining = max(0, me.edge_total_ms - me.edge_progress_ms)
        frames = ceil(remaining / pathing.BASE_MOVE_PER_FRAME) if remaining else 0
        extra_loss = frames * pathing.ROUTE_FRESHNESS.get(
            me.route_type or "", pathing._UNKNOWN_FRESHNESS)
    best_loss: float | None = None
    for terminal in _terminals(state):
        path = pathing.shortest_path(state, start, terminal)
        if path is None:
            continue
        loss = pathing.path_cost(state, path)[0]
        if best_loss is None or loss < best_loss:
            best_loss = loss
    if best_loss is None:
        return me.freshness
    return me.freshness - extra_loss - best_loss


def freshness_deadline_hit(state: GameState) -> bool:
    """鲜度/合法性预算触底 → 弃拦直冲（§6.3）。

    触发任一：(a) 预计交付鲜度 ≤ FRESH_MIN_AT_DELIVER（逼近报废）；
    (b) 好果 ≤ GOOD_MIN_AT_DELIVER（逼近好果归零、全货报废）。
    """
    if _predicted_delivery_freshness(state) <= FRESH_MIN_AT_DELIVER:
        return True
    if state.my_good <= GOOD_MIN_AT_DELIVER:
        return True
    return False


def delivery_deadline_hit(state: GameState) -> bool:
    """交付死线 = min(路程线, 鲜度线)：拦截/camp/设卡的最高闸，一亮即弃拦直冲。"""
    return must_rush(state) or freshness_deadline_hit(state)


# ---------- G2 拦截控制器观测器：ETA 差 + camp 目标 + 冻结窗口 ----------

def me_move_per_frame(state: GameState) -> int:
    """我方"当前生效"的每帧移动量（只算在用 buff，不乐观计入手里未用的马；§6.1）。

    与 opp_move_per_frame 的持有即计不同：对我方保守取"当前速度"，让 interception_node
    的"我能先到"判定偏严——只在我确实领先时才 camp。
    """
    best = pathing.BASE_MOVE_PER_FRAME
    for b in state.me.buffs:
        if b.remaining_round <= 0:
            continue
        if b.type in _OPP_HORSE_PER_FRAME:
            best = max(best, _OPP_HORSE_PER_FRAME[b.type])
        elif b.type == "RUSH_SPEED":
            best = max(best, _RUSH_PER_FRAME)
    return best


def _eta(state: GameState, player, node: str, speed: int) -> int:
    if not node or player is None:
        return _INF
    if player.next_node_id:
        remaining = max(0, player.edge_total_ms - player.edge_progress_ms)
        extra = ceil(remaining / speed) if remaining else 0
        start = player.next_node_id
    else:
        extra = 0
        start = player.current_node_id
    if not start:
        return _INF
    frames = pathing.min_frames(state, start, node, speed)
    return _INF if frames >= pathing.INF_FRAMES else extra + frames


def me_eta(state: GameState, node: str) -> int:
    """我方到 node 的理论最短帧数（当前速度；半路含剩余边）。"""
    return _eta(state, state.me, node, me_move_per_frame(state))


def opp_eta(state: GameState, node: str) -> int:
    """对手到 node 的理论最短帧数（最好速度；半路含剩余边）。缺席/退赛返 _INF。"""
    opp = state.opponent
    if opp is None or opp.retired:
        return _INF
    return _eta(state, opp, node, opp_move_per_frame(state))


def _friendly_guard_on(state: GameState, node_id: str) -> bool:
    ns = state.node_states.get(node_id)
    guard = ns.guard if ns else None
    my_team = state.my_team_id or state.me.team_id
    return bool(guard and guard.active and guard.defense > 0 and guard.owner_team_id == my_team)


def interception_node(state: GameState) -> str | None:
    """对手到终点路径上、我能先到且可设卡的第一个必经咽喉（camp 目标，§6.2）。

    返回 None：对手缺席/已交付/退赛；或对手前方已有我方有效卡（一张卡已冻死他，
    别再滚动 camp 拖累自己送达——滚动增援属第三/四刀）；或没有"我能先到"的咽喉。
    只认 KEY_PASS/PASS 咽喉——非此类型 camp 也设不了卡，会自冻。
    """
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired:
        return None
    opp_start = opp.current_node_id or opp.next_node_id
    me_cur = state.me.current_node_id or state.me.next_node_id
    if not opp_start or not me_cur:
        return None
    # 对手即将驶入的节点已有我方有效卡 = 已冻死，别 camp
    if opp.next_node_id and _friendly_guard_on(state, opp.next_node_id):
        return None
    best_node: str | None = None
    best_oe: int | None = None
    for terminal in _terminals(state):
        chokes = pathing.choke_nodes(state, opp_start, terminal)
        if any(_friendly_guard_on(state, c) for c in chokes):
            return None                       # 对手前方已有我方有效卡，已拦住
        for c in chokes:
            node = state.nodes.get(c)
            if node is None or node.node_type not in _GUARD_NODE_TYPES:
                continue
            oe = opp_eta(state, c)
            if oe >= _INF:
                continue
            if me_eta(state, c) + GUARD_SETUP_FRAMES <= oe:
                if best_oe is None or oe < best_oe:
                    best_node, best_oe = c, oe
    return best_node


def freeze_window_open(state: GameState, node: str) -> bool:
    """set-on-commit 时序闸（§6.4）：对手已 commit 进入 node 的边、且到站前设卡能生效。

    True = 对手 next_node==node 且 MOVING（已上边、无法折返/攻坚/强通）且剩余边帧
    ≥ 设卡读条 4 + 安全余量 → 现在设卡能把他冻死在这条边上。
    对手停在 node 相邻节点未上边（可强通）→ False，继续 camp 别早设。
    """
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired:
        return False
    if not node or opp.next_node_id != node or opp.state != "MOVING":
        return False
    return remaining_edge_frames(state, opp) >= GUARD_SETUP_FRAMES + FREEZE_SAFETY


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
