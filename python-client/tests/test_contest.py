import unittest

from lychee_basic_client.contest import active_contest, pick_card


def _contest(ctype, cid="C1", red=1001, blue=2002, resolved=False):
    return {
        "contestId": cid,
        "contestType": ctype,
        "redPlayerId": red,
        "bluePlayerId": blue,
        "resolved": resolved,
    }


class ContestTests(unittest.TestCase):
    def test_active_contest_picks_highest_value_unresolved(self) -> None:
        contests = [
            _contest("RESOURCE", cid="c_res"),
            _contest("GATE", cid="c_gate"),
            _contest("TASK", cid="c_task", resolved=True),  # ignored: resolved
        ]
        c = active_contest(1001, contests)
        self.assertEqual("c_gate", c["contestId"])

    def test_active_contest_none_when_not_party(self) -> None:
        contests = [_contest("GATE", red=3003, blue=4004)]
        self.assertIsNone(active_contest(1001, contests))

    def test_pick_card_spends_guard_point_first(self) -> None:
        me = {"guardActionPoint": 2, "resources": {"PASS_TOKEN": 1}}
        self.assertEqual("BING_ZHENG", pick_card(me, _contest("TASK")))

    def test_pick_card_uses_document_then_horse(self) -> None:
        me = {"guardActionPoint": 0, "resources": {"OFFICIAL_PERMIT": 1}}
        self.assertEqual("YAN_DIE", pick_card(me, _contest("TASK")))
        me2 = {"guardActionPoint": 0, "resources": {"SHORT_HORSE": 1}}
        self.assertEqual("QIANG_XING", pick_card(me2, _contest("TASK")))

    def test_pick_card_saves_good_fruit_for_high_value_only(self) -> None:
        # only a good fruit available: spend it on GATE, not on a mere RESOURCE
        me = {"guardActionPoint": 0, "resources": {}, "freshness": 95, "goodFruit": 50}
        self.assertEqual("XIAN_GONG", pick_card(me, _contest("GATE")))
        self.assertEqual("ABSTAIN", pick_card(me, _contest("RESOURCE")))

    def test_pick_card_abstains_when_nothing_affordable(self) -> None:
        me = {"guardActionPoint": 0, "resources": {}, "freshness": 40, "goodFruit": 0}
        self.assertEqual("ABSTAIN", pick_card(me, _contest("GATE")))


if __name__ == "__main__":
    unittest.main()
