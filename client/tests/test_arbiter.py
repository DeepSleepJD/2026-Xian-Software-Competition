"""arbiter 仲裁单测：动作类别同帧上限（协议第 8 章）+ 优先级竞争。"""

import unittest

from lychee.arbiter import merge_intents
from lychee.strategy import Intent


def move(target: str) -> dict:
    return {"action": "MOVE", "targetNodeId": target}


class ArbiterTests(unittest.TestCase):
    def test_priority_wins_main_conflict(self) -> None:
        intents = [
            Intent(kind="economy", priority=10, actions=[move("S03")]),
            Intent(kind="delivery", priority=50, actions=[move("S02")]),
        ]
        actions = merge_intents(intents)
        self.assertEqual([move("S02")], actions)

    def test_categories_do_not_conflict(self) -> None:
        intents = [
            Intent(kind="delivery", priority=50, actions=[move("S02")]),
            Intent(kind="combat", priority=40, actions=[{"action": "SQUAD_SCOUT", "targetNodeId": "S10"}]),
            Intent(kind="combat", priority=30, actions=[{"action": "RUSH_SPEED"}]),
        ]
        self.assertEqual(3, len(merge_intents(intents)))

    def test_squad_capped_at_one(self) -> None:
        intents = [
            Intent(kind="a", priority=2, actions=[{"action": "SQUAD_SCOUT", "targetNodeId": "S10"}]),
            Intent(kind="b", priority=1, actions=[{"action": "SQUAD_CLEAR", "targetNodeId": "S08"}]),
        ]
        actions = merge_intents(intents)
        self.assertEqual(1, len(actions))
        self.assertEqual("SQUAD_SCOUT", actions[0]["action"])

    def test_window_card_one_per_contest(self) -> None:
        card = lambda cid, c: {"action": "WINDOW_CARD", "contestId": cid, "card": c}
        intents = [
            Intent(kind="a", priority=3, actions=[card("C1", "ATTACK")]),
            Intent(kind="b", priority=2, actions=[card("C1", "DEFEND")]),  # 同窗口，丢弃
            Intent(kind="c", priority=1, actions=[card("C2", "ABSTAIN")]),  # 不同窗口，放行
        ]
        actions = merge_intents(intents)
        self.assertEqual(2, len(actions))
        self.assertEqual({"C1", "C2"}, {a["contestId"] for a in actions})
        self.assertEqual("ATTACK", actions[0]["card"])

    def test_empty_intents_yield_heartbeat(self) -> None:
        self.assertEqual([], merge_intents([]))


if __name__ == "__main__":
    unittest.main()
