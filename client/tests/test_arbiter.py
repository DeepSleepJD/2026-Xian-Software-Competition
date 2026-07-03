"""arbiter 仲裁单测：动作类别同帧上限（协议第 8 章）+ 优先级竞争。"""

import unittest

from lychee.arbiter import merge_intents
from lychee.state import PlayerState
from lychee.strategy import Intent


def move(target: str) -> dict:
    return {"action": "MOVE", "targetNodeId": target}


def moving_me(state: str = "MOVING", next_node: str = "S02") -> PlayerState:
    return PlayerState(player_id=1001, state=state, current_node_id="S01",
                       next_node_id=next_node)


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

    def test_window_card_capped_at_one_per_frame(self) -> None:
        card = lambda cid, c: {"action": "WINDOW_CARD", "contestId": cid, "card": c}
        intents = [
            Intent(kind="a", priority=3, actions=[card("C1", "ATTACK")]),
            Intent(kind="b", priority=2, actions=[card("C1", "DEFEND")]),  # 同窗口，丢弃
            Intent(kind="c", priority=1, actions=[card("C2", "ABSTAIN")]),  # 同帧窗口额度已占，丢弃
        ]
        actions = merge_intents(intents)
        self.assertEqual(1, len(actions))
        self.assertEqual("C1", actions[0]["contestId"])
        self.assertEqual("ATTACK", actions[0]["card"])

    def test_empty_intents_yield_heartbeat(self) -> None:
        self.assertEqual([], merge_intents([]))


class EscortMoveTests(unittest.TestCase):
    """半路派小分队捆绑 MOVE（未文档化暂停行为的规避，见 arbiter._escort_move）。"""

    SQUAD = {"action": "SQUAD_SCOUT", "targetNodeId": "S07"}

    def test_squad_mid_edge_gets_escort_move_first(self) -> None:
        actions = merge_intents([Intent(kind="c", priority=1, actions=[dict(self.SQUAD)])],
                                me=moving_me())
        self.assertEqual([move("S02"), self.SQUAD], actions)

    def test_squad_at_node_unchanged(self) -> None:
        me = moving_me(state="IDLE", next_node="")
        actions = merge_intents([Intent(kind="c", priority=1, actions=[dict(self.SQUAD)])], me=me)
        self.assertEqual([self.SQUAD], actions)

    def test_squad_while_guard_paused_unchanged(self) -> None:
        # 守卡拦停：state=WAITING + nextNodeId 保留，此时 MOVE 会被拒，不护航
        me = moving_me(state="WAITING")
        actions = merge_intents([Intent(kind="c", priority=1, actions=[dict(self.SQUAD)])], me=me)
        self.assertEqual([self.SQUAD], actions)

    def test_existing_main_action_blocks_escort(self) -> None:
        # 主车队类别已占（同帧限 1）：不能再塞 MOVE，宁可吃 1 帧暂停也不非法冲突
        intents = [
            Intent(kind="a", priority=2, actions=[{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}]),
            Intent(kind="c", priority=1, actions=[dict(self.SQUAD)]),
        ]
        actions = merge_intents(intents, me=moving_me())
        self.assertEqual(2, len(actions))
        self.assertNotIn("MOVE", [a["action"] for a in actions])

    def test_no_squad_no_escort_heartbeat_kept(self) -> None:
        # 无小分队动作的空帧维持空心跳，不学对手每帧重发 MOVE
        self.assertEqual([], merge_intents([], me=moving_me()))

    def test_no_me_backward_compatible(self) -> None:
        actions = merge_intents([Intent(kind="c", priority=1, actions=[dict(self.SQUAD)])])
        self.assertEqual([self.SQUAD], actions)


if __name__ == "__main__":
    unittest.main()
