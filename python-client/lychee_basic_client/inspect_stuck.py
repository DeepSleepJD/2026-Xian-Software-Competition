"""Dump the frames around the first "stuck" region (a run of our rejected
actions) of a match log, with our car state, the action we sent, the reject
reasons, and the current/target node fields. Use it to diagnose why the client
gets blocked (e.g. an enemy guard on the route) when the aggregate report only
shows "never delivered".

Handles our BattleLogger log ({"type":"round", "inquire":..., "clientAction":..})
and a raw wire trace ({"t":.., "dir":.., "msg":{msg_name,msg_data}}).

Usage:
    py -3 -m lychee_basic_client.inspect_stuck battle_rounds.jsonl [--before N] [--after N]
"""
import argparse
import json
import sys
from typing import Any, Optional

# fields worth seeing on our car and on the nodes when stuck
CAR_FIELDS = (
    "state", "currentNodeId", "nextNodeId", "routeEdgeId",
    "moveProgress", "edgeProgressPermille",
)


def _load(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _unwrap(row: dict[str, Any]) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Return (inquire, client_action) for a row, or (None, {}) if not a round."""
    if row.get("type") == "round":
        return row.get("inquire") or {}, row.get("clientAction") or {}
    if (row.get("msg") or {}).get("msg_name") == "inquire":
        return (row["msg"].get("msg_data") or {}), {}
    return None, {}


def _my_id(rows: list[dict[str, Any]]) -> Optional[int]:
    for row in rows:
        if row.get("type") in ("round", "start", "over"):
            if row.get("playerId") is not None:
                return row.get("playerId")
        if row.get("dir") == "send" and (row.get("msg") or {}).get("msg_name") == "registration":
            return ((row["msg"].get("msg_data")) or {}).get("playerId")
    return None


# error codes that mean we're actually stuck (vs a benign transient reject)
BLOCKING_CODES = {"MOVE_BLOCKED_BY_GUARD", "MOVING_ACTION_FORBIDDEN", "TARGET_NOT_REACHABLE"}


def _my_rejects(inq: dict[str, Any], me_id: Optional[int]) -> list[dict[str, Any]]:
    return [
        ar for ar in (inq.get("actionResults") or [])
        if ar.get("playerId") == me_id and not ar.get("accepted", True)
    ]


def _has_blocking_reject(inq: dict[str, Any], me_id: Optional[int]) -> bool:
    return any(r.get("errorCode") in BLOCKING_CODES for r in _my_rejects(inq, me_id))


def build_report(path: str, before: int, after: int) -> str:
    rows = _load(path)
    me_id = _my_id(rows)
    out = [f"me_id = {me_id}"]

    seq = []
    for row in rows:
        inq, ca = _unwrap(row)
        if not inq or "players" not in inq:
            continue
        mep = next((p for p in (inq.get("players") or []) if p.get("playerId") == me_id), None)
        if mep:
            seq.append((inq.get("round"), inq, mep, ca))

    # prefer the first genuinely-blocking reject (guard / forbidden / unreachable);
    # fall back to the first reject of any kind so benign transients don't hide it
    stuck = next(
        (i for i, (_, inq, _, _) in enumerate(seq) if _has_blocking_reject(inq, me_id)), None
    )
    if stuck is None:
        stuck = next((i for i, (_, inq, _, _) in enumerate(seq) if _my_rejects(inq, me_id)), None)
    out.append(f"stuck_idx = {stuck}  (rounds recorded: {len(seq)})")

    if stuck is not None:
        lo, hi = max(0, stuck - before), min(len(seq), stuck + after)
        for rnd, inq, mep, ca in seq[lo:hi]:
            sent = [
                {k: a.get(k) for k in ("action", "targetNodeId")}
                for a in ((ca or {}).get("actions") or [])
            ]
            rej = [
                {k: ar.get(k) for k in ("action", "accepted", "result", "errorCode")}
                for ar in (inq.get("actionResults") or [])
                if ar.get("playerId") == me_id
            ]
            nodes = inq.get("nodes") or []
            tgt = next((n for n in nodes if n.get("nodeId") == mep.get("nextNodeId")), {})
            cur = next((n for n in nodes if n.get("nodeId") == mep.get("currentNodeId")), {})
            out.append(f"--- r{rnd}")
            out.append(f"  me: {{{', '.join(f'{k}={mep.get(k)!r}' for k in CAR_FIELDS)}}}")
            out.append(f"  sent: {sent or '(client action not recorded)'}")
            out.append(f"  myResults: {rej}")
            out.append(f"  targetNode: {tgt}")
            out.append(f"  curNode: {cur}")

    out.append("=== GUARD events ===")
    for rnd, inq, _, _ in seq:
        for ev in (inq.get("events") or []):
            if "GUARD" in ((ev.get("type")) or ""):
                out.append(f"  r{rnd} {ev.get('type')} {ev.get('payload')}")
    return "\n".join(out)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Dump the frames around a match log's first stuck region")
    parser.add_argument("path", help="log file (.jsonl)")
    parser.add_argument("--before", type=int, default=3, help="frames before the stuck point")
    parser.add_argument("--after", type=int, default=8, help="frames after the stuck point")
    parser.add_argument("-o", "--out", help="also write the (small) dump to this file")
    args = parser.parse_args()
    report = build_report(args.path, args.before, args.after)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
        print(f"\n[written to {args.out}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
