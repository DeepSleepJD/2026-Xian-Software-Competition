#!/usr/bin/env python3
"""P4d 调测陪练：脚本化设卡对手（纯本地工具，不入提交 ZIP）。

行为：开局选点（对手起点→终点最短路上第一个 KEY_PASS，--guard-node 可覆盖）
→ 沿最短路赶去（复用 DeliveryStrategy 的走位/站点处理逻辑，把"终点"换成设伏点，
  到点后因 verified=False 永不交付、自然蹲守）
→ 途中下一跳有道路障碍时主车队 CLEAR（否则自己先卡死在障碍前）
→ 待对手 nextNodeId == 设伏点（正走在上边半路）当帧 SET_GUARD，精确复现「半路暂停」
→ 守卫被清/风化后若对手仍在逼近则补设，最多 --max-guards 次（默认 1=现网死局忠实复现；
  调大是超纲压力测试，8 支小分队物理上削不掉两个 6 防守卫）。陪练不求得分。

用法：python tools/adversary_guard.py <player_id> <host> <port> [--guard-node S10] [--max-guards 1]
挂进对局：
    python tools/run_match.py \
        --client-cmd "python client/main.py {player_id} {host} {port}" \
        --demo-cmd "python tools/adversary_guard.py {player_id} {host} {port}" --no-ui
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "client"))

from lychee import VERSION, pathing                      # noqa: E402
from lychee.net import Connection                        # noqa: E402
from lychee.recorder import Recorder                     # noqa: E402
from lychee.runtime import Runtime                       # noqa: E402
from lychee.state import GameState                       # noqa: E402
from lychee.strategy import Intent, Strategy             # noqa: E402
from lychee.strategy.delivery import DeliveryStrategy    # noqa: E402

PRIORITY_ADVERSARY_GUARD = 200
GUARD_EXTRA_GOOD = 2   # KEY_PASS 上 defense = 2 + 2*2 = 6，同我方客户端投料档


class DelayedStrategy(Strategy):
    """前 N 帧压制内层策略（只发心跳）：给陪练晚 N 帧发车。

    我方客户端修掉「半路派小分队掉 1 帧」后与陪练完全同步（同帧到 S02 同帧
    PROCESS → 5.4.4 镜像互平死锁，双方 0 分）；到站差 1 帧即被规则化解。
    陪练设卡触发是响应式的（看对手位置），延迟不影响设卡场景复现。
    """

    def __init__(self, inner: Strategy, delay: int) -> None:
        self._inner = inner
        self._delay = delay

    def propose(self, state: GameState) -> list[Intent]:
        if state.round <= self._delay:
            return []
        return self._inner.propose(state)


class GuardTargetPicker:
    """设伏点选择：覆盖参数 > 对手最短路上第一个 KEY_PASS > 第一个中途咽喉。"""

    def __init__(self, override: str) -> None:
        self._override = override
        self._target = ""

    def target(self, state: GameState) -> str:
        if self._override:
            return self._override
        if self._target:
            return self._target
        opp = state.opponent
        if not opp.current_node_id:
            return ""
        terminals = state.roles.terminal_node_ids or \
            [n.node_id for n in state.nodes.values() if n.is_terminal]
        best, best_cost = None, None
        for terminal in terminals:
            path = pathing.shortest_path(state, opp.current_node_id, terminal)
            if path is None:
                continue
            cost = pathing.path_cost(state, path)
            if best_cost is None or cost < best_cost:
                best, best_cost = path, cost
        if not best or len(best) < 3:
            return ""
        for node_id in best[1:-1]:
            node = state.nodes.get(node_id)
            if node and node.node_type == "KEY_PASS":
                self._target = node_id
                break
        else:
            for node_id in best[1:-1]:
                if any(node_id in pathing.choke_nodes(state, best[0], t) for t in terminals):
                    self._target = node_id
                    break
        if self._target:
            print(f"[adversary] 设伏点: {self._target}", flush=True)
        return self._target


class CamperDelivery(DeliveryStrategy):
    """走位复用：把 _terminals 偷换成设伏点，MOVE/PROCESS/绕行反馈全继承。"""

    def __init__(self, picker: GuardTargetPicker) -> None:
        super().__init__()
        self._picker = picker

    def _terminals(self, state: GameState) -> list[str]:  # type: ignore[override]
        target = self._picker.target(state)
        return [target] if target else DeliveryStrategy._terminals(state)


class ObstacleClearer(Strategy):
    """赶路清障：去设伏点路上下一跳有道路障碍时发主车队 CLEAR（6 帧 + 1 好果）。
    没有它陪练会像无清障能力的客户端一样卡死在障碍前（P4d 实测 S10 开局带 LANDSLIDE）。"""

    def __init__(self, picker: GuardTargetPicker) -> None:
        self._picker = picker

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.current_process is not None or me.next_node_id:
            return []
        if me.state not in ("IDLE", "WAITING") or me.move_direction == "PAUSED":
            return []
        target = self._picker.target(state)
        cur = me.current_node_id
        if not target or not cur or cur == target:
            return []
        path = pathing.shortest_path(state, cur, target)
        if not path or len(path) < 2:
            return []
        ns = state.node_states.get(path[1])
        if ns is None or not ns.has_obstacle:
            return []
        action = {"action": "CLEAR", "targetNodeId": path[1]}
        return [Intent(kind="adversary.clear", priority=PRIORITY_ADVERSARY_GUARD - 1,
                       actions=[action], note=f"清障@{path[1]}")]


class GuardSetter(Strategy):
    """蹲守设卡：对手正走在通往设伏点的边上（含被暂停）时当帧 SET_GUARD。"""

    def __init__(self, picker: GuardTargetPicker, max_guards: int) -> None:
        self._picker = picker
        self._max_guards = max_guards
        self._set_count = 0        # 只计受理成功的设卡（被拒不烧次数）
        self._pending_round = 0

    def propose(self, state: GameState) -> list[Intent]:
        self._read_feedback(state)
        me = state.me
        target = self._picker.target(state)
        if not target or self._set_count >= self._max_guards or self._pending_round:
            return []
        if me.current_node_id != target or me.next_node_id or me.current_process is not None:
            return []
        if me.state not in ("IDLE", "WAITING"):
            return []
        ns = state.node_states.get(target)
        if ns and ns.guard and ns.guard.active and ns.guard.defense > 0:
            return []
        opp = state.opponent
        if opp.delivered or opp.retired or opp.next_node_id != target:
            return []
        self._pending_round = state.round
        print(f"[adversary] 设卡@{target}（对手半路上边，第{self._set_count + 1}发）", flush=True)
        action = {"action": "SET_GUARD", "targetNodeId": target,
                  "extraGoodFruit": GUARD_EXTRA_GOOD}
        return [Intent(kind="adversary.guard", priority=PRIORITY_ADVERSARY_GUARD,
                       actions=[action], note=f"设卡@{target}")]

    def _read_feedback(self, state: GameState) -> None:
        if not self._pending_round:
            return
        for r in state.my_action_results():
            if r.action == "SET_GUARD" and r.round == self._pending_round:
                self._pending_round = 0
                if r.accepted:
                    self._set_count += 1
                    print(f"[adversary] 设卡受理，累计 {self._set_count}", flush=True)
                else:
                    print(f"[adversary] 设卡被拒: {r.error_code}", flush=True)
                return
        if state.round > self._pending_round + 3:   # 结果丢失兜底，允许重试
            self._pending_round = 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="P4d 设卡对手陪练")
    parser.add_argument("player_id", type=int)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--guard-node", default=os.environ.get("LYCHEE_GUARD_NODE", ""))
    # 默认 1：忠实复现现网「单卡风化」死局。8 支小分队只够削一个 6 防守卫
    # （削 1 次耗 2 支降 2 防），默认 2 会把修好的客户端也逼进无解局
    parser.add_argument("--max-guards", type=int, default=1)
    parser.add_argument("--depart-delay", type=int, default=1)
    args = parser.parse_args(argv)

    picker = GuardTargetPicker(args.guard_node)
    conn = Connection.open(args.host, args.port)
    try:
        runtime = Runtime(
            conn,
            player_id=args.player_id,
            player_name="guard-adversary",
            version=VERSION,
            strategies=[DelayedStrategy(s, args.depart_delay)
                        for s in (GuardSetter(picker, args.max_guards), ObstacleClearer(picker),
                                  CamperDelivery(picker))],
            recorder=Recorder.from_env(args.player_id),
        )
        return runtime.run()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
