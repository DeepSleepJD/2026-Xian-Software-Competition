"""主线交付状态机：走位 → 固定处理 → 宫门验核 → 交付。

规则依据（任务书）：
- 4.2 移动：MOVE 目标必须是合法相邻节点；移动/读条/休整中空 actions 即可推进
- 2.4.1 固定处理站点：到站必须 PROCESS（目标=当前节点）处理完才能离站；
  离站后再来需重新处理；4.3 处理被中断后进度清零（拒因 PROCESS_REQUIRED 重处理）
- 4.5 宫门验核：仅宫宴冲刺（phase=RUSH）可提交 VERIFY_GATE；宫门是 VERIFY 型
  处理点（真实地图 S14 在 processNodes 里），对它永不发 PROCESS；
  交付需位于终点 + 已验核 + 好果>0 + 鲜度>0
- 阻挡处理（M3 简化版）：MOVE 连续被拒 → 临时绕开目标节点重新寻路；
  攻坚/强通/清障是 P4 对抗层的事

每帧最多产出一个主车队动作（arbiter 兜底类别上限）。
"""

from .. import pathing
from ..state import GameState
from . import Intent, Strategy, safety

PRIORITY_DELIVERY = 100
# MOVE 连续被拒此数后，临时绕开该节点重新寻路（持续 AVOID_ROUNDS 帧）
MOVE_REJECT_LIMIT = 5
AVOID_ROUNDS = 30
# 冻结改道逃生（P4m-M2）：改道总帧数须比"等风化+走完本边"至少快这么多才动
FROZEN_ESCAPE_SLACK = 8
# MOVE 拒因明确在目标侧（协议第 11 章错误码）→ 与本站处理无关，不重置处理簿记
_TARGET_SIDE_REJECTS = frozenset({
    "MOVE_BLOCKED_BY_GUARD", "MOVE_EDGE_NOT_FOUND", "MOVE_MISSING_TARGET",
    "TARGET_NOT_FOUND", "TARGET_NOT_REACHABLE",
})


class DeliveryStrategy(Strategy):
    def __init__(self) -> None:
        self._last_node = ""            # 上一帧停靠节点（换节点时重置本站处理簿记）
        self._processed_here = False    # 当前停靠节点的固定处理已完成
        self._saw_processing = False    # 本站已观察到读条进行中（用于推断处理完成）
        self._last_move_target = ""
        self._move_rejects = 0
        self._avoid_until: dict[str, int] = {}   # 节点 → 绕行解除帧

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired:
            return []

        self._read_feedback(state)

        # 移动/读条/休整中：空心跳即可推进（任务书 4.2 / 协议第 8 章）
        if me.current_process is not None:
            cp = me.current_process
            # 只把站点处理/宫门验核的读条当作本站固定处理证据；
            # 资源/任务等经济类读条（P2 起会出现）不算，否则会误判处理完成
            if cp.action in ("PROCESS", "VERIFY_GATE") or \
                    cp.object_key.startswith(("PROCESS:", "GATE:")):
                self._saw_processing = True
            return []
        if me.state == "CONTESTING":
            # 窗口争夺中：主车队动作全禁——本地裁判对"卡牌+非法主动作"同帧会把
            # 整帧降级 WAIT（牌被吞记 ABSTAIN，S02 镜像 0:0 局实证）；出牌归 combat。
            # PROCESS 受理即开窗 ≠ 读条开始，平/负后需重新 PROCESS，撤销受理误标
            self._saw_processing = False
            return []
        if me.next_node_id:
            # 半路被敌卡冻结 → 改道逃生（P4m-M2 实证唯一可用的冻结态动作）
            escape = self._propose_frozen_escape(state)
            return [escape] if escape is not None else []
        if me.state in ("MOVING", "RESTING"):
            return []

        cur = me.current_node_id
        if not cur:
            return []
        if cur != self._last_node:
            self._last_node = cur
            self._processed_here = False
            self._saw_processing = False

        # 读条曾出现（或提交已受理）且已结束，仍停在原地 → 本站处理完成
        if self._saw_processing:
            self._processed_here = True
            self._saw_processing = False

        # 终点：满足条件即交付，否则原地等（不满足时提交 DELIVER 不计非法但没意义）
        if cur in self._terminals(state):
            if me.verified and me.good_fruit > 0 and me.freshness > 0:
                return [self._intent({"action": "DELIVER"}, "终点交付")]
            return []

        proc = state.process_nodes.get(cur)
        # 宫门（含 VERIFY 型处理点）：站点处理动作是 VERIFY_GATE，永不发 PROCESS；
        # 已验核即视同处理完成，直接走人
        if cur == state.roles.gate_node_id or (proc and proc.process_type == "VERIFY"):
            if not me.verified:
                if state.phase == "RUSH":
                    return [self._intent({"action": "VERIFY_GATE"}, "宫门验核")]
                return []  # NORMAL 阶段提交无效，等待开门
        elif proc and not self._processed_here:
            # 固定处理站点：先处理完才能离站
            return [self._intent({"action": "PROCESS", "targetNodeId": cur}, f"固定处理@{cur}")]

        # 主线走位：向最近终点推进
        target = self._pick_move_target(state, cur)
        if target:
            self._last_move_target = target
            return [self._intent({"action": "MOVE", "targetNodeId": target}, f"走位→{target}")]
        return []

    # -- 内部 --

    def _propose_frozen_escape(self, state: GameState) -> Intent | None:
        """半路被敌卡冻结的改道逃生（P4m-M2 实验实证）。

        冻结形态三变体统一判据：在边上（nextNodeId 非空）且下一跳有敌方有效卡——
        此时 MOVE(next)/WAIT 被拒、FORCED_PASS/BREAK_GUARD 判 MOVING_ACTION_FORBIDDEN，
        唯一被服务器受理的是任务书 4.2 的改道：MOVE 到本段起点的其他合法相邻节点，
        当帧解冻、旧边进度作废（13:22 现网局被钉 193 帧期间每帧都有这张脱困票）。

        决策：min(改道邻居 + 该点到终点) 与 "等风化 + 走完本边 + 下一跳到终点" 比较，
        改道明显更快（差 > FROZEN_ESCAPE_SLACK）才动——风化只剩几十帧时原地等更优。
        寻路成本已含在场敌卡的攻坚/风化惩罚，绕回原路还是绕开由成本模型自己定。
        """
        me = state.me
        target = me.next_node_id
        guard = state.enemy_guard_at(target)
        if guard is None:
            return None
        cur = me.current_node_id
        if not cur:
            return None
        onward = safety.frames_from_node(state, target)
        stay = safety.guard_weathering_remaining(state, target, guard) \
            + safety.remaining_edge_frames(state, me) \
            + (onward if onward < 10 ** 8 else 10 ** 8)
        best_alt, best_cost = "", None
        for alt, edge in state.neighbors(cur):
            if alt == target:
                continue
            alt_onward = safety.frames_from_node(state, alt)
            if alt_onward >= 10 ** 8:
                continue
            cost = pathing.edge_frames_for_state(state, edge) + alt_onward
            if best_cost is None or cost < best_cost:
                best_alt, best_cost = alt, cost
        if not best_alt or best_cost + FROZEN_ESCAPE_SLACK >= stay:
            return None
        return self._intent({"action": "MOVE", "targetNodeId": best_alt},
                            f"冻结改道逃生→{best_alt}")

    def _read_feedback(self, state: GameState) -> None:
        """读上一帧动作结果：处理被拒重试、移动被拒计数绕行。"""
        for r in state.my_action_results():
            if r.round != state.round - 1:
                continue
            if r.accepted:
                if r.action == "MOVE":
                    self._move_rejects = 0
                elif r.action in ("PROCESS", "VERIFY_GATE"):
                    # 受理即读条开始：处理帧数极短（如 1 帧）时可能观察不到
                    # currentProcess，用受理结果兜底，防止处理完后反复重发 PROCESS
                    self._saw_processing = True
                continue
            if r.action == "MOVE":
                # 停在处理站点且拒因不明确在目标侧 → 多半是处理被中断过
                # （任务书 4.3 进度清零）没处理完，重新处理
                if state.me.current_node_id in state.process_nodes and \
                        r.error_code not in _TARGET_SIDE_REJECTS:
                    self._processed_here = False
                if r.error_code == "PROCESS_REQUIRED":
                    continue   # 自家处理欠账导致的拒绝，不计入绕行
                self._move_rejects += 1
                if self._move_rejects >= MOVE_REJECT_LIMIT and self._last_move_target:
                    self._avoid_until[self._last_move_target] = state.round + AVOID_ROUNDS
                    self._move_rejects = 0
            elif r.action == "PROCESS" and r.error_code == "PROCESS_NOT_AVAILABLE":
                # 本站当前无处理流程 → 视同已处理，防止无限重发卡死
                self._processed_here = True
                self._saw_processing = False
            elif r.action in ("PROCESS", "VERIFY_GATE"):
                self._saw_processing = False   # 没排上读条，下帧重新提交

    @staticmethod
    def _terminals(state: GameState) -> list[str]:
        """终点集合：roles 缺失时回退 nodes 的 terminal 标记（换图变体防御）。"""
        return state.roles.terminal_node_ids or \
            [n.node_id for n in state.nodes.values() if n.is_terminal]

    def _pick_move_target(self, state: GameState, cur: str) -> str:
        avoid = frozenset(n for n, until in self._avoid_until.items() if state.round < until)
        # 激进抢点：公共可设卡节点在前方时，先把它当临时硬目标；已经站上去则不
        # camp，交给 combat 当帧设卡，下一帧继续送达/前压。
        rush = safety.first_common_rush_node(state)
        if rush and rush != cur:
            path = pathing.min_frame_path(state, cur, rush, safety.me_move_per_frame(state))
            if path and len(path) >= 2:
                return path[1]

        best: list[str] | None = None
        best_cost: tuple[float, int] = (0.0, 0)
        for terminal in self._terminals(state):
            path = pathing.shortest_path(state, cur, terminal, avoid)
            if path is None and avoid:   # 绕行导致不可达 → 放弃绕行硬闯
                path = pathing.shortest_path(state, cur, terminal)
            if path and len(path) >= 2:
                cost = pathing.path_cost(state, path)
                if best is None or cost < best_cost:
                    best, best_cost = path, cost
        if best is None:
            return ""
        # 防陷阱闸门（P4e）：对手蹲在咽喉上且可设卡时不进边，原地等它走人
        if safety.hold_before_choke(state, best[1]):
            return ""
        return best[1]

    def _intent(self, action: dict, note: str) -> Intent:
        return Intent(kind="delivery", priority=PRIORITY_DELIVERY, actions=[action], note=note)
