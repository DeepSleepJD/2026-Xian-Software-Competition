"""经济层：顺路皇榜任务 + 冰鉴领取/阈值使用（P2，设计见 docs/P2经济层开发准备.md）。

规则依据（任务书 4.4 / 5.1-5.3，协议动作速查）：
- CLAIM_TASK 须停在任务目标节点（有障碍的目标可在相邻节点处理，人不动）
- CLAIM_RESOURCE 须停在资源节点且有库存；USE_RESOURCE 冰鉴只能停靠时用
- 同帧对手抢同一对象 → 窗口争夺；P2 弃权（不出牌即弃权，零成本）
- 对方归属（ownerPlayerId）或保护（protectionPlayerId）的任务不碰

与 delivery 的分工：economy 高优先级（110/120）在 NORMAL 阶段抢主车队动作权
去做任务/领冰鉴，一到 RUSH 即闭嘴，delivery（100）接管直奔宫门；任务分拿满
（raw≥130 封顶）后任务候选关闭但冰鉴领取照常（P3 修正：不再连坐闭嘴）；
冰鉴使用（120）不受任务窗口限制，交付前全程有效。
固定处理站点未处理完不得离站（任务书 2.4.1）→ economy 在此类站点上
不抢 MOVE/WAIT，让位 delivery 的 PROCESS（用与 delivery 同源的完成推断）。

估值（实测复盘校准，2026-07-02 两局回归）：
- 净值制：net = 分值 − 绕路帧 × 0.12（时间不值钱、鲜度值钱，洞察#3）
- 一步前瞻：plan = net + 最优跟进目标 net。单步贪心会让顺路小绕的冰鉴
  永远输给下一个任务候选（每一站都有更大的任务在前面）
- 蹲守：任务只在刷新后才进 feed（无法预知），刷新波持续到 ~400 帧而车队
  ~355 帧就会路过最后的任务区、水路尾段 ~180 帧回不了头 → 无候选且
  离终局截止尚早时原地 WAIT（协议合法主车队动作，不清移动进度）等刷新
"""

from math import ceil, floor

from .. import pathing
from ..state import GameState
from . import Intent, Strategy, safety

PRIORITY_ICE_USE = 120
PRIORITY_HORSE_USE = 119
PRIORITY_INTEL_USE = 118
PRIORITY_ECONOMY = 110
TASK_SCORE_GOAL = 130         # 拿满即闭嘴：里程碑 60/90/110 → +15/+35/+50（无 130 档），
                              # 皇榜分封顶 180 = raw 130 + 50，超过 130 边际为零
                              # 注意 inquire.taskScore 是原始任务分，里程碑奖励结算时才补发
ICE_BOX_VALUE = 18.0          # +10 鲜度 ≈ +18 分（策略文档定量）
DETOUR_COST_PER_FRAME = 0.12  # 绕路 1 帧的点数成本：移动鲜度损耗 ~0.055/帧 ×
                              # 鲜度边际价值 ~1.8 分 + 风险余量（时间本身不值钱，洞察#3）
SLOW_ROUTE_COEF_LIMIT = 1500  # 经济目标不走慢边（P4e）：MOUNTAIN(1780)/BRANCH(1550)
                              # 级别的边只为任务/资源去走是净亏（现网败局实证：S08
                              # 山路绕行 +22 帧 + 雾天再慢 10%，换 30 分任务还落后于
                              # 会设卡的对手）；交付路径本身要走的慢边不受此限（换图
                              # 主线只有山路时经济层不哑）。帧数上限方案已否决——
                              # 它把"大路任务簇"（对水路基线呈绕行，实测配冰鉴净赚
                              # 34 分）一起误杀，见任务归档 2026-07-03 归因实验
CONTEST_DISCOUNT = 0.5        # 竞争折扣（B2b）：对手到候选点 ETA 更近但无朝向实证时
                              # 净值打对折——宁可折扣不硬出局，对手一次只能处理一个
                              # 目标，全面出局会饿死经济层
CONTEST_ETA_MARGIN = 3        # 帧。硬出局要求对手"明显"更近（ETA+此值仍先到）：
                              # ETA 是估计值（天气/守卫/暂停噪声），弱优势只降权不放弃
LINGER_WAVE_WINDOW = 15       # 蹲守只等临近刷新波；更远时行军穿走廊优先
LINGER_WAVE_GRACE = 3         # 波次边界/feed 抖动余量；落空后下一波会自然超窗
LINGER_DEFICIT_WINDOW = 45    # 对手已交付且小差额落后时，最多等约一个刷新周期
DEFICIT_LINGER_MAX = 40       # 差额过大时不白等，立即交付锁分/保鲜
WAVE_MIN_SAMPLES = 2          # 至少见过两个不同 refreshRound，才外推刷新周期
TARGET_STICKINESS = 2.0       # 换目标需净值优势超过此值（防止停靠间目标抖动）
TARGET_SWITCH_RATIO = 0.20    # 已承诺目标存在时，新目标需额外领先 20%
BACKTRACK_MARGIN = 2.0        # 刚到站即原路折返需额外覆盖一条边成本
ICE_BOX_MAX_HOLD = 2          # 库存到量后不再追领（本图第 3 个在 S06 支线，
                              # 实账往返~118帧鲜度+用时亏损 > 冰鉴收益，正确放弃）
ICE_ZERO_STOCK_BONUS = 6.0    # 0 冰时首个冰鉴额外覆盖十位鲜度阈值的坏果损失
ICE_CONTEST_TOLERANCE = 5     # 稀缺冰 ETA 劣势在此范围内仍全价争，不系统性让渡
RESOURCE_CLAIM_FRAMES = 2     # 实测资源领取读条帧数（估值用，非规则常量）
ICE_USE_MARGIN = 2.0          # freshness ≤ 阈值+2 即用
HOT_ICE_USE_MARGIN = 5.0      # 酷暑/临近酷暑时更早保鲜，避免连续跨十位阈值
ENDGAME_MARGIN = 40           # 目标完成帧 + 回终点帧 ≤ 总帧数 − 此余量
                              # （回程按终点算，途经宫门的验核读条已计入路径成本）
_INF = 10 ** 9

HORSE_MOVE_PER_FRAME = {"FAST_HORSE": 1200, "SHORT_HORSE": 1150}
HORSE_DURATION = {"FAST_HORSE": 20, "SHORT_HORSE": 14}
HORSE_USE_MIN_SAVED_FRAMES = 2
HORSE_RESOURCES = ("FAST_HORSE", "SHORT_HORSE")
ACTIVE_USE_RESOURCE_TYPES = frozenset({"ICE_BOX", "FAST_HORSE", "SHORT_HORSE", "INTEL"})
DOCUMENT_RESOURCES = frozenset({"PASS_TOKEN", "OFFICIAL_PERMIT"})
INTEL_PROCESS_TYPES = frozenset({"VERIFY"})
INTEL_MIN_PROCESS_FRAMES = 5
RESOURCE_CLAIM_CAPS = {
    "ICE_BOX": ICE_BOX_MAX_HOLD,
    "FAST_HORSE": 1,
    "SHORT_HORSE": 1,
    "PASS_TOKEN": 1,
    "OFFICIAL_PERMIT": 1,
    "INTEL": 1,
    "BOAT_RIGHT": 1,
}
RESOURCE_BASE_VALUES = {
    "ICE_BOX": ICE_BOX_VALUE,
    "FAST_HORSE": 8.0,
    "SHORT_HORSE": 6.0,
    "PASS_TOKEN": 1.0,
    "OFFICIAL_PERMIT": 1.0,
    "INTEL": 0.5,
    "BOAT_RIGHT": 1.0,
}


def _task_points(raw: int) -> int:
    """皇榜任务分结算值：raw + 里程碑奖励，封顶 180（任务书 7.2）。"""
    bonus = 50 if raw >= 110 else 35 if raw >= 90 else 15 if raw >= 60 else 0
    return min(180, raw + bonus)


def _use_resource_action(resource_type: str, **fields: object) -> dict:
    """Build a USE_RESOURCE action through the document-safety whitelist."""
    if resource_type not in ACTIVE_USE_RESOURCE_TYPES:
        raise AssertionError(f"USE_RESOURCE forbidden for {resource_type}")
    action = {"action": "USE_RESOURCE", "resourceType": resource_type}
    action.update(fields)
    return action


CLAIM_REJECT_LIMIT = 2        # 领取连续被拒此数后拉黑目标
MOVE_REJECT_LIMIT = 4         # 赶路连续被拒此数后拉黑目标
BACKOFF_ROUNDS = 50


class _StationGate:
    """当前停靠站点的固定处理是否已完成（与 delivery 同源的推断口径）。

    只看公开信号：PROCESS/VERIFY_GATE 读条、上一帧动作结果。economy 靠它
    决定能否从固定处理站点提议 MOVE，避免高优先级 MOVE 永久饿死 PROCESS。
    """

    def __init__(self) -> None:
        self._node = ""
        self._saw = False       # 本站观察到固定处理读条/受理
        self._done = False

    def observe(self, state: GameState) -> None:
        me = state.me
        for r in state.my_action_results():
            if r.round != state.round - 1:
                continue
            if r.accepted and r.action in ("PROCESS", "VERIFY_GATE"):
                self._saw = True
            elif r.action == "PROCESS" and r.error_code == "PROCESS_NOT_AVAILABLE":
                self._done = True
            elif r.action == "MOVE" and not r.accepted and r.error_code == "PROCESS_REQUIRED":
                self._saw = self._done = False   # 处理欠账实锤（如读条被打断）
        cp = me.current_process
        if cp is not None:
            if cp.action in ("PROCESS", "VERIFY_GATE") or \
                    cp.object_key.startswith(("PROCESS:", "GATE:")):
                self._saw = True
            return
        if me.state in ("MOVING", "RESTING") or me.next_node_id:
            return
        cur = me.current_node_id
        if not cur:
            return
        if cur != self._node:
            self._node, self._saw, self._done = cur, False, False
        if self._saw:
            self._done, self._saw = True, False

    def clear(self, state: GameState, cur: str) -> bool:
        proc = state.process_nodes.get(cur)
        if proc is None:
            return True
        # 宫门/VERIFY 型不属于普通固定处理（delivery 专管，永不发 PROCESS）
        if proc.process_type == "VERIFY" or cur == state.roles.gate_node_id:
            return True
        return self._done


class _Target:
    """一个贪心候选：到 claim_nodes 任一节点停靠后发 action。"""

    def __init__(self, key: str, value: float, proc_frames: int,
                 claim_nodes: list[str], action: dict, expire_round: int, note: str,
                 raw_score: int = 0) -> None:
        self.key = key
        self.value = value
        self.proc_frames = proc_frames
        self.claim_nodes = claim_nodes
        self.action = action
        self.expire_round = expire_round
        self.note = note
        self.raw_score = raw_score      # 任务面值（进 raw 累计）；资源类为 0

    def marginal_value(self, base_raw: int) -> float:
        """在 raw 累计 base_raw 之上做本目标的真实边际分值。

        任务按里程碑/封顶后的结算差值算（跨档加成、130 后归零都在内）；
        资源类不进 raw，用固定 value。
        """
        if self.raw_score <= 0:
            return self.value
        return float(_task_points(base_raw + self.raw_score) - _task_points(base_raw))


class EconomyStrategy(Strategy):
    def __init__(self) -> None:
        self._gate = _StationGate()
        self._backoff: dict[str, int] = {}      # 目标 key → 解禁帧
        self._claim_rejects: dict[str, int] = {}
        self._pending_claim = ""                # 上一帧提议的领取目标 key
        self._move_rejects = 0
        self._cur_target_key = ""
        self._last_stationary_node = ""
        self._previous_stationary_node = ""
        self._pending_use_resource = ""
        self.current_plan: tuple[str, int] | None = None
        self._seen_waves: set[int] = set()

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired:
            return []

        self._gate.observe(state)
        self._read_feedback(state)
        self._observe_waves(state)

        # 读条/移动/休整中：闭嘴让帧推进（打断读条 = 进度清零，任务书 4.3）
        if me.current_process is not None:
            return []
        if me.state == "MOVING" or me.next_node_id:
            horse = self._propose_horse_use(state, me.current_node_id, me.next_node_id)
            return [horse] if horse is not None and me.state == "MOVING" else []
        if me.state in ("MOVING", "RESTING") or me.next_node_id:
            return []
        cur = me.current_node_id
        if not cur:
            return []
        if cur != self._last_stationary_node:
            if self._last_stationary_node:
                self._previous_stationary_node = self._last_stationary_node
            self._last_stationary_node = cur

        intents: list[Intent] = []
        intel = self._propose_intel_use(state, cur)
        if intel is not None:
            intents.append(intel)

        # 送达优先（P4d 兜底）：时间账吃紧时任务/冰鉴候选与 WAIT 蹲守全停；
        # 冰鉴/马匹/情报使用保留（保交付有效性 + 助攻直奔终点）
        must_rush = safety.must_rush(state)
        if must_rush:
            self.current_plan = None
        eco = None if must_rush else self._propose_economy(state, cur)
        if eco is not None:
            intents.append(eco)
            # 冰鉴上边预判只看本帧真会走的边：economy 出 MOVE 用其目标，
            # 出 CLAIM/WAIT 则本帧不走边；economy 无话时按 delivery 下一跳估计
            act = eco.actions[0]
            planned_next = act.get("targetNodeId", "") if act.get("action") == "MOVE" else ""
        else:
            planned_next = self._delivery_next_hop(state, cur)

        ice = self._propose_ice_use(state, cur, planned_next)
        if ice is not None:
            intents.append(ice)
            horse = None
        else:
            horse = self._propose_horse_use(state, cur, planned_next)
        if horse is not None:
            intents.append(horse)
        return intents

    # -- 反馈 --

    def _read_feedback(self, state: GameState) -> None:
        for r in state.my_action_results():
            if r.round != state.round - 1:
                continue
            if r.action in ("CLAIM_TASK", "CLAIM_RESOURCE"):
                key = self._pending_claim
                if r.accepted:
                    self._claim_rejects.pop(key, None)
                elif key:
                    n = self._claim_rejects.get(key, 0) + 1
                    self._claim_rejects[key] = n
                    if n >= CLAIM_REJECT_LIMIT:
                        self._backoff[key] = state.round + BACKOFF_ROUNDS
                        self._claim_rejects.pop(key, None)
            elif r.action == "MOVE":
                if r.accepted:
                    self._move_rejects = 0
                elif r.error_code != "PROCESS_REQUIRED":
                    # 赶路被堵（设卡/障碍等）：连续被拒则放弃当前目标
                    self._move_rejects += 1
                    if self._move_rejects >= MOVE_REJECT_LIMIT and self._cur_target_key:
                        self._backoff[self._cur_target_key] = state.round + BACKOFF_ROUNDS
                        self._move_rejects = 0
            elif r.action == "USE_RESOURCE" and not r.accepted:
                resource = self._pending_use_resource or "ICE_BOX"
                self._backoff[f"USE:{resource}"] = state.round + 20
                self._pending_use_resource = ""
            elif r.action == "USE_RESOURCE" and r.accepted:
                self._pending_use_resource = ""

    # -- 任务/资源贪心 --

    def _propose_economy(self, state: GameState, cur: str) -> Intent | None:
        me = state.me
        if state.phase != "NORMAL" or me.verified:
            self.current_plan = None
            return None
        # 任务分闸门只挡任务候选（见 _candidates），不连坐冰鉴领取——
        # P2/P3-1 实测：raw 拿满后整体闭嘴导致脚下 0 绕路的 S07 冰鉴都不领

        target, spot = self._pick_target(state, cur)
        self._cur_target_key = target.key if target else ""
        self.current_plan = (spot, target.proc_frames) if target is not None else None
        if target is None:
            # 无候选：只在脚下可能刷任务、下一波临近或终局小差额时蹲守。
            # 否则行军穿过任务走廊本身更优，避免 P4j 复盘中的白等。
            if self._should_linger(state, cur):
                return Intent(kind="economy", priority=PRIORITY_ECONOMY,
                              actions=[{"action": "WAIT"}], note="蹲守任务刷新")
            return None
        if cur in target.claim_nodes:
            self._pending_claim = target.key
            return Intent(kind="economy", priority=PRIORITY_ECONOMY,
                          actions=[target.action], note=target.note)
        self._pending_claim = ""
        # 固定处理站点没处理完不能走（让位 delivery 的 PROCESS）
        if not self._gate.clear(state, cur):
            return None
        path = pathing.shortest_path(state, cur, spot)
        if path and len(path) >= 2:
            return Intent(kind="economy", priority=PRIORITY_ECONOMY,
                          actions=[{"action": "MOVE", "targetNodeId": path[1]}],
                          note=f"赶路→{target.note}")
        return None

    def _pick_target(self, state: GameState, cur: str) -> tuple[_Target | None, str]:
        """净值 + 一步前瞻贪心，返回 (目标, 停靠节点)。"""
        anchor = self._nearest_terminal(state, cur) or state.roles.gate_node_id
        if not anchor:
            return None, ""
        from_cur = pathing.all_costs(state, cur)
        base_frames = from_cur.get(anchor, (0.0, _INF))[1]
        deadline = state.duration_round - ENDGAME_MARGIN

        # 第一遍：可行性过滤（到点最近停靠点、过期、终局截止、慢边、净值>0）
        allowed_slow = self._delivery_slow_edges(state, cur, anchor)
        feasible: list[tuple[_Target, str, int, int]] = []   # (cand, spot, to, done)
        for cand in self._candidates(state, cur):
            if state.round < self._backoff.get(cand.key, 0):
                continue
            spot, to_frames = "", _INF
            for s in cand.claim_nodes:
                f = from_cur.get(s, (0.0, _INF))[1]
                if f >= _INF:
                    continue
                path = pathing.shortest_path(state, cur, s)
                if path and len(path) >= 2 and safety.hold_before_choke(state, path[1]):
                    continue
                if f < to_frames:
                    spot, to_frames = s, f
            if not spot or to_frames >= _INF:
                continue
            done_round = state.round + to_frames + cand.proc_frames
            if cand.expire_round > 0 and done_round > cand.expire_round:
                continue
            if self._walks_slow_route(state, cur, spot, anchor, allowed_slow) \
                    and not self._slow_route_exempt(state, cand):
                continue   # 只为经济目标走山路/支线级慢边 → 弃（P4e）
            feasible.append((cand, spot, to_frames, done_round))
        if not feasible:
            return None, ""

        # 竞争建模（B2b/B2c）：被对手明显抢先的候选出局，弱信号打折（B2a 在 _candidates）
        contest = self._contest_factors(state, feasible)
        feasible = [item for item in feasible if contest[item[0].key] > 0.0]
        if not feasible:
            return None, ""

        from_spot = {spot: pathing.all_costs(state, spot)
                     for spot in {s for _, s, _, _ in feasible}}

        raw = state.me.task_score

        def net_of(cand: _Target, to: int, back: int) -> float:
            cost = max(0, to + cand.proc_frames + back - base_frames)
            return cand.marginal_value(raw) - cost * DETOUR_COST_PER_FRAME

        scored: list[tuple[float, int, _Target, str]] = []
        for cand, spot, to_frames, done_round in feasible:
            back = from_spot[spot].get(anchor, (0.0, _INF))[1]
            if done_round + back > deadline:
                continue
            net = net_of(cand, to_frames, back) * contest[cand.key]
            if net <= 0:
                continue
            # 一步前瞻：做完本目标后最优跟进目标的净值也计入。
            # 否则顺路小绕的冰鉴会永远输给"前面还有更大的任务"
            follow = 0.0
            for c2, s2, _, _ in feasible:
                if c2.key == cand.key:
                    continue
                to2 = from_spot[spot].get(s2, (0.0, _INF))[1]
                done2 = done_round + to2 + c2.proc_frames
                if c2.expire_round > 0 and done2 > c2.expire_round:
                    continue
                back2 = from_spot[s2].get(anchor, (0.0, _INF))[1]
                if done2 + back2 > deadline:
                    continue
                cost2 = max(0, to2 + c2.proc_frames + back2 - back)
                follow = max(follow, (c2.marginal_value(raw + cand.raw_score)
                                      - cost2 * DETOUR_COST_PER_FRAME) * contest[c2.key])
            plan = net + follow
            if self._is_immediate_backtrack(state, cur, spot):
                plan -= self._backtrack_penalty(state, cur)
            scored.append((plan, to_frames, cand, spot))
        if not scored:
            return None, ""
        # 同分取更近的（先落袋近处，降低被对手截胡的风险）
        best = max(scored, key=lambda item: (item[0], -item[1]))
        current = next((item for item in scored if item[2].key == self._cur_target_key), None)
        if current is not None and best[2].key != current[2].key:
            threshold = max(TARGET_STICKINESS, abs(current[0]) * TARGET_SWITCH_RATIO)
            if best[0] < current[0] + threshold:
                best = current
        return best[2], best[3]

    # -- 竞争建模（B2）：任务/资源先到先得，被对手抢先的候选别白跑 --

    def _contest_factors(self, state: GameState,
                         feasible: list[tuple[_Target, str, int, int]]) -> dict[str, float]:
        """B2b/B2c 竞争折扣系数：候选 key → 1.0 不变 / CONTEST_DISCOUNT 打折 / 0.0 出局。

        ETA 只是估计：仅"明显更近 + 正朝它去"双信号才硬出局，只有 ETA 优势时打折
        （现网 1349 的 OBJECT_BUSY 白跑即此模式）。B2c 解除：对手任务分封顶后不再
        抢任务（任务候选不折，资源候选照折）；已交付/退赛/验核完的对手不构成竞争。
        """
        factors = {cand.key: 1.0 for cand, _, _, _ in feasible}
        opp = state.opponent
        if opp is None or opp.delivered or opp.retired or opp.verified:
            return factors
        if not opp.current_node_id:
            return factors      # 对手不在场：估值完全不变
        opp_task_capped = opp.task_score >= TASK_SCORE_GOAL
        me_ice = state.me.resources.get("ICE_BOX", 0)
        map_ice_left = sum(ns.resource_stock.get("ICE_BOX", 0)
                           for ns in state.node_states.values())
        if opp.next_node_id:    # 半路：从下一节点起算 + 剩余边帧
            origin = opp.next_node_id
            extra = safety.remaining_edge_frames(state, opp)
            if extra >= _INF:
                extra = 0
        else:
            origin, extra = opp.current_node_id, 0
        opp_costs = pathing.all_costs(state, origin)    # 每帧最多算一次
        for cand, spot, to_frames, _ in feasible:
            if opp_task_capped and cand.raw_score > 0:
                continue        # B2c：对手任务 raw 封顶，不再与我争任务
            frames = opp_costs.get(spot, (0.0, _INF))[1]
            if frames >= _INF:
                continue
            opp_eta = extra + frames
            if opp_eta >= to_frames:
                continue        # 对手不更近：估值完全不变
            if cand.key.endswith(":ICE_BOX") and me_ice == 0 and map_ice_left <= 2 \
                    and to_frames <= opp_eta + ICE_CONTEST_TOLERANCE:
                continue        # 稀缺首冰：小 ETA 劣势仍争，避免对手双吃冰鉴
            if opp_eta + CONTEST_ETA_MARGIN < to_frames and \
                    self._opponent_heading_to(state, spot):
                factors[cand.key] = 0.0
            else:
                factors[cand.key] = CONTEST_DISCOUNT
        return factors

    @staticmethod
    def _opponent_heading_to(state: GameState, spot: str) -> bool:
        """对手下一跳是否落在其到 spot 的最短路方向上（B2b 朝向实证）。"""
        opp = state.opponent
        if not opp.next_node_id:
            return False
        if opp.next_node_id == spot:
            return True
        path = pathing.shortest_path(state, opp.current_node_id, spot)
        return bool(path and len(path) >= 2 and path[1] == opp.next_node_id)

    @staticmethod
    def _opponent_lock(state: GameState):
        """对手读条中的目标（B2a 硬信号）；无读条/不在场返回 None。"""
        opp = state.opponent
        if opp is None or opp.state != "PROCESSING":
            return None
        return opp.current_process

    @staticmethod
    def _path_slow_edges(state: GameState, path: list[str] | None) -> set[str]:
        """一条路径上耗时系数超限（MOUNTAIN/BRANCH 级）的边 id 集合。"""
        out: set[str] = set()
        if not path:
            return out
        for a, b in zip(path, path[1:]):
            for nxt, edge in state.neighbors(a):
                if nxt == b:
                    coef = pathing.ROUTE_COST_COEF.get(
                        edge.route_type, pathing._UNKNOWN_COEF)
                    if coef > SLOW_ROUTE_COEF_LIMIT:
                        out.add(edge.edge_id)
                    break
        return out

    def _delivery_slow_edges(self, state: GameState, cur: str, anchor: str) -> set[str]:
        """交付路径自身要走的慢边（经济候选走这些边不算额外绕山路）。"""
        return self._path_slow_edges(state, pathing.shortest_path(state, cur, anchor))

    def _walks_slow_route(self, state: GameState, cur: str, spot: str,
                          anchor: str, allowed_slow: set[str]) -> bool:
        """去停靠点或从停靠点回终点需要走交付路径之外的慢边则为 True。"""
        for src, dst in ((cur, spot), (spot, anchor)):
            slow = self._path_slow_edges(state, pathing.shortest_path(state, src, dst))
            if slow - allowed_slow:
                return True
        return False

    @staticmethod
    def _slow_route_exempt(state: GameState, cand: _Target) -> bool:
        """0 冰状态下冰鉴候选解除慢边硬禁令，交给净值账裁决。"""
        return cand.key.endswith(":ICE_BOX") and \
            state.me.resources.get("ICE_BOX", 0) < 1

    def _can_linger(self, state: GameState, cur: str) -> bool:
        """蹲守安全判定：现在动身仍能在截止前送达，且不欠本站固定处理。"""
        if not self._gate.clear(state, cur):
            return False
        terminal = self._nearest_terminal(state, cur)
        if not terminal:
            return False
        p = pathing.shortest_path(state, cur, terminal)
        if p is None:
            return False
        return state.round + pathing.path_frames(state, p) <= \
            state.duration_round - ENDGAME_MARGIN

    def _observe_waves(self, state: GameState) -> None:
        for t in state.tasks:
            if t.refresh_round > 0:
                self._seen_waves.add(t.refresh_round)

    def _next_wave_round(self, state: GameState) -> int | None:
        waves = sorted(self._seen_waves)
        if len(waves) < WAVE_MIN_SAMPLES:
            return None
        diffs = [b - a for a, b in zip(waves, waves[1:]) if b > a]
        if not diffs:
            return None
        period = min(diffs)
        nxt = waves[-1]
        while nxt <= state.round:
            nxt += period
        return nxt

    @staticmethod
    def _is_task_candidate_node(state: GameState, node_id: str) -> bool:
        return any(node_id in nodes for nodes in state.task_candidates.values())

    def _should_linger(self, state: GameState, cur: str) -> bool:
        me = state.me
        if not self._can_linger(state, cur):
            return False
        if not self._is_task_candidate_node(state, cur):
            return False
        nxt = self._next_wave_round(state)
        if nxt is None:
            return False
        wait = nxt - state.round
        opp = state.opponent
        opp_delivered = bool(opp and opp.delivered)

        if opp_delivered and me.task_score < TASK_SCORE_GOAL:
            deficit = opp.total_score - self._projected_score(state)
            if 0 < deficit <= DEFICIT_LINGER_MAX and \
                    wait <= LINGER_DEFICIT_WINDOW + LINGER_WAVE_GRACE:
                return True
            return False

        if me.task_score >= 110:
            return False
        if wait > LINGER_WAVE_WINDOW + LINGER_WAVE_GRACE:
            return False
        if not (safety.ahead_of_opponent(state)
                or not safety.opponent_ever_set_guard(state)):
            return False
        return True

    @staticmethod
    def _projected_score(state: GameState) -> int:
        """按当前状态即刻动身交付的最终分保守估计（终局差额蹲守用）。"""
        me = state.me
        terminal_frames = safety.frames_to_terminal(state)
        eta = state.round + terminal_frames
        time_left = max(0, state.duration_round - eta)
        raw = me.task_score
        time_score = (time_left * 70 // state.duration_round) * min(raw, 90) // 90
        fresh = max(0.0, me.freshness - terminal_frames * 0.07)
        return (240 + _task_points(raw) + int(me.good_fruit / 100 * 180)
                + int(fresh / 100 * 180) + time_score)

    def _is_immediate_backtrack(self, state: GameState, cur: str, spot: str) -> bool:
        if not self._previous_stationary_node or spot == cur:
            return False
        path = pathing.shortest_path(state, cur, spot)
        return bool(path and len(path) >= 2 and path[1] == self._previous_stationary_node)

    def _backtrack_penalty(self, state: GameState, cur: str) -> float:
        for node_id, edge in state.neighbors(cur):
            if node_id == self._previous_stationary_node:
                frames = pathing.edge_frames(edge.distance, edge.route_type)
                return frames * DETOUR_COST_PER_FRAME + BACKTRACK_MARGIN
        return BACKTRACK_MARGIN

    def _candidates(self, state: GameState, cur: str) -> list[_Target]:
        me = state.me
        out: list[_Target] = []
        lock = self._opponent_lock(state)
        hard_required_resources = self._required_resources_on_delivery_path(state, cur)
        for t in state.tasks if me.task_score < TASK_SCORE_GOAL else []:
            if not t.active or t.completed or t.failed or not t.node_id:
                continue
            if t.owner_player_id not in (0, state.player_id):
                continue
            if t.protection_player_id not in (0, state.player_id):
                continue
            if lock is not None and lock.task_id and lock.task_id == t.task_id:
                continue   # B2a：对手读条中必然先到手，不等 OBJECT_BUSY 反馈
            tpl = state.task_templates.get(t.task_template_id)
            if tpl and any(me.resources.get(rt, 0) < 1 for rt in tpl.required_resource_types):
                continue   # 消耗型任务（如 T06 耗马）没有本钱不接
            ns = state.node_states.get(t.node_id)
            if ns is not None and ns.has_obstacle:
                # 协议任务书 690：除 T04 清障任务外，主车队必须停在任务目标节点
                # 才能处理；T04 可在目标障碍节点或相邻节点处理。而障碍节点不可用
                # 普通 MOVE 到达（协议 294）→ 非清障任务在障碍未清前不可达，跳过
                # （障碍被清后该任务会重新进候选），否则会对相邻节点误发 CLAIM_TASK
                # 得 NOT_AT_TARGET_NODE（现网 1349 实证）
                is_clear = t.process_type == "CLEAR_OBSTACLE" or t.task_template_id == "T04"
                if not is_clear:
                    continue
                claim_nodes = [n for n, _ in state.neighbors(t.node_id)]
                if not claim_nodes:
                    continue
            else:
                claim_nodes = [t.node_id]
            out.append(_Target(
                key=t.task_id, value=float(t.score), proc_frames=t.process_round,
                claim_nodes=claim_nodes,
                action={"action": "CLAIM_TASK", "taskId": t.task_id},
                expire_round=t.expire_round, note=f"任务{t.task_id}@{t.node_id}",
                raw_score=int(t.score)))

        for node_id, ns in state.node_states.items():
            for resource_type, stock in ns.resource_stock.items():
                if stock < 1:
                    continue
                if lock is not None and lock.resource_type == resource_type \
                        and lock.target_node_id == node_id:
                    continue   # B2a：对手正在该点领取同款资源
                cap = RESOURCE_CLAIM_CAPS.get(resource_type)
                if cap is not None and me.resources.get(resource_type, 0) >= cap:
                    continue
                value = self._resource_value(state, resource_type, hard_required_resources)
                if value is None:
                    continue
                if not self._resource_has_claim_consumer(state, resource_type,
                                                         hard_required_resources):
                    continue
                out.append(_Target(
                    key=f"RES:{node_id}:{resource_type}", value=value,
                    proc_frames=self._resource_claim_round(state, node_id, resource_type),
                    claim_nodes=[node_id],
                    action={"action": "CLAIM_RESOURCE", "targetNodeId": node_id,
                            "resourceType": resource_type},
                    expire_round=0, note=f"资源{resource_type}@{node_id}"))
        return out

    def _resource_value(self, state: GameState, resource_type: str,
                        hard_required_resources: set[str]) -> float | None:
        value = RESOURCE_BASE_VALUES.get(resource_type)
        if value is None:
            return None
        if resource_type == "ICE_BOX" and state.me.resources.get("ICE_BOX", 0) < 1:
            value += ICE_ZERO_STOCK_BONUS
        if resource_type in hard_required_resources:
            return max(value, ICE_BOX_VALUE)
        return value

    def _resource_has_claim_consumer(
            self, state: GameState, resource_type: str,
            hard_required_resources: set[str]) -> bool:
        if resource_type in hard_required_resources:
            return True
        if resource_type in DOCUMENT_RESOURCES:
            opp = state.opponent
            return bool(opp.player_id and not opp.delivered and not opp.retired)
        if resource_type == "INTEL":
            # CLAIM_RESOURCE itself costs a read bar; INTEL is only worth consuming
            # when already held or hard-required by the map.
            return False
        return True

    # -- 冰鉴使用 --

    def _propose_ice_use(self, state: GameState, cur: str, planned_next: str) -> Intent | None:
        me = state.me
        if me.resources.get("ICE_BOX", 0) < 1 or me.freshness <= 0:
            return None
        if state.round < self._backoff.get("USE:ICE_BOX", 0):
            return None
        f = me.freshness
        threshold = min(floor(f / 10) * 10, 90)   # 下一个会被跌破的十位阈值
        margin = HOT_ICE_USE_MARGIN if self._hot_weather_near(state) else ICE_USE_MARGIN
        trigger = threshold < 90 and f <= threshold + margin
        if not trigger and planned_next:
            # 出发上长边前预判：途中跨阈值则提前用（跌破一次 = 1 好果转坏）
            for nxt, edge in state.neighbors(cur):
                if nxt == planned_next:
                    frames = pathing.edge_frames_for_state(state, edge)
                    loss = frames * pathing.ROUTE_FRESHNESS.get(
                        edge.route_type, pathing._UNKNOWN_FRESHNESS)
                    trigger = threshold < 90 and f - loss < threshold
                    break
        if not trigger:
            return None
        self._pending_use_resource = "ICE_BOX"
        return Intent(kind="economy", priority=PRIORITY_ICE_USE,
                      actions=[_use_resource_action("ICE_BOX")],
                      note=f"冰鉴保鲜@{f:.1f}")

    def _propose_intel_use(self, state: GameState, cur: str) -> Intent | None:
        me = state.me
        if me.resources.get("INTEL", 0) < 1:
            return None
        if state.round < self._backoff.get("USE:INTEL", 0):
            return None
        proc = state.process_nodes.get(cur)
        if proc is None:
            return None
        if proc.process_type not in INTEL_PROCESS_TYPES:
            return None
        if proc.process_round < INTEL_MIN_PROCESS_FRAMES:
            return None
        ns = state.node_states.get(cur)
        if ns is not None:
            for marker in ns.scouted:
                marker_team = marker.get("teamId")
                marker_player = marker.get("playerId", 0)
                if marker_team == me.team_id or marker_player == state.player_id:
                    return None
        self._pending_use_resource = "INTEL"
        return Intent(kind="economy.intel", priority=PRIORITY_INTEL_USE,
                      actions=[_use_resource_action("INTEL", targetNodeId=cur)],
                      note=f"情报标记@{cur}")

    def _propose_horse_use(self, state: GameState, cur: str, planned_next: str) -> Intent | None:
        if not planned_next:
            return None
        if any(b.type in ("FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED") and b.remaining_round > 0
               for b in state.me.buffs):
            return None
        for resource_type in HORSE_RESOURCES:
            if state.me.resources.get(resource_type, 0) < 1:
                continue
            if state.round < self._backoff.get(f"USE:{resource_type}", 0):
                continue
            if self._horse_saved_frames(state, cur, planned_next, resource_type) < HORSE_USE_MIN_SAVED_FRAMES:
                continue
            self._pending_use_resource = resource_type
            return Intent(kind="economy.horse", priority=PRIORITY_HORSE_USE,
                          actions=[_use_resource_action(resource_type)],
                          note=f"启用{resource_type}")
        return None

    # -- 辅助 --

    def _required_resources_on_delivery_path(self, state: GameState, cur: str) -> set[str]:
        terminal = self._nearest_terminal(state, cur)
        if not terminal:
            return set()
        path = pathing.shortest_path(state, cur, terminal)
        if not path:
            return set()
        out: set[str] = set()
        for node_id in path:
            proc = state.process_nodes.get(node_id)
            if proc:
                out.update(proc.required_resource_types)
        return out

    @staticmethod
    def _nearest_terminal(state: GameState, cur: str) -> str:
        terminals = state.roles.terminal_node_ids or \
            [n.node_id for n in state.nodes.values() if n.is_terminal]
        best, best_cost = "", None
        for t in terminals:
            p = pathing.shortest_path(state, cur, t)
            if p is None:
                continue
            cost = pathing.path_cost(state, p)
            if best_cost is None or cost < best_cost:
                best, best_cost = t, cost
        return best

    def _delivery_next_hop(self, state: GameState, cur: str) -> str:
        """economy 静默期估计 delivery 下一跳（用于冰鉴上长边预判）。"""
        terminal = self._nearest_terminal(state, cur)
        if not terminal:
            return ""
        p = pathing.shortest_path(state, cur, terminal)
        return p[1] if p and len(p) >= 2 else ""

    @staticmethod
    def _resource_claim_round(state: GameState, node_id: str, resource_type: str) -> int:
        for spec in state.resource_specs:
            if spec.node_id == node_id and spec.resource_type == resource_type:
                return spec.claim_round or RESOURCE_CLAIM_FRAMES
        return RESOURCE_CLAIM_FRAMES

    @staticmethod
    def _hot_weather_near(state: GameState) -> bool:
        if any(w.type == "HOT" for w in state.weather_active):
            return True
        return any(w.type == "HOT" and 0 <= w.start_round - state.round <= 30
                   for w in state.weather_forecast)

    def _horse_saved_frames(
            self, state: GameState, cur: str, planned_next: str, resource_type: str) -> int:
        move_per_frame = HORSE_MOVE_PER_FRAME[resource_type]
        if state.me.state == "MOVING":
            remaining = max(0, state.me.edge_total_ms - state.me.edge_progress_ms)
            if remaining <= 0:
                return 0
            accelerated = max(1, ceil(remaining / move_per_frame))
            base = max(1, ceil(remaining / pathing.BASE_MOVE_PER_FRAME))
            return max(0, min(HORSE_DURATION[resource_type], base) - accelerated)

        for nxt, edge in state.neighbors(cur):
            if nxt != planned_next:
                continue
            base = pathing.edge_frames_for_state(state, edge)
            accelerated = pathing.edge_frames_for_state(state, edge, move_per_frame)
            return max(0, base - accelerated)
        return 0
