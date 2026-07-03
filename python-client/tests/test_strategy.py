import unittest

from lychee_basic_client.strategy import Strategy, TOTAL_ROUNDS


def _line_strategy(gate="S05"):
    # S01 - S02 - S03 - S04 - S05 (a single funnel: every inner node is a choke)
    s = Strategy(1001)
    s.graph.load_edges([
        {"fromNodeId": a, "toNodeId": b, "routeType": "ROAD", "distance": 10,
         "bidirectional": True}
        for a, b in [("S01", "S02"), ("S02", "S03"), ("S03", "S04"), ("S04", "S05")]
    ])
    s.start_node, s.gate_node, s.terminal_node = "S01", gate, "S05"
    s.chokes = s.graph.choke_points("S01", gate)
    s._my_team = "RED"
    return s


def _me(node, **kw):
    d = {"playerId": 1001, "teamId": "RED", "currentNodeId": node, "state": "IDLE",
         "nextNodeId": None, "routeEdgeId": None, "resources": {}, "goodFruit": 20,
         "freshness": 90.0, "verified": False, "delivered": False, "retired": False}
    d.update(kw)
    return d


def _opp(node, **kw):
    d = {"playerId": 2002, "teamId": "BLUE", "currentNodeId": node, "state": "IDLE",
         "nextNodeId": None, "routeEdgeId": None}
    d.update(kw)
    return d


def _inq(round_no, me, opp, nodes=None, phase="NORMAL", tasks=None):
    ns = nodes or []
    return {"round": round_no, "phase": phase, "players": [me, opp],
            "nodes": ns, "tasks": tasks or [], "contests": [], "events": []}


class ChokeSetupTests(unittest.TestCase):
    def test_finds_chokes_on_a_funnel(self) -> None:
        s = _line_strategy(gate="S04")
        # S02, S03 are cut-vertices between S01 and S04
        self.assertIn("S02", s.chokes)
        self.assertIn("S03", s.chokes)


class BlockadeTests(unittest.TestCase):
    def test_races_to_the_choke_first(self) -> None:
        s = _line_strategy(gate="S04")  # chokes S02(near gate first?)/S03
        act = s.decide(_inq(10, _me("S01"), _opp("S01")))
        # heads deeper toward the choke, not idling
        self.assertEqual("MOVE", act[0]["action"])

    def test_guards_a_choke_it_passes_while_opponent_is_behind(self) -> None:
        s = _line_strategy(gate="S04")  # chokes S02, S03 on the line
        self.assertIn("S02", s.chokes)
        me = _me("S02", goodFruit=20)      # standing on a choke
        opp = _opp("S01")                   # opponent still behind it
        act = s.decide(_inq(50, me, opp))
        self.assertEqual("SET_GUARD", act[0]["action"])
        self.assertEqual("S02", act[0]["targetNodeId"])

    def test_does_not_guard_a_choke_opponent_already_passed(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S02", goodFruit=20)
        opp = _opp("S03")  # opponent already past S02 -> guarding it is pointless
        act = s.decide(_inq(50, me, opp))
        self.assertNotEqual("SET_GUARD", act[0]["action"])

    def test_must_deliver_overrides_blocking_near_deadline(self) -> None:
        s = _line_strategy(gate="S04")
        # very late: no time left to keep blocking -> must move toward the gate
        act = s.decide(_inq(TOTAL_ROUNDS - 5, _me("S01"), _opp("S01")))
        self.assertEqual("MOVE", act[0]["action"])

    def test_delivers_when_verified_at_terminal(self) -> None:
        s = _line_strategy(gate="S04")
        me = _me("S05", verified=True, currentNodeId="S05")
        act = s.decide(_inq(300, me, _opp("S01")))
        self.assertEqual("DELIVER", act[0]["action"])


if __name__ == "__main__":
    unittest.main()
