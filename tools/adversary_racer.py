#!/usr/bin/env python3
"""强竞速陪练：模拟现网真实对手（快路 + 抢任务），纯本地工具，不入提交 ZIP。

现网败因是"任务争夺"——强对手走更快的路线先到任务点、抢先锁任务（OBJECT_BUSY）。
官方 demo / adversary_guard 都太弱、不抢任务，复现不了；两个我方客户端自对弈又会在
可争夺固定处理站点（如 S02）完美镜像 → 每拍同牌必平 → DRAW 冷却重试 → 死锁
（任务书 5.4.4）。本陪练专治这两点：

行为：
- 走"帧数最短"路线奔终点（山路更快时就走山路，正是现网对手的打法），不做鲜度优先、
  不做防陷阱等待——纯竞速。
- 到站抢脚下每一个可领任务（含相邻可领的 T04 清障任务），高优先级，模拟抢先锁任务。
- 持有马就用（提速抢跑）。
- 交付路径下一跳有道路障碍则主车队 CLEAR。
- 固定处理站点 PROCESS、宫门 RUSH 阶段 VERIFY_GATE、终点交付：复用 DeliveryStrategy。
- 起手错 1 拍（STAGGER）：与镜像对手天然错位，避免可争夺站点的镜像平局死锁。

用法：python tools/adversary_racer.py <player_id> <host> <port> [--stagger 1]
挂进对局：
    python tools/run_match.py --no-ui \
        --client-cmd "python client/main.py {player_id} {host} {port}" \
        --demo-cmd  "python tools/adversary_racer.py {player_id} {host} {port}"
"""

import argparse
import heapq
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

PRIORITY_GRAB = 210
PRIORITY_CLEAR = 205
PRIORITY_HORSE = 202
PRIORITY_DELIVERY = 100
_INF = 10 ** 9


def fast_path(state: GameState, src: str, dst: str) -> list[str] | None:
    """帧数最短路（只按到站帧数，含天气/障碍通行税；不看鲜度）。"""
    if src == dst:
        return [src]
    dist: dict[str, int] = {src: 0}
    prev: dict[str, str] = {}
    heap: list[tuple[int, str]] = [(0, src)]
    seen: set[str] = set()
    while heap:
        d, node = heapq.heappop(heap)
        if node in seen:
            continue
        seen.add(node)
        if node == dst:
            path = [dst]
            while path[-1] != src:
                path.append(prev[path[-1]])
            path.reverse()
            return path
        for nxt, edge in state.neighbors(node):
            if nxt in seen:
                continue
            step = pathing.edge_frames_for_state(state, edge)
            proc = state.process_nodes.get(nxt)
            if proc:
                step += proc.process_round
            cand = d + step
            if cand < dist.get(nxt, _INF):
                dist[nxt] = cand
                prev[nxt] = node
                heapq.heappush(heap, (cand, nxt))
    return None


def _terminals(state: GameState) -> list[str]:
    return state.roles.terminal_node_ids or \
        [n.node_id for n in state.nodes.values() if n.is_terminal]


def _fastest_terminal_path(state: GameState, src: str) -> list[str] | None:
    best, best_f = None, _INF
    for t in _terminals(state):
        p = fast_path(state, src, t)
        if p is None:
            continue
        frames = _path_fast_frames(state, p)
        if frames < best_f:
            best, best_f = p, frames
    return best


def _path_fast_frames(state: GameState, path: list[str]) -> int:
    total = 0
    for a, b in zip(path, path[1:]):
        for nxt, edge in state.neighbors(a):
            if nxt == b:
                total += pathing.edge_frames_for_state(state, edge)
                proc = state.process_nodes.get(b)
                if proc:
                    total += proc.process_round
                break
    return total


class RacerTaskGrabber(Strategy):
    """到站抢脚下每一个可领任务（含相邻可领的 T04 清障任务），抢先锁任务。"""

    def __init__(self) -> None:
        self._pending = ""

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired or me.current_process is not None:
            return []
        if me.state not in ("IDLE", "WAITING") or me.next_node_id:
            return []
        cur = me.current_node_id
        if not cur:
            return []
        best = None
        for t in state.tasks:
            if not t.active or t.completed or t.failed or not t.node_id:
                continue
            if t.owner_player_id not in (0, state.player_id):
                continue
            if t.protection_player_id not in (0, state.player_id):
                continue
            is_clear = t.process_type == "CLEAR_OBSTACLE" or t.task_template_id == "T04"
            at_node = (t.node_id == cur) or (
                is_clear and any(n == cur for n, _ in state.neighbors(t.node_id)))
            if not at_node:
                continue
            if best is None or t.score > best.score:
                best = t
        if best is None:
            return []
        return [Intent(kind="racer.grab", priority=PRIORITY_GRAB,
                       actions=[{"action": "CLAIM_TASK", "taskId": best.task_id}],
                       note=f"抢任务{best.task_id}")]


class RacerObstacleClearer(Strategy):
    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.current_process is not None or me.next_node_id:
            return []
        if me.state not in ("IDLE", "WAITING") or me.move_direction == "PAUSED":
            return []
        cur = me.current_node_id
        if not cur or me.good_fruit < 1:
            return []
        path = _fastest_terminal_path(state, cur)
        if not path or len(path) < 2:
            return []
        ns = state.node_states.get(path[1])
        if ns is None or not ns.has_obstacle:
            return []
        return [Intent(kind="racer.clear", priority=PRIORITY_CLEAR,
                       actions=[{"action": "CLEAR", "targetNodeId": path[1]}],
                       note=f"清障@{path[1]}")]


class RacerResourceClaimer(Strategy):
    """到站领冰鉴/马（脚下有库存且没到持有上限就领）——现网强对手靠冰鉴保鲜跑山路。"""

    CAPS = {"ICE_BOX": 2, "FAST_HORSE": 1, "SHORT_HORSE": 1}

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired or me.current_process is not None:
            return []
        if me.state not in ("IDLE", "WAITING") or me.next_node_id:
            return []
        cur = me.current_node_id
        ns = state.node_states.get(cur) if cur else None
        if ns is None:
            return []
        for rt, cap in self.CAPS.items():
            if ns.resource_stock.get(rt, 0) >= 1 and me.resources.get(rt, 0) < cap:
                return [Intent(kind="racer.claim", priority=PRIORITY_GRAB - 1,
                               actions=[{"action": "CLAIM_RESOURCE", "targetNodeId": cur,
                                         "resourceType": rt}], note=f"领{rt}")]
        return []


class RacerIceUser(Strategy):
    """鲜度跌到 80 就用冰鉴保鲜（停靠时用）——把山路的鲜度代价抹平。"""

    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired or me.current_process is not None:
            return []
        if me.state != "IDLE" or me.next_node_id:   # 只在节点上停稳时用，绝不饿死移动
            return []
        if me.resources.get("ICE_BOX", 0) < 1 or me.freshness > 80 or me.freshness <= 0:
            return []
        return [Intent(kind="racer.ice", priority=PRIORITY_HORSE + 1,
                       actions=[{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}],
                       note=f"用冰鉴@{me.freshness:.0f}")]


class RacerHorseUser(Strategy):
    def propose(self, state: GameState) -> list[Intent]:
        me = state.me
        if me.delivered or me.retired or me.current_process is not None:
            return []
        if any(b.type in ("FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED") and b.remaining_round > 0
               for b in me.buffs):
            return []
        for rt in ("FAST_HORSE", "SHORT_HORSE"):
            if me.resources.get(rt, 0) >= 1 and (me.state == "MOVING" or me.next_node_id):
                return [Intent(kind="racer.horse", priority=PRIORITY_HORSE,
                               actions=[{"action": "USE_RESOURCE", "resourceType": rt}],
                               note=f"用{rt}")]
        return []


class RacerDelivery(DeliveryStrategy):
    """竞速走位：帧数最短路奔终点，不做鲜度优先、不做防陷阱等待；起手错 STAGGER 拍。"""

    def __init__(self, stagger: int) -> None:
        super().__init__()
        self._stagger = stagger

    def _pick_move_target(self, state: GameState, cur: str) -> str:  # type: ignore[override]
        if state.round <= self._stagger:
            return ""   # 起手错拍：破可争夺站点镜像死锁
        path = _fastest_terminal_path(state, cur)
        if not path or len(path) < 2:
            return ""
        return path[1]


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="强竞速抢任务陪练")
    parser.add_argument("player_id", type=int)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--stagger", type=int, default=1,
                        help="起手错拍帧数，破可争夺站点镜像死锁（默认 1）")
    args = parser.parse_args(argv)

    conn = Connection.open(args.host, args.port)
    try:
        runtime = Runtime(
            conn,
            player_id=args.player_id,
            player_name="racer-adversary",
            version=VERSION,
            strategies=[RacerTaskGrabber(), RacerResourceClaimer(), RacerIceUser(),
                        RacerObstacleClearer(), RacerHorseUser(),
                        RacerDelivery(args.stagger)],
            recorder=Recorder.from_env(args.player_id),
        )
        return runtime.run()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
