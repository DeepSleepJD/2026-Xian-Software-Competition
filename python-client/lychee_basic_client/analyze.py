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


def _client_version(obj: dict[str, Any]) -> Optional[str]:
    if obj.get("type") == "client":
        return (obj.get("payload") or {}).get("version")
    return None


def _load(
    path: str,
) -> tuple[Optional[int], list[dict[str, Any]], Optional[dict[str, Any]], Optional[str]]:
    """Load a match log, auto-detecting the format. Supports:
      A. our recorder:      {"kind":"meta|inquire|over", ...}
      B. our BattleLogger:  {"type":"round|start|over|error", "inquire"/"payload":...}
      C. raw wire trace:    {"t":.., "dir":"send|recv", "msg":{msg_name,msg_data}}
    Normalises all three to (my_player_id, [inquire dicts], over dict).
    """
    my_id: Optional[int] = None
    rounds: list[dict[str, Any]] = []
    over: Optional[dict[str, Any]] = None
    version: Optional[str] = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            ver = _client_version(obj)        # build stamp
            if ver:
                version = ver
                continue

            kind = obj.get("kind")            # format A (recorder)
            if kind == "meta":
                my_id = my_id or obj.get("playerId")
                continue
            if kind == "inquire":
                rounds.append(obj)
                continue
            if kind == "over":
                over = obj
                continue

            typ = obj.get("type")             # format B (BattleLogger)
            if typ == "round":
                my_id = my_id or obj.get("playerId")
                inq = obj.get("inquire")
                if inq is not None:
                    rounds.append(inq)
                continue
            if typ == "start":
                my_id = my_id or obj.get("playerId")
                continue
            if typ == "over":
                over = obj.get("payload")
                continue
            if typ == "error":
                continue

            # BattleLogger round entry without a "type" field (older format)
            if "inquire" in obj:
                my_id = my_id or obj.get("playerId")
                inq = obj.get("inquire")
                if inq:
                    rounds.append(inq)
                continue

            if "msg" in obj:                  # format C (raw wire trace)
                m = obj.get("msg") or {}
                name = m.get("msg_name")
                md = m.get("msg_data") or {}
                if obj.get("dir") == "send" and name == "registration":
                    my_id = my_id or md.get("playerId")
                elif name == "inquire":
                    rounds.append(md)
                elif name == "over":
                    over = md
                continue
    return my_id, rounds, over, version


def _player(rec: dict[str, Any], pid: int) -> Optional[dict[str, Any]]:
    for p in rec.get("players", []):
        if p.get("playerId") == pid:
            return p
    return None


def analyze_file(path: str) -> dict[str, Any]:
    my_id, rounds, over, client_version = _load(path)
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

    # --- L3: attribute lost / wasted points to concrete events ---
    def event_attribution(pid: int) -> dict[str, Any]:
        res = {
            "goodfruit_conv": 0,       # GOOD_TO_BAD: good fruit turned bad
            "forced_tax_frames": 0,    # net forced-pass time tax (after refunds)
            "residual_tax_frames": 0,  # obstacle clear-residual tax we paid
            "rejects": Counter(),      # rejected actions by error code
            "task_expire": 0,          # tasks that expired in the match (missed)
            "contest_lost": 0,         # windows we did not win
        }
        for rec in rounds:
            for e in rec.get("events", []):
                t = e.get("type")
                pl = e.get("payload") or {}
                who = pl.get("playerId")
                if t == "GOOD_TO_BAD" and who == pid:
                    res["goodfruit_conv"] += 1
                elif t == "FORCED_PASS_START" and who == pid:
                    res["forced_tax_frames"] += int(pl.get("timeTax", 0))
                elif t == "FORCED_PASS_RECALCULATE" and who == pid:
                    # obstacle cleared mid-pass refunds tax: total round dropped
                    refund = int(pl.get("oldTotalRound", 0)) - int(pl.get("newTotalRound", 0))
                    if refund > 0:
                        res["forced_tax_frames"] -= refund
                elif t == "OBSTACLE_RESIDUAL_TAX" and who == pid:
                    res["residual_tax_frames"] += int(pl.get("extraRound", 0))
                elif t == "ACTION_REJECTED" and who == pid:
                    res["rejects"][pl.get("errorCode") or "?"] += 1
                elif t == "TASK_EXPIRE":
                    res["task_expire"] += 1
                elif t and ("CONTEST" in t or "WINDOW" in t):
                    winner = pl.get("winnerPlayerId")
                    if winner is not None and winner != pid:
                        res["contest_lost"] += 1
        res["forced_tax_frames"] = max(0, res["forced_tax_frames"])
        return res

    # --- tactics actually exercised (rush tactic / resources / forced pass /
    #     guards / window outcomes) -- reflects the added strategy layers ---
    def tactics(pid: int) -> dict[str, Any]:
        t: dict[str, Any] = {
            "rush_tactic": None,
            "claim": Counter(),
            "use": Counter(),
            "forced_pass": Counter(),   # by blockType (OBSTACLE / GUARD)
            "guard_set": 0,
            "win": {"played": 0, "won": 0, "lost": 0, "draw": 0},
        }
        for rec in rounds:
            for e in rec.get("events", []):
                pl = e.get("payload") or {}
                if pl.get("playerId") != pid:
                    continue
                typ = e.get("type")
                if typ == "RUSH_TACTIC_USE":
                    t["rush_tactic"] = pl.get("rushTactic")
                elif typ == "RESOURCE_CLAIM":
                    t["claim"][pl.get("resourceType")] += 1
                elif typ == "RESOURCE_USE":
                    t["use"][pl.get("resourceType")] += 1
                elif typ == "FORCED_PASS_START":
                    t["forced_pass"][pl.get("blockType", "?")] += 1
                elif typ == "GUARD_SET":
                    t["guard_set"] += 1
        # window outcomes from the contests we were a party to
        done: set = set()
        for rec in rounds:
            for c in rec.get("contests", []):
                cid = c.get("contestId")
                if cid in done or pid not in (c.get("redPlayerId"), c.get("bluePlayerId")):
                    continue
                if c.get("resolved"):
                    done.add(cid)
                    t["win"]["played"] += 1
                    am_red = c.get("redPlayerId") == pid
                    mine = c.get("redPoint", 0) if am_red else c.get("bluePoint", 0)
                    theirs = c.get("bluePoint", 0) if am_red else c.get("redPoint", 0)
                    t["win"]["won" if mine > theirs else "lost" if mine < theirs else "draw"] += 1
        return t

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
        "client_version": client_version,
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
        "events": {my_id: event_attribution(my_id), opp_id: event_attribution(opp_id)},
        "tactics": tactics(my_id),
    }


def format_report(a: dict[str, Any]) -> str:
    my, opp = a["my_id"], a["opp_id"]
    md, od = a["my_detail"], a["opp_detail"]
    out: list[str] = []
    out.append(f"客户端构建 = {a.get('client_version') or '(日志未标记版本)'}")
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

    # --- tactics exercised (reflects the added strategy layers) ---
    t = a.get("tactics", {})
    out.append("== 战术使用(我方) ==")
    out.append(f"  终局急策: {t.get('rush_tactic') or '未使用'}")
    claim = t.get("claim") or {}
    use = t.get("use") or {}
    out.append(f"  资源领取: {dict(claim) or '无'}")
    out.append(f"  资源使用: {dict(use) or '无'}")
    fp = t.get("forced_pass") or {}
    out.append(f"  强制通行: {dict(fp) or '无'}  (OBSTACLE=障碍, GUARD=敌方设卡)")
    out.append(f"  我方设卡: {t.get('guard_set', 0)} 次")
    w = t.get("win") or {}
    out.append(
        f"  窗口出牌: 参与 {w.get('played', 0)} 次 (胜 {w.get('won', 0)} / "
        f"负 {w.get('lost', 0)} / 平 {w.get('draw', 0)})"
    )
    out.append("")

    # --- L3: event attribution ---
    ev = a["events"].get(my, {})
    out.append("== L3 丢分/浪费事件归因(我方) ==")
    gf = ev.get("goodfruit_conv", 0)
    out.append(f"  好果转坏: {gf} 次  → 约 -{gf * 1.8:.1f} 分(好果数量分)")
    out.append(f"  强制通行时间税(净): {ev.get('forced_tax_frames', 0)} 帧  → 纯浪费")
    out.append(f"  清障残留税: {ev.get('residual_tax_frames', 0)} 帧  → 纯浪费")
    rj = ev.get("rejects") or {}
    out.append(f"  被拒动作: {dict(rj) or '无'}  → 浪费帧/潜在违规")
    out.append(f"  任务过期(全场): {ev.get('task_expire', 0)} 个  → 错失的任务分机会")
    out.append(f"  窗口败北: {ev.get('contest_lost', 0)} 次")
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
    parser = argparse.ArgumentParser(
        description="Analyse a recorded Lychee match (recorder / BattleLogger / raw-wire logs). "
        "Runs offline with the standard library only."
    )
    parser.add_argument("path", help="log file (.jsonl)")
    parser.add_argument(
        "-o", "--out",
        help="also write the (small) report to this file, so only the report needs "
        "to leave an air-gapped machine while the large raw log stays put",
    )
    args = parser.parse_args()
    report = format_report(analyze_file(args.path))
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"\n[report written to {args.out}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
