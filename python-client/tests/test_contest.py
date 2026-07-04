import unittest

from lychee_basic_client.contest import active_contest, pick_card


def _contest(ctype, cid="C1", red=1001, blue=2002, resolved=False, round_index=1):
    return {
        "contestId": cid,
        "contestType": ctype,
        "redPlayerId": red,
        "bluePlayerId": blue,
        "resolved": resolved,
        "roundIndex": round_index,
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

    def test_active_contest_skips_suppressed_and_idless_windows(self) -> None:
        # a suppressed / id-less pseudo-contest must never be carded (server error)
        supp = _contest("DOCK", cid="SUPPRESSED:DOCK:S02"); supp["roundIndex"] = None
        idless = _contest("DOCK", cid=None); idless["roundIndex"] = None
        self.assertIsNone(active_contest(1001, [supp, idless], round_no=54))
        # a real window with a valid id and an active tap IS returned
        real = _contest("GATE", cid="C_1"); real["roundIndex"] = 1
        self.assertEqual("C_1", active_contest(1001, [real], round_no=54)["contestId"])

    def test_active_contest_excludes_ended_window_past_deadline(self) -> None:
        c = _contest("TASK")
        c["deadlineRound"] = 120
        # within deadline -> playable; past deadline -> excluded (would server-error)
        self.assertIsNotNone(active_contest(1001, [c], round_no=118))
        self.assertIsNone(active_contest(1001, [c], round_no=121))

    def test_pick_card_spends_xian_gong_when_affordable(self) -> None:
        me = {"guardActionPoint": 2, "resources": {"PASS_TOKEN": 1},
              "freshness": 95, "goodFruit": 20}
        self.assertEqual("XIAN_GONG", pick_card(me, _contest("TASK")))

    def test_pick_card_does_not_use_xian_gong_below_freshness_floor(self) -> None:
        me = {"guardActionPoint": 2, "resources": {"PASS_TOKEN": 1},
              "freshness": 79, "goodFruit": 20}
        self.assertEqual("BING_ZHENG", pick_card(me, _contest("TASK")))

    def test_pick_card_falls_back_to_guard_point_when_good_fruit_is_gone(self) -> None:
        me = {"guardActionPoint": 2, "resources": {"PASS_TOKEN": 1},
              "freshness": 95, "goodFruit": 0}
        self.assertEqual("BING_ZHENG", pick_card(me, _contest("TASK")))

    def test_pick_card_uses_document_then_horse(self) -> None:
        me = {"guardActionPoint": 0, "resources": {"OFFICIAL_PERMIT": 1},
              "freshness": 40, "goodFruit": 0}
        self.assertEqual("YAN_DIE", pick_card(me, _contest("TASK")))
        me2 = {"guardActionPoint": 0, "resources": {"SHORT_HORSE": 1},
               "freshness": 40, "goodFruit": 0}
        self.assertEqual("QIANG_XING", pick_card(me2, _contest("TASK")))

    def test_pick_card_spends_good_fruit_on_low_value_windows_too(self) -> None:
        me = {"guardActionPoint": 0, "resources": {}, "freshness": 95, "goodFruit": 50}
        self.assertEqual("XIAN_GONG", pick_card(me, _contest("GATE")))
        self.assertEqual("XIAN_GONG", pick_card(me, _contest("RESOURCE")))

    def test_pick_card_abstains_when_nothing_affordable(self) -> None:
        me = {"guardActionPoint": 0, "resources": {}, "freshness": 40, "goodFruit": 0}
        self.assertEqual("ABSTAIN", pick_card(me, _contest("GATE")))


if __name__ == "__main__":
    unittest.main()
