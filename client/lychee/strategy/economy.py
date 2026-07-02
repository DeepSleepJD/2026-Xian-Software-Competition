"""经济层：顺路皇榜任务 + 冰鉴领取/阈值使用（P2，设计见 docs/P2经济层开发准备.md）。

规则依据（任务书 4.4 / 5.1-5.3，协议动作速查）：
- CLAIM_TASK 须停在任务目标节点（有障碍的目标可在相邻节点处理，人不动）
- CLAIM_RESOURCE 须停在资源节点且有库存；USE_RESOURCE 冰鉴只能停靠时用
- 同帧对手抢同一对象 → 窗口争夺；P2 弃权（不出牌即弃权，零成本）
- 对方归属（ownerPlayerId）或保护（protectionPlayerId）的任务不碰

与 delivery 的分工：economy 高优先级（110/120）在 NORMAL 阶段抢主车队动作权
去做任务，一到 RUSH 或任务分拿满 90 即闭嘴，delivery（100）接管直奔宫门；
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

from math import floor

from .. import pathing
from ..state import GameState
from . import Intent, Strategy

PRIORITY_ICE_USE = 120
PRIORITY_ECONOMY = 110
TASK_SCORE_GOAL = 90          # 拿满即闭嘴（60/90/110 里程碑，90 是 P2 目标）
                              # 注意 inquire.taskScore 是原始任务分，里程碑奖励结算时才补发
ICE_BOX_VALUE = 18.0          # +10 鲜度 ≈ +18 分（策略文档定量）
DETOUR_COST_PER_FRAME = 0.12  # 绕路 1 帧的点数成本：移动鲜度损耗 ~0.055/帧 ×
                              # 鲜度边际价值 ~1.8 分 + 风险余量（时间本身不值钱，洞察#3）
TARGET_STICKINESS = 2.0       # 换目标需净值优势超过此值（防止停靠间目标抖动）
ICE_BOX_MAX_HOLD = 2          # 库存到量后不再追领
RESOURCE_CLAIM_FRAMES = 2     # 实测资源领取读条帧数（估值用，非规则常量）
ICE_USE_MARGIN = 2.0          # freshness ≤ 阈值+2 即用
ENDGAME_MARGIN = 40           # 目标完成帧 + 回终点帧 ≤ 总帧数 − 此余量
                              # （回程按终点算，途经宫门的验核读条已计入路径成本）
_INF = 10 ** 9
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
                 claim_nodes: list[str], action: dict, expire_round: int, note: str) -> None:
        self.key = key
        self.value = value
        self.proc_frames = proc_frames
        self.claim_nodes = claim_nodes
        self.action = action
        self.expire_round = expire_round
        self.note = note


class EconomyStrategy(Strategy):
    def __init__(self) -> None:
        self._gate = _StationGate()
        self._backoff: dict[str, int] = {}      # 目标 key → 解禁帧
        self._claim_rejects: dict[str, int] = {}
        self._pending_claim = ""                # 上一帧提议的领取目标 key
        self._move_rejects = 0
        self._cur_target_key = ""

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired:
            return []

        self._gate.observe(state)
        self._read_feedback(state)

        # 读条/移动/休整中：闭嘴让帧推进（打断读条 = 进度清零，任务书 4.3）
        if me.current_process is not None:
            return []
        if me.state in ("MOVING", "RESTING") or me.next_node_id:
            return []
        cur = me.current_node_id
        if not cur:
            return []

        intents: list[Intent] = []
        eco = self._propose_economy(state, cur)
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
                self._backoff["USE:ICE_BOX"] = state.round + 20

    # -- 任务/资源贪心 --

    def _propose_economy(self, state: GameState, cur: str) -> Intent | None:
        me = state.me
        if state.phase != "NORMAL" or me.verified or me.task_score >= TASK_SCORE_GOAL:
            return None

        target, spot = self._pick_target(state, cur)
        self._cur_target_key = target.key if target else ""
        if target is None:
            # 无候选：离终局截止尚早就原地蹲守刷新（任务只在刷新后才可见）
            if self._can_linger(state, cur):
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

        # 第一遍：可行性过滤（到点最近停靠点、过期、终局截止、净值>0）
        feasible: list[tuple[_Target, str, int, int]] = []   # (cand, spot, to, done)
        for cand in self._candidates(state, cur):
            if state.round < self._backoff.get(cand.key, 0):
                continue
            spot, to_frames = "", _INF
            for s in cand.claim_nodes:
                f = from_cur.get(s, (0.0, _INF))[1]
                if f < to_frames:
                    spot, to_frames = s, f
            if not spot or to_frames >= _INF:
                continue
            done_round = state.round + to_frames + cand.proc_frames
            if cand.expire_round > 0 and done_round > cand.expire_round:
                continue
            feasible.append((cand, spot, to_frames, done_round))
        if not feasible:
            return None, ""

        from_spot = {spot: pathing.all_costs(state, spot)
                     for spot in {s for _, s, _, _ in feasible}}

        def net_of(cand: _Target, to: int, back: int) -> float:
            cost = max(0, to + cand.proc_frames + back - base_frames)
            return cand.value - cost * DETOUR_COST_PER_FRAME

        best: tuple[float, int, _Target, str] | None = None
        for cand, spot, to_frames, done_round in feasible:
            back = from_spot[spot].get(anchor, (0.0, _INF))[1]
            if done_round + back > deadline:
                continue
            net = net_of(cand, to_frames, back)
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
                follow = max(follow, c2.value - cost2 * DETOUR_COST_PER_FRAME)
            plan = net + follow
            if cand.key == self._cur_target_key:
                plan += TARGET_STICKINESS
            # 同分取更近的（先落袋近处，降低被对手截胡的风险）
            if best is None or plan > best[0] or (plan == best[0] and to_frames < best[1]):
                best = (plan, to_frames, cand, spot)
        if best is None:
            return None, ""
        return best[2], best[3]

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

    def _candidates(self, state: GameState, cur: str) -> list[_Target]:
        me = state.me
        out: list[_Target] = []
        for t in state.tasks:
            if not t.active or t.completed or t.failed or not t.node_id:
                continue
            if t.owner_player_id not in (0, state.player_id):
                continue
            if t.protection_player_id not in (0, state.player_id):
                continue
            tpl = state.task_templates.get(t.task_template_id)
            if tpl and any(me.resources.get(rt, 0) < 1 for rt in tpl.required_resource_types):
                continue   # 消耗型任务（如 T06 耗马）没有本钱不接
            ns = state.node_states.get(t.node_id)
            if ns is not None and ns.has_obstacle:
                # 清障任务目标节点进不去：在相邻节点处理（任务书 5.2 例外）
                claim_nodes = [n for n, _ in state.neighbors(t.node_id)]
                if not claim_nodes:
                    continue
            else:
                claim_nodes = [t.node_id]
            out.append(_Target(
                key=t.task_id, value=float(t.score), proc_frames=t.process_round,
                claim_nodes=claim_nodes,
                action={"action": "CLAIM_TASK", "taskId": t.task_id},
                expire_round=t.expire_round, note=f"任务{t.task_id}@{t.node_id}"))

        if me.resources.get("ICE_BOX", 0) < ICE_BOX_MAX_HOLD:
            for node_id, ns in state.node_states.items():
                if ns.resource_stock.get("ICE_BOX", 0) < 1:
                    continue
                out.append(_Target(
                    key=f"RES:{node_id}:ICE_BOX", value=ICE_BOX_VALUE,
                    proc_frames=RESOURCE_CLAIM_FRAMES, claim_nodes=[node_id],
                    action={"action": "CLAIM_RESOURCE", "targetNodeId": node_id,
                            "resourceType": "ICE_BOX"},
                    expire_round=0, note=f"冰鉴@{node_id}"))
        return out

    # -- 冰鉴使用 --

    def _propose_ice_use(self, state: GameState, cur: str, planned_next: str) -> Intent | None:
        me = state.me
        if me.resources.get("ICE_BOX", 0) < 1 or me.freshness <= 0:
            return None
        if state.round < self._backoff.get("USE:ICE_BOX", 0):
            return None
        f = me.freshness
        threshold = min(floor(f / 10) * 10, 90)   # 下一个会被跌破的十位阈值
        trigger = f <= threshold + ICE_USE_MARGIN
        if not trigger and planned_next:
            # 出发上长边前预判：途中跨阈值则提前用（跌破一次 = 1 好果转坏）
            for nxt, edge in state.neighbors(cur):
                if nxt == planned_next:
                    frames = pathing.edge_frames(edge.distance, edge.route_type)
                    loss = frames * pathing.ROUTE_FRESHNESS.get(
                        edge.route_type, pathing._UNKNOWN_FRESHNESS)
                    trigger = f - loss < threshold
                    break
        if not trigger:
            return None
        return Intent(kind="economy", priority=PRIORITY_ICE_USE,
                      actions=[{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}],
                      note=f"冰鉴保鲜@{f:.1f}")

    # -- 辅助 --

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
