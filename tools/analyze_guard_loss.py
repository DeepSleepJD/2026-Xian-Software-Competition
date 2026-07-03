"""逐帧分析现网日志：对手设卡/增援时间线 + 我方被拦区间 + 对抗动作 + 终局比分。
用法: python analyze_guard_loss.py <log.jsonl> [log2.jsonl ...]
"""
import json
import sys
from collections import defaultdict


def analyze(path: str) -> None:
    my_id = None
    guards_seen = {}
    guard_events = []
    my_actions = []
    rejects = defaultdict(list)
    events = []
    score_me = score_opp = None
    my_squad = []  # (round, squadAvailable)
    my_pos = {}  # round -> (cur,next,state)
    opp_pos = {}
    last_round = 0
    opp_id = None

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            msg = rec.get("msg", {})
            name = msg.get("msg_name", "")
            data = msg.get("msg_data", {})
            if rec.get("dir") == "send":
                if name == "registration":
                    my_id = data.get("playerId")
                elif name == "action":
                    acts = data.get("actions", [])
                    if acts:
                        my_actions.append((data.get("round"), [
                            (a.get("action"), a.get("targetNodeId") or a.get("cardType") or a.get("card") or "")
                            for a in acts]))
                continue
            if "round" not in data:
                continue
            rnd = data["round"]
            last_round = max(last_round, rnd)
            for nd in data.get("nodes", []) or []:
                nid = nd.get("nodeId")
                g = nd.get("guard") or {}
                owner = g.get("ownerTeamId") or g.get("teamId") or g.get("owner") or ""
                dfs = g.get("defense", g.get("defenseValue", 0)) or 0
                cur = (owner, dfs) if owner and dfs > 0 else None
                prev = guards_seen.get(nid)
                if cur != prev:
                    if cur and prev is None:
                        guard_events.append((rnd, nid, owner, dfs, "NEW"))
                    elif cur and prev:
                        guard_events.append((rnd, nid, owner, dfs, f"{prev[1]}->{dfs}"))
                    elif cur is None and prev:
                        guard_events.append((rnd, nid, prev[0], 0, "GONE"))
                    guards_seen[nid] = cur
            for p in data.get("players", []) or []:
                pid = p.get("playerId")
                entry = (p.get("currentNodeId"), p.get("nextNodeId"), p.get("state"))
                if pid == my_id:
                    my_pos[rnd] = entry
                    score_me = p.get("totalScore", score_me)
                    sq = p.get("squadAvailable", p.get("squadCount"))
                    if sq is not None and (not my_squad or my_squad[-1][1] != sq):
                        my_squad.append((rnd, sq))
                else:
                    opp_id = pid
                    opp_pos[rnd] = entry
                    score_opp = p.get("totalScore", score_opp)
            for ar in data.get("actionResults", []) or []:
                code = ar.get("errorCode") or ""
                if code and ar.get("accepted") is False:
                    who = "me" if ar.get("playerId") == my_id else "opp"
                    rejects[(who, code, ar.get("action"))].append(rnd)
            for ev in data.get("events", []) or []:
                et = ev.get("eventType") or ev.get("type") or ""
                if any(k in str(et).upper() for k in ("GUARD", "SQUAD", "REINFORCE", "WEAKEN", "BOUNTY", "FORCED")):
                    events.append((rnd, et, json.dumps(ev, ensure_ascii=False)[:150]))

    print(f"\n{'='*70}\n{path}")
    print(f"my_id={my_id} opp_id={opp_id} last_round={last_round} FINAL me={score_me} opp={score_opp}")
    print("--- guard timeline ---")
    for e in guard_events:
        rnd = e[0]
        mp = my_pos.get(rnd, ("?", "?", "?"))
        op = opp_pos.get(rnd, ("?", "?", "?"))
        print(f"  r{rnd:<4} {e[1]} {e[2]} def={e[3]:<2} {e[4]:<10} | me@{mp[0]}->{mp[1]}({mp[2]}) opp@{op[0]}->{op[1]}({op[2]})")
    print("--- squad available over time ---")
    print("  " + " ".join(f"r{r}:{s}" for r, s in my_squad))
    print("--- my combat/squad/forced actions ---")
    for rnd, acts in my_actions:
        keep = [a for a in acts if a[0] and any(k in a[0] for k in ("GUARD", "SQUAD", "FORCED"))]
        if keep:
            print(f"  r{rnd} {keep}")
    print("--- rejects ---")
    for (who, code, act), rounds in sorted(rejects.items(), key=lambda kv: kv[1][0]):
        print(f"  [{who}] {code} {act} x{len(rounds)} r{rounds[0]}-r{rounds[-1]}")
    print("--- guard/squad events ---")
    seen_kinds = defaultdict(int)
    for rnd, et, raw in events:
        seen_kinds[et] += 1
        if seen_kinds[et] <= 6:
            print(f"  r{rnd} {raw}")
    extra = {k: v for k, v in seen_kinds.items() if v > 6}
    if extra:
        print(f"  (truncated: {extra})")


if __name__ == "__main__":
    for pth in sys.argv[1:]:
        analyze(pth)
