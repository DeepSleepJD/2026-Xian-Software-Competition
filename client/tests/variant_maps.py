"""换图变体生成器：从真实 start 消息派生若干"合法但结构迥异"的地图变体。

用途：检验客户端泛化性——赛方明确会换地图变体（CLAUDE.md 硬约束"不得写死地图"）。
本模块把 refs/debug-kit-v1/start消息.json 的 map 作为基线，做系统性变换，每个变体针对
一类泛化风险：坐标重排 / 边权重排（最优路线翻转）/ 资源改点 / 拓扑增删节点 /
角色改派（宫门·终点换位）/ 极简特征缺失 / 全维叠加。

客户端 state.update_start 只读这些字段（其余如 routePaths/grid data 一律忽略）：
    data.nodes|map.nodes, data.edges|map.edges,
    map.gameplay.{roles, resources, processNodes, taskCandidates,
                 routeTaskBuckets, obstacleCandidateNodeIds}
因此变换聚焦以上字段，并保持 map.nodes/edges 与顶层同步（供落盘给真实赛服使用）。

每个变体都经 validate() 保证：边引用的节点存在、roles 引用的节点存在、
起点到每个终点可达、宫门在通往某终点的路径上——否则模拟器无法完成交付即为测试假阳性。
"""

import copy
import json
from pathlib import Path

REFS = Path(__file__).resolve().parents[2] / "refs" / "debug-kit-v1"


# ---------------------------------------------------------------- 基线加载

def load_base() -> dict:
    """真实样例 start 的 msg_data（未改）。玩家显式设为 1001/2002 便于测试。"""
    with open(REFS / "start消息.json", encoding="utf-8") as f:
        data = json.load(f)["msg_data"]
    data["players"] = [{"playerId": 1001, "teamId": "RED", "name": "me"},
                       {"playerId": 2002, "teamId": "BLUE", "name": "op"}]
    return data


# ---------------------------------------------------------------- 通用工具

def _nodes(md: dict) -> list[dict]:
    return md.get("nodes") or md["map"]["nodes"]


def _edges(md: dict) -> list[dict]:
    return md.get("edges") or md["map"]["edges"]


def _gameplay(md: dict) -> dict:
    return md["map"]["gameplay"]


def _sync_map(md: dict) -> None:
    """把顶层 nodes/edges 回写进 map.nodes/edges（客户端读顶层，落盘用内层）。"""
    md["map"]["nodes"] = copy.deepcopy(md["nodes"])
    md["map"]["edges"] = copy.deepcopy(md["edges"])


def _adjacency(md: dict) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {n["nodeId"]: set() for n in _nodes(md)}
    for e in _edges(md):
        a = e.get("fromNodeId") or e.get("fromNode")
        b = e.get("toNodeId") or e.get("toNode")
        if a in adj and b in adj:
            adj[a].add(b)
            if e.get("bidirectional", True):
                adj[b].add(a)
    return adj


def _reachable(md: dict, src: str, dst: str) -> bool:
    adj = _adjacency(md)
    if src not in adj or dst not in adj:
        return False
    seen, stack = {src}, [src]
    while stack:
        n = stack.pop()
        if n == dst:
            return True
        for nx in adj.get(n, ()):
            if nx not in seen:
                seen.add(nx)
                stack.append(nx)
    return False


def _set_node_type(md: dict, node_id: str, node_type: str) -> None:
    for coll in (_nodes(md), md["map"]["nodes"]):
        for n in coll:
            if n["nodeId"] == node_id:
                n["type"] = node_type
                n["nodeType"] = node_type
                n["start"] = node_type == "START"
                n["terminal"] = node_type == "FINISH"


def validate(md: dict, name: str) -> None:
    """变体合法性硬校验：非法即抛，避免模拟器把'地图无效'误判成'客户端不泛化'。"""
    ids = {n["nodeId"] for n in _nodes(md)}
    assert ids, f"[{name}] 节点为空"
    for e in _edges(md):
        a = e.get("fromNodeId") or e.get("fromNode")
        b = e.get("toNodeId") or e.get("toNode")
        assert a in ids and b in ids, f"[{name}] 边 {a}->{b} 引用了不存在的节点"
    roles = _gameplay(md)["roles"]
    start = roles["startNodeId"]
    terminals = roles["terminalNodeIds"]
    gate = roles.get("gateNodeId")
    assert start in ids, f"[{name}] startNodeId={start} 不存在"
    assert terminals and all(t in ids for t in terminals), f"[{name}] 终点非法 {terminals}"
    if gate:
        assert gate in ids, f"[{name}] gateNodeId={gate} 不存在"
    for t in terminals:
        assert _reachable(md, start, t), f"[{name}] 起点 {start} 不可达终点 {t}"
    for r in _gameplay(md)["resources"]:
        assert r["nodeId"] in ids, f"[{name}] 资源挂在不存在的节点 {r['nodeId']}"


# ---------------------------------------------------------------- 各变体变换

def v_identity(md: dict) -> dict:
    """基线本身（对照组：模拟器保真锚点，客户端本应正常交付）。"""
    md = copy.deepcopy(md)
    md["map"]["mapName"] = "variant_identity_baseline"
    return md


def v_coords(md: dict) -> dict:
    """坐标全重排（水平镜像 + 垂直翻转 + 缩放）。拓扑不变。

    证伪目标：任何基于坐标几何的假设。客户端应只用图上距离（edge.distance），
    与 (x,y) 无关——变换后决策/路线必须与基线一致。
    """
    md = copy.deepcopy(md)
    maxx = md["map"].get("maxX", 80)
    maxy = md["map"].get("maxY", 60)
    for coll in (md["nodes"], md["map"]["nodes"]):
        for n in coll:
            n["x"], n["y"] = (maxx - n["x"]) * 2 + 3, (maxy - n["y"]) + 7
    md["map"].pop("routePaths", None)
    md.pop("routePaths", None)
    md["map"]["mapName"] = "variant_coords_remap"
    return md


def v_reweight(md: dict) -> dict:
    """边权重排：主线 ROAD 大幅加重、山路/支线减轻，使起点→终点最优路线翻转。

    证伪目标："水路/某条线是主线"之类硬编码。客户端路线应由成本模型（帧数+鲜度）
    动态选出——变换后应改走原本更贵的那条线且仍能送达。
    """
    md = copy.deepcopy(md)
    for coll in (md["edges"], md["map"]["edges"]):
        for e in coll:
            rt = e.get("routeType")
            if rt == "ROAD":
                e["distance"] = int(e["distance"] * 2.4)     # 主线变贵
            elif rt in ("MOUNTAIN", "BRANCH"):
                e["distance"] = max(6, int(e["distance"] * 0.5))  # 备线变便宜
    md["map"]["mapName"] = "variant_reweight_route_flip"
    return md


def v_resources(md: dict) -> dict:
    """资源与任务候选整体改点（在中间节点间轮转分配）。

    证伪目标："冰鉴在 S03/S06""快马在 S09"之类固定位置假设。经济层应动态发现
    任意节点上的资源/任务候选。
    """
    md = copy.deepcopy(md)
    roles = _gameplay(md)["roles"]
    fixed = {roles["startNodeId"], *roles["terminalNodeIds"], roles.get("gateNodeId")}
    middle = [n["nodeId"] for n in _nodes(md) if n["nodeId"] not in fixed]
    shift = 3
    remap = {nid: middle[(i + shift) % len(middle)] for i, nid in enumerate(middle)}
    gp = _gameplay(md)
    for r in gp["resources"]:
        r["nodeId"] = remap.get(r["nodeId"], r["nodeId"])
    gp["taskCandidates"] = {
        tid: [remap.get(n, n) for n in cands] for tid, cands in gp["taskCandidates"].items()}
    gp["routeTaskBuckets"] = {
        rt: [remap.get(n, n) for n in cands] for rt, cands in gp["routeTaskBuckets"].items()}
    gp["obstacleCandidateNodeIds"] = [remap.get(n, n) for n in gp["obstacleCandidateNodeIds"]]
    md["map"]["mapName"] = "variant_resources_relocated"
    return md


def v_topology(md: dict) -> dict:
    """拓扑改形：在主线 S12-S13 之间插入新节点 S16，并新增一条 S07-S12 捷径边。

    证伪目标：固定 15 节点数、固定连通结构。寻路 / 割点(choke) / 邻接遍历
    应对任意节点数与连通性成立。
    """
    md = copy.deepcopy(md)
    new_id = "S16"
    # 新节点：普通中转站，坐标取 S12/S13 中点（几何无关，仅占位）
    def _find(nid):
        return next(n for n in md["nodes"] if n["nodeId"] == nid)
    s12, s13 = _find("S12"), _find("S13")
    newn = {"nodeId": new_id, "code": 116, "name": "新驿",
            "x": (s12["x"] + s13["x"]) // 2, "y": (s12["y"] + s13["y"]) // 2,
            "type": "STATION", "nodeType": "STATION", "start": False, "terminal": False,
            "icon": "node_station"}
    md["nodes"].append(newn)
    # 断开 S12-S13，改成 S12-S16-S13
    kept = []
    for e in md["edges"]:
        pair = {e.get("fromNodeId"), e.get("toNodeId")}
        if pair == {"S12", "S13"}:
            continue
        kept.append(e)
    md["edges"] = kept
    def _edge(eid, a, b, rt, dist):
        return {"edgeId": eid, "fromNode": a, "toNode": b, "fromNodeId": a, "toNodeId": b,
                "routeType": rt, "distance": dist, "bidirectional": True, "pathId": "P_" + eid}
    md["edges"].append(_edge("E22", "S12", new_id, "ROAD", 12))
    md["edges"].append(_edge("E23", new_id, "S13", "ROAD", 13))
    md["edges"].append(_edge("E24", "S07", "S12", "BRANCH", 70))   # 新捷径
    _sync_map(md)
    md["map"]["mapName"] = "variant_topology_insert_node"
    return md


def v_roles(md: dict) -> dict:
    """角色改派：新增终点 S16，宫门从 S14 前移到 S15、终点从 S15 后移到 S16。

    证伪目标：写死 S14=宫门 / S15=终点。delivery/combat 全走 roles.gateNodeId /
    terminalNodeIds / node.is_terminal，改派后应把新宫门·新终点认对。
    """
    md = copy.deepcopy(md)
    new_id = "S16"
    def _find(nid):
        return next(n for n in md["nodes"] if n["nodeId"] == nid)
    s15 = _find("S15")
    newn = {"nodeId": new_id, "code": 116, "name": "新兴庆宫",
            "x": s15["x"] + 2, "y": s15["y"], "type": "FINISH", "nodeType": "FINISH",
            "start": False, "terminal": True, "icon": "node_finish"}
    md["nodes"].append(newn)
    md["edges"].append({"edgeId": "E22", "fromNode": "S15", "toNode": new_id,
                        "fromNodeId": "S15", "toNodeId": new_id, "routeType": "ROAD",
                        "distance": 10, "bidirectional": True, "pathId": "P_E22"})
    _sync_map(md)
    # 角色改派 + 节点类型改型
    _set_node_type(md, "S14", "PASS")       # 旧宫门降级为普通关隘
    _set_node_type(md, "S15", "GATE")       # 旧终点升级为宫门
    _set_node_type(md, new_id, "FINISH")    # 新终点
    roles = _gameplay(md)["roles"]
    roles["gateNodeId"] = "S15"
    roles["reverifyNodeId"] = "S15"
    roles["terminalNodeIds"] = [new_id]
    roles["safeZoneNodeIds"] = [new_id]
    # 处理点：把 S14 的 VERIFY 迁到新宫门 S15
    gp = _gameplay(md)
    for p in gp["processNodes"]:
        if p["nodeId"] == "S14":
            p["nodeId"] = "S15"
    md["map"]["mapName"] = "variant_roles_gate_finish_shift"
    return md


def v_minimal(md: dict) -> dict:
    """极简线性图：8 节点全 ROAD 单链，无 KEY_PASS / 无障碍候选 / 单资源 / 无任务。

    证伪目标：地图缺少真实图的特征（关隘、障碍、多资源）时的健壮性——
    guard_max_defense 缺 KEY_PASS 走默认、combat 无咽喉可设、economy 候选稀少
    都不能崩或死循环。
    """
    md = copy.deepcopy(md)
    n = 8
    ids = [f"S{i:02d}" for i in range(1, n + 1)]
    md["nodes"] = []
    for i, nid in enumerate(ids):
        if i == 0:
            t = "START"
        elif i == n - 1:
            t = "FINISH"
        elif i == n - 2:
            t = "GATE"
        else:
            t = "STATION"
        md["nodes"].append({"nodeId": nid, "code": 100 + i + 1, "name": f"驿{i+1}",
                            "x": 5 + i * 9, "y": 30, "type": t, "nodeType": t,
                            "start": t == "START", "terminal": t == "FINISH",
                            "icon": "node"})
    md["edges"] = []
    for i in range(n - 1):
        eid = f"E{i+1:02d}"
        md["edges"].append({"edgeId": eid, "fromNode": ids[i], "toNode": ids[i + 1],
                            "fromNodeId": ids[i], "toNodeId": ids[i + 1], "routeType": "ROAD",
                            "distance": 24, "bidirectional": True, "pathId": "P_" + eid})
    _sync_map(md)
    gp = _gameplay(md)
    gp["roles"] = {"startNodeId": ids[0], "terminalNodeIds": [ids[-1]],
                   "gateNodeId": ids[-2], "safeZoneNodeIds": [ids[-1]],
                   "reverifyNodeId": ids[-2], "rushExcludedNodeIds": []}
    gp["resources"] = [{"nodeId": ids[2], "resourceType": "ICE_BOX", "count": 1, "claimRound": 2}]
    gp["processNodes"] = [
        {"nodeId": ids[3], "processType": "TRANSFER", "processRound": 4, "canWindow": False},
        {"nodeId": ids[-2], "processType": "VERIFY", "processRound": 6, "canWindow": False}]
    gp["taskCandidates"] = {}
    gp["routeTaskBuckets"] = {"ROAD": [ids[2], ids[4]]}
    gp["obstacleCandidateNodeIds"] = []
    md["map"]["mapName"] = "variant_minimal_linear"
    return md


def v_stress(md: dict) -> dict:
    """全维叠加：坐标重排 + 边权翻转 + 资源改点 + 拓扑插点。最强泛化考验。"""
    md = v_coords(md)
    md = v_reweight(md)
    md = v_resources(md)
    md = v_topology(md)
    md["map"]["mapName"] = "variant_stress_combined"
    return md


# ---------------------------------------------------------------- 汇总

VARIANTS = {
    "identity": v_identity,
    "coords": v_coords,
    "reweight": v_reweight,
    "resources": v_resources,
    "topology": v_topology,
    "roles": v_roles,
    "minimal": v_minimal,
    "stress": v_stress,
}


def build_all() -> dict[str, dict]:
    """{变体名: 合法 msg_data}。每个都过 validate()。"""
    base = load_base()
    out = {}
    for name, fn in VARIANTS.items():
        md = fn(base)
        validate(md, name)
        out[name] = md
    return out
