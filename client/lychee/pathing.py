"""图结构 / 最短路 / 路线规划。

基于 start 下发的 nodes/edges 建图（支持换图变体，不写死地图）。
成本模型（任务书 2.3.2 / 2.4.1 / 3.2.2，均为规则常量，不随地图变化）：
- 边移动帧数 = ceil( ceil(距离 × 路线耗时系数) / 每帧移动量 )，无加速每帧 1000
- 途经固定处理站点必须处理完才能离站 → 处理帧数计入路径（停靠损耗 0.05/帧）
- **主成本 = 累计鲜度损耗，次成本 = 帧数**：宫门 RUSH 阶段（~390帧）才开，
  早到也是停着掉鲜度（0.05/帧），时间不值钱、鲜度值钱（策略文档洞察#3）。
  样例地图实测：按帧数山路最快但多耗 ~4 鲜度（≈7 分），按鲜度水路胜出。
"""

import heapq
from math import ceil

from .state import GameState

# 路线耗时系数：每 1 点路线距离所需移动量（任务书 2.3.2 固定表）
ROUTE_COST_COEF = {"ROAD": 1380, "WATER": 1250, "MOUNTAIN": 1780, "BRANCH": 1550}
_UNKNOWN_COEF = 1600            # 未知路线类型保守估计
# 每结算帧鲜度损耗（任务书 3.2.2 固定表）
ROUTE_FRESHNESS = {"ROAD": 0.055, "WATER": 0.045, "MOUNTAIN": 0.07, "BRANCH": 0.065}
_UNKNOWN_FRESHNESS = 0.07
STATIONARY_FRESHNESS = 0.05     # 停靠/处理/验核等状态每帧损耗
BASE_MOVE_PER_FRAME = 1000


def edge_frames(distance: int, route_type: str, move_per_frame: int = BASE_MOVE_PER_FRAME) -> int:
    """一条路线边的移动帧数（无天气影响）。"""
    coef = ROUTE_COST_COEF.get(route_type, _UNKNOWN_COEF)
    need = ceil(distance * coef)
    return ceil(need / max(move_per_frame, 1))


def _reachable_without(state: GameState, src: str, dst: str, blocked: str) -> bool:
    if src == dst:
        return True
    seen = {blocked}
    stack = [src]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        if node == dst:
            return True
        seen.add(node)
        for nxt, _ in state.neighbors(node):
            if nxt not in seen:
                stack.append(nxt)
    return False


def choke_nodes(state: GameState, src: str, dst: str) -> set[str]:
    """Nodes that every route from src to dst must pass through, excluding endpoints."""
    if src not in state.nodes or dst not in state.nodes:
        return set()
    if not _reachable_without(state, src, dst, ""):
        return set()
    out: set[str] = set()
    for node_id in state.nodes:
        if node_id in (src, dst):
            continue
        if not _reachable_without(state, src, dst, node_id):
            out.add(node_id)
    return out


def _guard_weathering_frames(state: GameState, node_id: str, defense: int, age: int, initial: int) -> int:
    node = state.nodes.get(node_id)
    first = 45 if node and node.node_type == "KEY_PASS" and initial >= 4 else 30
    interval = 30
    age = max(0, age)
    if age < first:
        next_loss = first - age
    else:
        elapsed = (age - first) % interval
        next_loss = interval - elapsed if elapsed else interval
    return next_loss + max(0, defense - 1) * interval


def _guard_penalty_frames(state: GameState, to_node: str) -> int:
    guard = state.enemy_guard_at(to_node)
    if guard is None:
        return 0
    attack = min(2, state.my_bad) * 3 + min(2, state.my_good) * 2
    if attack >= guard.defense:
        return 1
    if attack > 0:
        return 6
    return _guard_weathering_frames(
        state, to_node, int(guard.defense), int(guard.age_round), int(guard.initial_defense))


def _step_cost(state: GameState, edge, to_node: str) -> tuple[float, int]:
    """走一条边并（如需）完成目标站固定处理的 (鲜度损耗, 帧数)。"""
    frames = edge_frames(edge.distance, edge.route_type)
    fresh = frames * ROUTE_FRESHNESS.get(edge.route_type, _UNKNOWN_FRESHNESS)
    guard_frames = _guard_penalty_frames(state, to_node)
    if guard_frames:
        frames += guard_frames
        fresh += guard_frames * STATIONARY_FRESHNESS
    proc = state.process_nodes.get(to_node)
    if proc:
        frames += proc.process_round
        fresh += proc.process_round * STATIONARY_FRESHNESS
    return fresh, frames


def shortest_path(state: GameState, src: str, dst: str,
                  avoid: frozenset[str] = frozenset()) -> list[str] | None:
    """Dijkstra 最短路，返回节点序列 [src, ..., dst]；不可达返回 None。

    成本 = (累计鲜度损耗, 累计帧数) 字典序；途经固定处理站点（含 dst）
    的处理帧数与停靠损耗计入。avoid 中的节点不入路径（src/dst 除外）。
    """
    if src == dst:
        return [src]
    dist: dict[str, tuple[float, int]] = {src: (0.0, 0)}
    prev: dict[str, str] = {}
    heap: list[tuple[float, int, str]] = [(0.0, 0, src)]
    visited: set[str] = set()

    while heap:
        fresh, frames, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        if node == dst:
            path = [dst]
            while path[-1] != src:
                path.append(prev[path[-1]])
            path.reverse()
            return path
        for nxt, edge in state.neighbors(node):
            if nxt in visited or (nxt in avoid and nxt != dst):
                continue
            step_fresh, step_frames = _step_cost(state, edge, nxt)
            cand = (fresh + step_fresh, frames + step_frames)
            if nxt not in dist or cand < dist[nxt]:
                dist[nxt] = cand
                prev[nxt] = node
                heapq.heappush(heap, (cand[0], cand[1], nxt))
    return None


def all_costs(state: GameState, src: str) -> dict[str, tuple[float, int]]:
    """单源到全图各节点的 (鲜度损耗, 帧数)。多目标估值时替代反复调 shortest_path。"""
    dist: dict[str, tuple[float, int]] = {src: (0.0, 0)}
    heap: list[tuple[float, int, str]] = [(0.0, 0, src)]
    visited: set[str] = set()
    while heap:
        fresh, frames, node = heapq.heappop(heap)
        if node in visited:
            continue
        visited.add(node)
        for nxt, edge in state.neighbors(node):
            if nxt in visited:
                continue
            step_fresh, step_frames = _step_cost(state, edge, nxt)
            cand = (fresh + step_fresh, frames + step_frames)
            if nxt not in dist or cand < dist[nxt]:
                dist[nxt] = cand
                heapq.heappush(heap, (cand[0], cand[1], nxt))
    return dist


def path_cost(state: GameState, path: list[str]) -> tuple[float, int]:
    """一条路径的 (估计鲜度损耗, 估计帧数)，用于多终点/多路线比较。"""
    fresh, frames = 0.0, 0
    for a, b in zip(path, path[1:]):
        for nxt, edge in state.neighbors(a):
            if nxt == b:
                sf, sn = _step_cost(state, edge, b)
                fresh += sf
                frames += sn
                break
    return fresh, frames


def path_frames(state: GameState, path: list[str]) -> int:
    """一条路径的估计总帧数（移动 + 途经处理）。"""
    return path_cost(state, path)[1]
