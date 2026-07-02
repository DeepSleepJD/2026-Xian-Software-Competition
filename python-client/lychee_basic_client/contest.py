"""Window-card policy for the 3-tap contest windows (task book 5.4).

The card matrix is rock-paper-scissors-like:
    XIAN_GONG beats YAN_DIE, BING_ZHENG ; loses to QIANG_XING
    BING_ZHENG beats YAN_DIE, QIANG_XING ; loses to XIAN_GONG
    QIANG_XING beats XIAN_GONG           ; loses to YAN_DIE, BING_ZHENG
    YAN_DIE    beats QIANG_XING          ; loses to XIAN_GONG, BING_ZHENG

With hidden simultaneous choices there is no dominant pure play, so we use a
resource-aware heuristic: spend the cheapest card we hold (guard points are
otherwise unused, documents next), and only spend a good fruit (XIAN_GONG,
needs freshness >= 80) on a high-value window like the gate or a forced pass.
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
HIGH_VALUE = 90  # priority at/above which we'll spend a good fruit (XIAN_GONG)


def active_contest(
    player_id: int, contests: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """The most valuable unresolved window this player is a party to, or None."""
    mine = [
        c
        for c in contests
        if not c.get("resolved")
        and player_id in (c.get("redPlayerId"), c.get("bluePlayerId"))
    ]
    if not mine:
        return None
    mine.sort(key=lambda c: CONTEST_PRIORITY.get(c.get("contestType"), 10), reverse=True)
    return mine[0]


def pick_card(me: dict[str, Any], contest: dict[str, Any]) -> str:
    """Cheapest affordable card that we're willing to spend on this window."""
    res = me.get("resources", {}) or {}
    buffs = {b.get("type") for b in me.get("buffs", [])}
    priority = CONTEST_PRIORITY.get(contest.get("contestType"), 10)

    if me.get("guardActionPoint", 0) > 0:
        return "BING_ZHENG"
    if res.get("PASS_TOKEN", 0) > 0 or res.get("OFFICIAL_PERMIT", 0) > 0:
        return "YAN_DIE"
    if buffs & HORSE_BUFFS or res.get("FAST_HORSE", 0) > 0 or res.get("SHORT_HORSE", 0) > 0:
        return "QIANG_XING"
    if priority >= HIGH_VALUE and me.get("freshness", 0) >= 80 and me.get("goodFruit", 0) > 0:
        return "XIAN_GONG"
    return "ABSTAIN"
