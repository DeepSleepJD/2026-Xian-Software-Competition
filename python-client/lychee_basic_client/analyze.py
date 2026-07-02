"""Analyse a recorded match (JSONL from recorder.py) to see where we lose points.

Usage:
    py -3 -m lychee_basic_client.analyze <recording.jsonl>
"""
import argparse
import json
import sys
from collections import Counter
from typing import Any, Optional

ROUTE_TYPES = ("ROAD", "WATER", "MOUNTAIN", "BRANCH")
WASTE_STATES = {"RESTING", "CONTESTING", "FORCED_PASSING"}
# how weather types "hit" a moving car, for freshness attribution
WEATHER_HITS = {"HOT": None, "HEAVY_RAIN": "WATER", "MOUNTAIN_FOG": "MOUNTAIN"}
FRESH_WINDOW = 40  # frames, for locating where we bleed freshness vs the opponent

SCORE_KEYS = ("delivery", "tasks", "goodFruit", "freshness", "time", "bounty", "penalty")
SCORE_LABELS = {
    "delivery": "送达基础分",
    "tasks": "皇榜任务分",
    "goodFruit": "好果数量分",
    "freshness": "鲜度品质分",
    "time": "用时分",
    "bounty": "破关悬赏分",
    "penalty": "惩罚(扣分)",
}


def _load(path: str) -> tuple[Optional[int], list[dict[str, Any]], Optional[dict[str, Any]]]:
    my_id: Optional[int] = None
    rounds: list[dict[str, Any]] = []
    over: Optional[dict[str, Any]] = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            kind = obj.get("kind")
            if kind == "meta":
                my_id = obj.get("playerId")
            elif kind == "inquire":
                rounds.append(obj)
            elif kind == "over":
                over = obj
    return my_id, rounds, over


def _player(rec: dict[str, Any], pid: int) -> Optional[dict[str, Any]]:
    for p in rec.get("players", []):
        if p.get("playerId") == pid:
            return p
    return None


def analyze_file(path: str) -> dict[str, Any]:
    my_id, rounds, over = _load(path)
    if not rounds:
        raise SystemExit(f"no inquire records in {path}")
    last = rounds[-1]
    ids = [p.get("playerId") for p in last.get("players", [])]
    if my_id is None:
        my_id = ids[0]
    opp_id = next((i for i in ids if i != my_id), None)

    over_players = {p.get("playerId"): p for p in (over or {}).get("players", [])}

    def final_detail(pid: int) -> dict[str, Any]:
        # `over` is authoritative; fall back to the last in-match preview
        op = over_players.get(pid)
        if op and op.get("scoreDetail"):
            return op["scoreDetail"]
        for rec in reversed(rounds):
            p = _player(rec, pid)
            if p and p.get("scoreDetail"):
                return p["scoreDetail"]
        return {}

    def delivery_info(pid: int) -> dict[str, Any]:
        op = over_players.get(pid)
        if op:
            return {
                "round": op.get("deliverRound") or None,
                "freshness": op.get("freshness"),
                "goodFruit": op.get("goodFruit"),
                "delivered": op.get("delivered"),
            }
        for rec in rounds:
            p = _player(rec, pid)
            if p and p.get("delivered"):
                return {
                    "round": rec.get("round"),
                    "freshness": p.get("freshness"),
                    "goodFruit": p.get("goodFruit"),
                    "delivered": True,
                }
        p = _player(last, pid) or {}
        return {
            "round": None,
            "freshness": p.get("freshness"),
            "goodFruit": p.get("goodFruit"),
            "delivered": False,
        }

    # tasks completed per owner (scan all rounds; completed tasks may leave the list)
    task_done: dict[int, dict[str, int]] = {my_id: {}, opp_id: {}}
    for rec in rounds:
        for t in rec.get("tasks", []):
            if t.get("completed"):
                owner = t.get("ownerPlayerId")
                if owner in task_done:
                    task_done[owner][t.get("taskId")] = int(t.get("score", 0))

    # rejected actions per player
    rejects: dict[int, dict[str, int]] = {my_id: {}, opp_id: {}}
    for rec in rounds:
        for r in rec.get("actionResults", []):
            if not r.get("accepted", True):
                pid = r.get("playerId")
                if pid in rejects:
                    key = f"{r.get('action')}:{r.get('result') or r.get('errorCode') or '?'}"
                    rejects[pid][key] = rejects[pid].get(key, 0) + 1

    # time spent in each main-car state per player
    state_hist: dict[int, dict[str, int]] = {my_id: {}, opp_id: {}}
    for rec in rounds:
        for pid in (my_id, opp_id):
            p = _player(rec, pid)
            if p:
                st = p.get("state", "?")
                state_hist[pid][st] = state_hist[pid].get(st, 0) + 1

    # --- L2: frame breakdown + freshness divergence ---
    def frame_breakdown(pid: int) -> dict[str, Any]:
        buckets = {"move": 0, "process": 0, "verify": 0, "wait": 0, "waste": 0, "other": 0}
        move_by_rt: Counter = Counter()
        weather_hit = 0
        for rec in rounds:
            p = _player(rec, pid)
            if not p:
                continue
            st = p.get("state")
            if st == "MOVING":
                buckets["move"] += 1
                rt = p.get("routeType") or "?"
                move_by_rt[rt] += 1
                for w in rec.get("weather", {}).get("active", []):
                    region = WEATHER_HITS.get(w.get("type"))
                    if region is None or region == rt:  # HOT hits everywhere
                        weather_hit += 1
                        break
            elif st == "PROCESSING":
                buckets["process"] += 1
            elif st == "VERIFYING":
                buckets["verify"] += 1
            elif st in ("WAITING", "IDLE"):
                buckets["wait"] += 1
            elif st in WASTE_STATES:
                buckets["waste"] += 1
            else:
                buckets["other"] += 1
        return {"buckets": buckets, "move_by_rt": dict(move_by_rt), "weather_hit": weather_hit}

    # freshness series while BOTH are still undelivered (after delivery it freezes)
    fresh: list[tuple[int, float, float]] = []
    for rec in rounds:
        mp, op = _player(rec, my_id), _player(rec, opp_id)
        if mp and op and not mp.get("delivered") and not op.get("delivered"):
            fresh.append((rec.get("round"), mp.get("freshness", 0.0), op.get("freshness", 0.0)))

    fresh_checkpoints = [(r, mf, of) for (r, mf, of) in fresh if r and r % 100 == 0]

    # window where our freshness deficit (opp - me) grows the most
    worst_window: dict[str, Any] = {}
    if len(fresh) > FRESH_WINDOW:
        gaps = [of - mf for (_, mf, of) in fresh]  # positive = we are behind
        best_i, best_inc = 0, -1e9
        for i in range(len(fresh) - FRESH_WINDOW):
            inc = gaps[i + FRESH_WINDOW] - gaps[i]
            if inc > best_inc:
                best_inc, best_i = inc, i
        a, b = fresh[best_i][0], fresh[best_i + FRESH_WINDOW][0]
        route_mix: Counter = Counter()
        weathers: set = set()
        buffs_seen: set = set()
        for rec in rounds:
            r = rec.get("round")
            if r is None or not (a <= r <= b):
                continue
            p = _player(rec, my_id)
            if not p:
                continue
            if p.get("state") == "MOVING":
                route_mix[p.get("routeType") or "?"] += 1
            for w in rec.get("weather", {}).get("active", []):
                weathers.add(w.get("type"))
            for bf in p.get("buffs", []):
                buffs_seen.add(bf.get("type"))
        worst_window = {
            "start": a,
            "end": b,
            "gap_increase": round(best_inc, 2),
            "my_route_mix": dict(route_mix),
            "weather": sorted(w for w in weathers if w),
            "buffs": sorted(b for b in buffs_seen if b),
        }

    # score-gap timeline (opp.total - my.total) and worst round
    gap_series: list[tuple[int, float]] = []
    for rec in rounds:
        mp, op = _player(rec, my_id), _player(rec, opp_id)
        if mp and op:
            mt = (mp.get("scoreDetail") or {}).get("total", mp.get("totalScore", 0))
            ot = (op.get("scoreDetail") or {}).get("total", op.get("totalScore", 0))
            gap_series.append((rec.get("round"), ot - mt))
    worst = max(gap_series, key=lambda x: x[1]) if gap_series else (None, 0)

    return {
        "path": path,
        "match_id": last.get("matchId"),
        "rounds": len(rounds),
        "my_id": my_id,
        "opp_id": opp_id,
        "result_type": (over or {}).get("resultType"),
        "over_reason": (over or {}).get("overReason"),
        "winner_id": (over or {}).get("winnerPlayerId"),
        "has_over": over is not None,
        "my_detail": final_detail(my_id),
        "opp_detail": final_detail(opp_id),
        "my_delivery": delivery_info(my_id),
        "opp_delivery": delivery_info(opp_id),
        "task_done": {k: (len(v), sum(v.values())) for k, v in task_done.items()},
        "rejects": rejects,
        "state_hist": state_hist,
        "gap_checkpoints": [g for g in gap_series if g[0] and g[0] % 100 == 0],
        "worst_gap": worst,
        "breakdown": {my_id: frame_breakdown(my_id), opp_id: frame_breakdown(opp_id)},
        "fresh_checkpoints": fresh_checkpoints,
        "fresh_worst_window": worst_window,
    }


def format_report(a: dict[str, Any]) -> str:
    my, opp = a["my_id"], a["opp_id"]
    md, od = a["my_detail"], a["opp_detail"]
    out: list[str] = []
    out.append(f"对局 {a['match_id']}  记录回合数={a['rounds']}  我方={my} 对手={opp}")
    if a.get("has_over"):
        win = a.get("winner_id")
        who = "我方胜" if win == my else ("对手胜" if win == opp else "平局/无胜方")
        out.append(
            f"结果: {a.get('result_type')} ({a.get('over_reason')})  胜者={win} -> {who}"
        )
    else:
        out.append("(记录缺少 over 消息；最终分用最后一帧预览，可能不准)")
    out.append("")
    out.append(f"{'分项':<12}{'我方':>8}{'对手':>8}{'差值(我-对)':>12}")
    out.append("-" * 42)
    deltas = []
    for k in SCORE_KEYS:
        mv = md.get(k, 0)
        ov = od.get(k, 0)
        d = mv - ov
        deltas.append((k, d))
        out.append(f"{SCORE_LABELS[k]:<12}{mv:>8}{ov:>8}{d:>+12}")
    mt = md.get("total", 0)
    ot = od.get("total", 0)
    out.append("-" * 42)
    out.append(f"{'总分':<12}{mt:>8}{ot:>8}{mt - ot:>+12}")
    out.append("")

    md_del, od_del = a["my_delivery"], a["opp_delivery"]
    out.append("交付对比:")
    out.append(
        f"  我方: 交付帧={md_del.get('round')} 鲜度={md_del.get('freshness')} "
        f"好果={md_del.get('goodFruit')}"
    )
    out.append(
        f"  对手: 交付帧={od_del.get('round')} 鲜度={od_del.get('freshness')} "
        f"好果={od_del.get('goodFruit')}"
    )
    tn_my, tb_my = a["task_done"].get(my, (0, 0))
    tn_op, tb_op = a["task_done"].get(opp, (0, 0))
    out.append(
        f"任务: 我方完成 {tn_my} 个(基础分 {tb_my}) | 对手完成 {tn_op} 个(基础分 {tb_op})"
    )
    out.append("")

    out.append("被拒动作(次数):")
    out.append(f"  我方: {a['rejects'].get(my) or '无'}")
    out.append(f"  对手: {a['rejects'].get(opp) or '无'}")
    out.append("")

    wr, wg = a["worst_gap"]
    out.append(f"分差最大时刻: 第 {wr} 帧, 对手领先 {wg:+.0f}")
    if a["gap_checkpoints"]:
        cp = "  ".join(f"r{r}:{g:+.0f}" for r, g in a["gap_checkpoints"])
        out.append(f"分差(对手-我方)时间线: {cp}")
    out.append("")

    # --- L2: frame breakdown ---
    out.append("== L2 帧数拆解(帧) ==")
    bd_my = a["breakdown"].get(my, {})
    bd_op = a["breakdown"].get(opp, {})

    def _fmt_bd(bd: dict[str, Any]) -> str:
        b = bd.get("buckets", {})
        mv = bd.get("move_by_rt", {})
        mv_s = "/".join(f"{rt}:{mv.get(rt, 0)}" for rt in ROUTE_TYPES if mv.get(rt))
        return (
            f"移动{b.get('move', 0)}({mv_s or '-'})  处理{b.get('process', 0)}  "
            f"验核{b.get('verify', 0)}  等待{b.get('wait', 0)}  "
            f"浪费{b.get('waste', 0)}(休整/窗口/强制通行)  天气命中移动{bd.get('weather_hit', 0)}"
        )

    out.append(f"  我方: {_fmt_bd(bd_my)}")
    out.append(f"  对手: {_fmt_bd(bd_op)}")
    out.append("")

    # --- L2: freshness divergence ---
    out.append("== L2 鲜度分歧 ==")
    if a["fresh_checkpoints"]:
        cp = "  ".join(
            f"r{r}:我{mf:.1f}/对{of:.1f}(差{of - mf:+.1f})" for r, mf, of in a["fresh_checkpoints"]
        )
        out.append(f"  鲜度时间线: {cp}")
    ww = a["fresh_worst_window"]
    if ww:
        rm = "/".join(f"{k}:{v}" for k, v in sorted(ww["my_route_mix"].items()))
        w = ",".join(ww["weather"]) or "无"
        bf = ",".join(ww["buffs"]) or "无"
        out.append(
            f"  最快掉队窗口: r{ww['start']}-{ww['end']} 内鲜度差扩大 {ww['gap_increase']:+.1f}"
        )
        out.append(f"    这段我方在: 路线[{rm or '-'}]  天气[{w}]  增益[{bf}]")
    else:
        out.append("  (双方同时在途的帧不足，无法定位窗口)")
    out.append("")

    # conclusion: biggest losing components
    losing = sorted((d for d in deltas if d[1] < 0), key=lambda x: x[1])
    out.append("== 失分点(按差值从大到小) ==")
    if not losing:
        out.append("  没有落后的分项；总分领先。")
    else:
        for k, d in losing:
            out.append(f"  {SCORE_LABELS[k]}: 落后 {d:+d}")
    return "\n".join(out)


def main() -> int:
    # ensure Chinese labels print correctly regardless of the console code page
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Analyse a recorded Lychee match")
    parser.add_argument("path", help="recording .jsonl file")
    args = parser.parse_args()
    print(format_report(analyze_file(args.path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
