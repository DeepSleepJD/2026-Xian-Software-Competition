"""Window-card policy for the 3-tap contest windows (task book 5.4).

The card matrix is rock-paper-scissors-like:
    XIAN_GONG beats YAN_DIE, BING_ZHENG ; loses to QIANG_XING
    BING_ZHENG beats YAN_DIE, QIANG_XING ; loses to XIAN_GONG
    QIANG_XING beats XIAN_GONG           ; loses to YAN_DIE, BING_ZHENG
    YAN_DIE    beats QIANG_XING          ; loses to XIAN_GONG, BING_ZHENG

With hidden simultaneous choices there is no dominant pure play, so we use a
resource-aware heuristic. If we still have good fruit, spend XIAN_GONG even on
low-value windows: repeated window draws are worse than the fruit cost because
they can lock both players on a process node for hundreds of frames. Once good
fruit is gone, fall back to the cheapest card we can still pay.
"""
from typing import Any, Optional

# higher = more worth spending a card to win
CONTEST_PRIORITY = {
    "GATE": 100,
    "PASS": 90,
    "OBSTACLE": 40,
    "TASK": 30,
    "DOCK": 20,
    "RESOURCE": 15,
}
HORSE_BUFFS = {"FAST_HORSE", "SHORT_HORSE", "RUSH_SPEED"}


def active_contest(
    player_id: int, contests: list[dict[str, Any]], round_no: Optional[int] = None
) -> Optional[dict[str, Any]]:
    """The most valuable still-playable window this player is a party to, or None.

    A window is playable only while it is unresolved and within its deadline;
    playing on an already-ended window is what triggers a server error / retire,
    so we exclude those here (and the caller also de-dups per tap)."""
    mine = []
    for c in contests:
        cid = c.get("contestId")
        # only real, playable windows: a valid id (not a None/"SUPPRESSED:..."
        # pseudo-contest) and an actual play tap. Carding a suppressed/idless
        # window makes the server send an error that can retire us.
        if not cid or str(cid).startswith("SUPPRESSED"):
            continue
        ri = c.get("roundIndex")
        if not isinstance(ri, int) or ri < 1:
            continue
        if c.get("resolved"):
            continue
        if player_id not in (c.get("redPlayerId"), c.get("bluePlayerId")):
            continue
        deadline = c.get("deadlineRound")
        if round_no is not None and deadline is not None and round_no > deadline:
            continue  # window already ended
        mine.append(c)
    if not mine:
        return None
    mine.sort(key=lambda c: CONTEST_PRIORITY.get(c.get("contestType"), 10), reverse=True)
    return mine[0]


def pick_card(me: dict[str, Any], contest: dict[str, Any]) -> str:
    """Best affordable card that we're willing to spend on this window."""
    res = me.get("resources", {}) or {}
    buffs = {b.get("type") for b in me.get("buffs", [])}

    if me.get("goodFruit", 0) > 0:
        return "XIAN_GONG"
    if me.get("guardActionPoint", 0) > 0:
        return "BING_ZHENG"
    if res.get("PASS_TOKEN", 0) > 0 or res.get("OFFICIAL_PERMIT", 0) > 0:
        return "YAN_DIE"
    if buffs & HORSE_BUFFS or res.get("FAST_HORSE", 0) > 0 or res.get("SHORT_HORSE", 0) > 0:
        return "QIANG_XING"
    return "ABSTAIN"
