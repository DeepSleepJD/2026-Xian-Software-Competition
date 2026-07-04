#!/usr/bin/env python3
"""生成"真实裁判可加载"的换图变体（Unity 地图格式），检验客户端换图泛化性。

背景与关键发现（2026-07-04 逆向调试包 exe 实证）：
- 裁判读环境变量 GAME_MAP_PATH 加载外部地图（run_match.py --map 已接通）。
- 外部图**必须是 Unity 格式**（含 grid/legend/assetMapping/unity*Mapping）：这类文件
  走 readUnityMapConfig 加载路径，绕过 fastjson 反射墙；而普通 GameStartMap/map_config
  格式走 readJsonMap 会报 "default constructor not found. class GameStartMap"（GraalVM
  native-image 未给该类注册反射构造器）——三种非 Unity 格式实测全部加载失败。
- 裁判会校验 routePaths 引用的边存在。故本生成器只做**不改边集**的变换（改距离/
  改资源点/改坐标并同步 routePath 点），保证 routePaths 恒有效、对局能跑完出分。
  改拓扑/改角色/极简这类会动边集的变体，由 client/tests 的 mini_arena 无 exe harness
  覆盖（见 docs/地图泛化测试.md）。

Unity 基线取自 tools/variant_maps/server_embedded_variant_1.json（从 exe 内置图抠出）。

用法：
    python tools/gen_variant_maps.py            # 生成 unity_*.json 到 tools/variant_maps/
    python tools/run_match.py --map tools/variant_maps/unity_reweight.json --no-ui
"""

import copy
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "tools" / "variant_maps"
BASE = OUT_DIR / "server_embedded_variant_1.json"


def _load_base() -> dict:
    if not BASE.exists():
        raise SystemExit(
            f"缺少 Unity 基线图 {BASE}。它是从裁判 exe 内置图抠出的 Unity 格式地图，"
            "本生成器以它为模板做变换。")
    return json.loads(BASE.read_text(encoding="utf-8"))


def _adjacency(md: dict) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {n["nodeId"]: set() for n in md["nodes"]}
    for e in md["edges"]:
        a, b = e["fromNodeId"], e["toNodeId"]
        adj[a].add(b)
        if e.get("bidirectional", True):
            adj[b].add(a)
    return adj


def _reachable(md: dict, src: str, dst: str) -> bool:
    adj = _adjacency(md)
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


def validate(md: dict, name: str) -> None:
    """边集未动 + 起点可达终点 + 资源挂在存在的节点。"""
    ids = {n["nodeId"] for n in md["nodes"]}
    edge_ids = {e["edgeId"] for e in md["edges"]}
    for rp in md.get("routePaths") or []:
        assert rp.get("edgeId") in edge_ids, f"[{name}] routePath 引用了不存在的边 {rp.get('edgeId')}"
    roles = md["gameplay"]["roles"]
    assert _reachable(md, roles["startNodeId"], roles["terminalNodeIds"][0]), \
        f"[{name}] 起点不可达终点"
    for r in md["gameplay"]["resources"]:
        assert r["nodeId"] in ids, f"[{name}] 资源挂在不存在的节点 {r['nodeId']}"


# ---------------------------------------------------------------- 变换（不改边集）

def v_reweight(md: dict) -> dict:
    """边权翻转：主线 ROAD 大幅加重、山路/支线减轻，使最优路线改走原本更贵的线。

    证伪"水路/某条线是主线"的硬编码——客户端路线应由成本模型动态选出。routePaths
    不动（只改 distance）。
    """
    md = copy.deepcopy(md)
    for e in md["edges"]:
        rt = e.get("routeType")
        if rt == "ROAD":
            e["distance"] = int(e["distance"] * 2.4)
        elif rt in ("MOUNTAIN", "BRANCH"):
            e["distance"] = max(6, int(e["distance"] * 0.5))
    md["mapName"] = md.get("mapName", "") + " [变体:边权翻转]"
    return md


def v_resources(md: dict) -> dict:
    """资源与任务候选整体改点（中间节点间轮转）。证伪"冰鉴在 S03""快马在 S09"等固定位置。"""
    md = copy.deepcopy(md)
    roles = md["gameplay"]["roles"]
    fixed = {roles["startNodeId"], *roles["terminalNodeIds"], roles.get("gateNodeId")}
    middle = [n["nodeId"] for n in md["nodes"] if n["nodeId"] not in fixed]
    remap = {nid: middle[(i + 3) % len(middle)] for i, nid in enumerate(middle)}
    gp = md["gameplay"]
    for r in gp["resources"]:
        r["nodeId"] = remap.get(r["nodeId"], r["nodeId"])
    gp["taskCandidates"] = {t: [remap.get(n, n) for n in c] for t, c in gp["taskCandidates"].items()}
    gp["routeTaskBuckets"] = {rt: [remap.get(n, n) for n in c]
                             for rt, c in gp["routeTaskBuckets"].items()}
    gp["obstacleCandidateNodeIds"] = [remap.get(n, n) for n in gp["obstacleCandidateNodeIds"]]
    md["mapName"] = md.get("mapName", "") + " [变体:资源改点]"
    return md


def v_coords(md: dict) -> dict:
    """坐标全重排（水平镜像 + 垂直翻转），routePath 点同步变换以保持几何一致。

    证伪任何基于坐标几何的假设——客户端应只用图上距离。边集不动、routePaths 边引用有效。
    """
    md = copy.deepcopy(md)
    maxx = md["grid"]["width"]
    maxy = md["grid"]["height"]
    def tx(x, y):
        return maxx - x, maxy - y
    for n in md["nodes"]:
        n["x"], n["y"] = tx(n["x"], n["y"])
    for rp in md.get("routePaths") or []:
        for p in rp.get("points") or []:
            p["x"], p["y"] = tx(p["x"], p["y"])
    md["mapName"] = md.get("mapName", "") + " [变体:坐标重排]"
    return md


def v_combo(md: dict) -> dict:
    """边权翻转 + 资源改点 + 坐标重排 三合一。"""
    md = v_coords(v_resources(v_reweight(md)))
    md["mapName"] = md.get("mapName", "").split(" [")[0] + " [变体:三合一]"
    return md


VARIANTS = {
    "unity_reweight": v_reweight,
    "unity_resources": v_resources,
    "unity_coords": v_coords,
    "unity_combo": v_combo,
}


def main() -> int:
    base = _load_base()
    print(f"Unity 基线: {BASE.name}  nodes={len(base['nodes'])} edges={len(base['edges'])}")
    for name, fn in VARIANTS.items():
        md = fn(base)
        validate(md, name)
        out = OUT_DIR / f"{name}.json"
        out.write_text(json.dumps(md, ensure_ascii=False), encoding="utf-8")
        print(f"  ✓ {out.name:22s} {md['mapName']}")
    print("\n生成完成。用真实裁判跑变体图对局：")
    print("  python tools/run_match.py --map tools/variant_maps/unity_reweight.json --no-ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
