#!/usr/bin/env python3
"""ETA 模型校验：静态计算过程展示 + 真实对局逐边/逐处理实测对账。

用法（仓库根目录）：
    python tools/verify_eta.py                          # 静态表 + 扫描默认日志
    python tools/verify_eta.py --logs logs/battle_rounds_2751.jsonl ...

静态部分：按任务书 2.3.2 公式逐边计算新图（tools/variant_maps/公开地图.json）
的到站帧数，并展开三条开局路线到 S10 / 终点的累计账，供人工校对。

实测部分：解析 battle_rounds JSONL（每回合含双方完整状态），测量每次
"离开节点A -> 到达节点B" 的实际帧数、每次 PROCESSING/VERIFYING 的实际时长，
与模型预测对比。带马/天气/等待的样本单独标注。
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAP_PATH = REPO / "tools" / "variant_maps" / "公开地图.json"

COEF = {"ROAD": 1380, "WATER": 1250, "MOUNTAIN": 1780, "BRANCH": 1550}
BASE = 1000
HORSE_SPEED = {"FAST_HORSE": 1200, "SHORT_HORSE": 1150, "RUSH_SPEED": 1300}


def frames_plain(dist: int, rt: str, speed: int = BASE) -> int:
    required = math.ceil(dist * COEF[rt])
    return math.ceil(required / speed)


# ---------------- 静态：计算过程展示 ----------------

def load_map():
    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    edges = {e["edgeId"]: e for e in data["edges"]}
    process = {p["nodeId"]: p for p in data["gameplay"]["processNodes"]}
    return data, edges, process


def print_static():
    _, edges, process = load_map()
    print("=" * 78)
    print("① 逐边计算（frames = ceil( ceil(dist×coef) / 每帧移动量 )）")
    print("=" * 78)
    print(f"{'边':<4}{'从→到':<10}{'类型':<10}{'距离':>4} {'所需移动量':>8} "
          f"{'素帧':>5} {'短马':>5} {'快马':>5}")
    for eid, e in sorted(edges.items()):
        rt, d = e["routeType"], e["distance"]
        req = math.ceil(d * COEF[rt])
        print(f"{eid:6}{e['fromNodeId']}→{e['toNodeId']:5}{rt:9}{d:4} "
              f"{req:>8}  {frames_plain(d, rt):>5} {frames_plain(d, rt, 1150):>5} "
              f"{frames_plain(d, rt, 1200):>5}")

    routes = {
        "山路线 (S10最快)": ["S01", "S06", "S08", "S10", "S13", "S14", "S15"],
        "水路线": ["S01", "S02", "S04", "S05", "S09", "S10", "S13", "S14", "S15"],
        "官道线": ["S01", "S02", "S03", "S07", "S09", "S10", "S13", "S14", "S15"],
    }
    by_pair = {}
    for e in edges.values():
        by_pair[(e["fromNodeId"], e["toNodeId"])] = e
        if e.get("bidirectional"):
            by_pair[(e["toNodeId"], e["fromNodeId"])] = e

    print()
    print("=" * 78)
    print("② 路线累计账（素速无天气；到 S10 的帧数 = 赛跑账，含途中强制处理）")
    print("   注: S14 宫门验核(6) 只在 RUSH 提交; 到S10列不含 S10 自身处理")
    print("=" * 78)
    for name, path in routes.items():
        total = 0
        parts = []
        eta_s10 = None
        for a, b in zip(path, path[1:]):
            e = by_pair[(a, b)]
            f = frames_plain(e["distance"], e["routeType"])
            total += f
            parts.append(f"{a}→{b} {e['routeType'][:1]}{e['distance']}={f}")
            if b == "S10" and eta_s10 is None:
                eta_s10 = total
            p = process.get(b)
            if p and b != "S14":
                total += p["processRound"]
                parts.append(f"[{b}处理+{p['processRound']}]")
        gate_v = process.get("S14", {}).get("processRound", 6)
        print(f"\n{name}: 到S10 = {eta_s10} 帧, 到S15(不含验核/交付动作) = {total} 帧"
              f" (+验核{gate_v}+交付2 = {total + gate_v + 2})")
        print("   " + " ".join(parts))


# ---------------- 实测：对局日志对账 ----------------

def iter_entries(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def player_view(inquire, pid):
    for p in inquire.get("players", []) or []:
        if p.get("playerId") == pid:
            return p
    return None


def active_horse(p):
    best = None
    for b in p.get("buffs") or []:
        t = b.get("type")
        if t in HORSE_SPEED and int(b.get("remainingRound", 0) or 0) > 0:
            best = t if best is None else best
    return best


def weather_now(inquire):
    w = inquire.get("weather") or {}
    cur = w.get("current") or w.get("currentWeather") or {}
    if isinstance(cur, dict):
        return cur.get("type") or cur.get("weatherType")
    return None


def scan_log(path: Path, edge_stats, proc_stats, notes):
    """把日志切成对局段，跟踪双方每次移动与处理。"""
    edges_by_id = {}
    edges_by_pair = {}
    process_round = {}
    # per (match_seq, playerId) 的移动状态机
    track = {}
    match_seq = 0

    def load_edges(edge_list):
        edges_by_id.clear()
        edges_by_pair.clear()
        for e in edge_list or []:
            eid = e.get("edgeId")
            if not eid:
                continue
            edges_by_id[eid] = e
            a, b = e.get("fromNodeId"), e.get("toNodeId")
            edges_by_pair[(a, b)] = e
            if e.get("bidirectional"):
                edges_by_pair[(b, a)] = e

    for entry in iter_entries(path):
        etype = entry.get("type")
        if etype == "start":
            match_seq += 1
            track.clear()
            payload = entry.get("payload") or {}
            m = payload.get("map") or {}
            load_edges(payload.get("edges") or m.get("edges"))
            for p in (m.get("gameplay") or {}).get("processNodes", []) or []:
                process_round[p["nodeId"]] = int(p.get("processRound", 0) or 0)
            continue
        if etype != "round":
            continue
        inquire = entry.get("inquire") or {}
        if not edges_by_id:
            load_edges(inquire.get("edges"))
        rnd = entry.get("round")
        if rnd is None:
            continue
        for p in inquire.get("players", []) or []:
            pid = p.get("playerId")
            key = (path.name, match_seq, pid)
            st = track.setdefault(key, {
                "node": None, "edge": None, "edge_start_round": None,
                "edge_from": None, "waits": 0, "horse_frames": 0,
                "weather_frames": 0, "proc_state": None, "proc_start": None,
                "proc_node": None, "last_idle_node_round": None,
            })
            state = p.get("state")
            node = p.get("currentNodeId")
            redge = p.get("routeEdgeId")
            wtype = weather_now(inquire)

            # ---- 移动测量 ----
            if redge and st["edge"] is None:
                # 本回合首次看到上边：出发回合 = 上一次停在起点的回合
                st["edge"] = redge
                st["edge_from"] = node
                st["edge_start_round"] = rnd
                st["waits"] = 0
                st["horse_frames"] = 0
                st["weather_frames"] = 0
            elif redge and st["edge"] == redge:
                if state == "WAITING":
                    st["waits"] += 1
                if active_horse(p):
                    st["horse_frames"] += 1
                if wtype in ("HEAVY_RAIN", "MOUNTAIN_FOG"):
                    st["weather_frames"] += 1
            elif st["edge"] and not redge:
                # 到达（或改道/冻结后消失——按到达节点区分）
                e = edges_by_id.get(st["edge"])
                if e is not None and node in (e.get("fromNodeId"), e.get("toNodeId")) \
                        and node != st["edge_from"]:
                    frames = rnd - st["edge_start_round"] + 1
                    tag = "plain"
                    if st["horse_frames"]:
                        tag = f"horse{st['horse_frames']}"
                    if st["weather_frames"]:
                        tag += f"+wx{st['weather_frames']}"
                    if st["waits"]:
                        tag += f"+wait{st['waits']}"
                    model = frames_plain(e["distance"], e["routeType"])
                    edge_stats[(e.get("edgeId"), e["routeType"], e["distance"], tag)].append(
                        (frames, model, path.name, match_seq, pid, st["edge_start_round"])
                    )
                st["edge"] = None
                st["edge_from"] = None
                st["edge_start_round"] = None

            # ---- 处理测量 ----
            if state in ("PROCESSING", "VERIFYING") and st["proc_state"] != state:
                st["proc_state"] = state
                st["proc_start"] = rnd
                st["proc_node"] = node
            elif state not in ("PROCESSING", "VERIFYING") and st["proc_state"]:
                dur = rnd - st["proc_start"]
                model = process_round.get(st["proc_node"], None)
                proc_stats[(st["proc_node"], st["proc_state"])].append(
                    (dur, model, path.name, match_seq, pid, st["proc_start"])
                )
                st["proc_state"] = None


def print_empirical(edge_stats, proc_stats):
    print()
    print("=" * 78)
    print("③ 实测对账：边通行（观测帧数 vs 模型帧数；样本含马/天气/等待的已标注）")
    print("=" * 78)
    print(f"{'边':6}{'类型':9}{'距':>4} {'条件':14}{'模型':>5} {'观测(次数)':<24}{'偏差'}")
    rows = 0
    for (eid, rt, d, tag), samples in sorted(edge_stats.items()):
        obs = defaultdict(int)
        model = samples[0][1]
        for f, _m, *_ in samples:
            obs[f] += 1
        obs_s = " ".join(f"{f}×{c}" for f, c in sorted(obs.items()))
        deltas = sorted({f - model for f, *_ in [(s[0],) for s in samples]})
        flag = "" if deltas == [0] or (tag != "plain") else "  <-- 偏差!"
        if tag != "plain":
            flag = "  (非素速,仅记录)"
        print(f"{eid or '?':6}{rt:9}{d:>4} {tag:14}{model:>5} {obs_s:<24}"
              f"{'+'.join(str(x) for x in deltas):>4}{flag}")
        rows += 1
    if not rows:
        print("  (日志中没有完成的边通行样本)")

    print()
    print("=" * 78)
    print("④ 实测对账：处理/验核时长（观测 = PROCESSING 状态持续帧数）")
    print("=" * 78)
    print(f"{'节点':6}{'状态':12}{'配置':>5} {'观测(次数)'}")
    for (node, state), samples in sorted(proc_stats.items()):
        obs = defaultdict(int)
        model = samples[0][1]
        for dur, _m, *_ in samples:
            obs[dur] += 1
        obs_s = " ".join(f"{d}×{c}" for d, c in sorted(obs.items()))
        print(f"{node:6}{state:12}{str(model):>5} {obs_s}")
    if not proc_stats:
        print("  (无处理样本)")


def main() -> int:
    ap = argparse.ArgumentParser()
    default_logs = (
        list((REPO / "python-client").glob("battle_rounds_*.jsonl"))
        + list((REPO / "logs").glob("battle_rounds_*.jsonl"))
    )
    ap.add_argument("--logs", nargs="*", type=Path, default=default_logs)
    ap.add_argument("--no-static", action="store_true")
    args = ap.parse_args()

    if not args.no_static:
        print_static()

    edge_stats = defaultdict(list)
    proc_stats = defaultdict(list)
    notes = []
    for p in args.logs:
        if p.exists():
            print(f"\n[扫描] {p} ({p.stat().st_size // 1048576}MB)", file=sys.stderr)
            scan_log(p, edge_stats, proc_stats, notes)
    print_empirical(edge_stats, proc_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
