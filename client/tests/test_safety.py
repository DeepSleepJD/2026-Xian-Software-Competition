"""safety 单测：「送达优先」硬约束的到终点帧数与触发边界。

地图：A —(ROAD d=2, 3帧)— B —(ROAD d=2, 3帧)— C(终点)，无处理节点，
A 到终点 = 6 帧整，边界数字可手算。
"""

import unittest

from lychee.state import GameState
from lychee.strategy import safety

MY_ID = 1001

START = {
    "matchId": "safety-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "STATION"},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "A", "terminalNodeIds": ["C"]}}},
}


def inquire(round_no: int, *, node: str = "A", state: str = "IDLE",
            next_node: str = "", move_dir: str = "",
            progress_ms: int = 0, total_ms: int = 0) -> dict:
    return {
        "round": round_no,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "moveDirection": move_dir,
                     "edgeProgressMs": progress_ms, "edgeTotalMs": total_ms}],
    }


OPP_ID = 2002

TRAP_START = {
    "matchId": "trap-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "STATION"},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "A", "terminalNodeIds": ["C"]}}},
}

# B 有旁路（A—D—C）→ 不是咽喉
BYPASS_START = {
    **TRAP_START,
    "matchId": "bypass-test",
    "nodes": TRAP_START["nodes"] + [{"nodeId": "D", "nodeType": "STATION"}],
    "edges": TRAP_START["edges"] + [
        {"edgeId": "E3", "fromNodeId": "A", "toNodeId": "D",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E4", "fromNodeId": "D", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
}

# A→B 是长边，用来复刻“对手正在同一咽喉边上领先，先到后还能设卡”的现网形态。
LONG_TRAP_START = {
    **TRAP_START,
    "matchId": "long-trap-test",
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
}


def trap_inquire(round_no: int, *, me_node: str = "A", squads: int = 0,
                 opp_node: str = "B", opp_next: str = "", opp_ap: int = 4,
                 opp_delivered: bool = False, nodes: list | None = None,
                 opp_state: str = "IDLE", opp_progress_ms: int = 0,
                 opp_total_ms: int = 0) -> dict:
    return {
        "round": round_no,
        "players": [
            {"playerId": MY_ID, "teamId": "RED", "state": "IDLE",
             "currentNodeId": me_node, "nextNodeId": "",
             "squadAvailable": squads},
            {"playerId": OPP_ID, "teamId": "BLUE", "state": opp_state,
             "currentNodeId": opp_node, "nextNodeId": opp_next,
             "edgeProgressMs": opp_progress_ms, "edgeTotalMs": opp_total_ms,
             "guardActionPoint": opp_ap, "delivered": opp_delivered},
        ],
        "nodes": nodes or [],
    }


def enemy_guard(node_id: str, defense: int = 6) -> list[dict]:
    return [{"nodeId": node_id,
             "guard": {"active": True, "ownerTeamId": "BLUE", "defense": defense,
                       "initialDefense": defense, "maxDefense": 7}}]


def seen_enemy_guard(node_id: str = "C") -> list[dict]:
    return [{"nodeId": node_id,
             "guard": {"active": False, "ownerTeamId": "BLUE", "defense": 0,
                       "initialDefense": 4, "maxDefense": 6}}]


class TrapGateTests(unittest.TestCase):
    """防陷阱闸门（P4e）：现网 match_2751 r361 败因场景的最小复刻。

    对手停在咽喉 B 上握着 guardAP，我方 0 小分队——上边后它设卡即 180 帧冻结
    （半路禁折返/攻坚需停稳），必须在边外等它走人。
    """

    def load(self, start: dict, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(start)
        state.update_inquire(inq)
        return state

    def test_holds_when_opponent_squats_choke_with_guard_points(self) -> None:
        state = self.load(TRAP_START, trap_inquire(100, nodes=seen_enemy_guard()))
        self.assertTrue(safety.hold_before_choke(state, "B"))

    def test_no_hold_before_any_enemy_guard_seen(self) -> None:
        state = self.load(TRAP_START, trap_inquire(100))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_opponent_ever_set_guard_accessor_keeps_memory(self) -> None:
        state = self.load(TRAP_START, trap_inquire(100))
        self.assertFalse(safety.opponent_ever_set_guard(state))
        state.update_inquire(trap_inquire(101, nodes=seen_enemy_guard()))
        self.assertTrue(safety.opponent_ever_set_guard(state))
        state.update_inquire(trap_inquire(102))
        self.assertTrue(safety.opponent_ever_set_guard(state))

    def test_no_hold_without_opponent_guard_points(self) -> None:
        state = self.load(TRAP_START, trap_inquire(100, opp_ap=0, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_no_hold_when_opponent_already_en_route(self) -> None:
        # 对手已上边离站（半路）：设卡窗口已过，亮没亮卡都不该再蹲
        state = self.load(TRAP_START, trap_inquire(100, opp_next="C", nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_holds_when_opponent_will_reach_choke_first(self) -> None:
        # P4f：对手虽还没停在 B，但正驶向 B 且能先到+完成 4 帧设卡；
        # 此时我方进边会在半路撞卡，必须等在 A，亮卡后停稳攻坚。
        state = self.load(LONG_TRAP_START, trap_inquire(
            100, opp_node="A", opp_next="B", opp_state="MOVING",
            opp_progress_ms=4000, opp_total_ms=8000, nodes=seen_enemy_guard()))
        self.assertTrue(safety.hold_before_choke(state, "B"))

    def test_no_hold_when_opponent_cannot_finish_guard_before_us(self) -> None:
        # 对手也在去 B，但剩余到站+设卡读条晚于我方到站，继续走不会半路冻住。
        state = self.load(LONG_TRAP_START, trap_inquire(
            100, opp_node="A", opp_next="B", opp_state="MOVING",
            opp_progress_ms=0, opp_total_ms=15000, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_no_hold_when_guard_already_visible(self) -> None:
        # 已亮卡：停稳攻坚链接管（BREAK_GUARD 当帧结算），蹲着白等
        state = self.load(TRAP_START, trap_inquire(100, nodes=enemy_guard("B")))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_no_hold_with_enough_squads_to_weaken_through(self) -> None:
        # STATION 最大防御 6 → 6 支小分队可半路削穿，进边风险可控
        state = self.load(TRAP_START, trap_inquire(100, squads=6, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))
        state = self.load(TRAP_START, trap_inquire(100, squads=5, nodes=seen_enemy_guard()))
        self.assertTrue(safety.hold_before_choke(state, "B"))

    def test_no_hold_when_must_rush(self) -> None:
        # 时间账吃紧：接受风化风险也要走，保底交付
        state = self.load(TRAP_START, trap_inquire(590, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_no_hold_on_non_choke_node(self) -> None:
        # B 有旁路 → 对手不值得在此设卡，跟停会在它每个处理站后面白等
        state = self.load(BYPASS_START, trap_inquire(100, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_no_hold_when_opponent_delivered(self) -> None:
        state = self.load(TRAP_START, trap_inquire(100, opp_delivered=True, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_hold_cap_releases_after_twelve_frames(self) -> None:
        state = GameState(MY_ID)
        state.update_start(TRAP_START)
        for round_no in range(100, 112):
            state.update_inquire(trap_inquire(round_no, nodes=seen_enemy_guard()))
            self.assertTrue(safety.hold_before_choke(state, "B"))
        state.update_inquire(trap_inquire(112, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))


class AheadOfOpponentTests(unittest.TestCase):
    def load(self, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(TRAP_START)
        state.update_inquire(inq)
        return state

    def test_behind_when_opponent_closer_to_terminal(self) -> None:
        state = self.load(trap_inquire(100, me_node="A", opp_node="B"))
        self.assertFalse(safety.ahead_of_opponent(state))

    def test_ahead_when_closer_than_opponent(self) -> None:
        state = self.load(trap_inquire(100, me_node="B", opp_node="A"))
        self.assertTrue(safety.ahead_of_opponent(state))

    def test_ahead_when_opponent_delivered(self) -> None:
        # 无在场对手 = 竞速压力不存在，蹲守只受时间账约束
        state = self.load(trap_inquire(100, me_node="A", opp_node="B",
                                       opp_delivered=True))
        self.assertTrue(safety.ahead_of_opponent(state))


class SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)

    def load(self, inq: dict) -> GameState:
        self.state.update_inquire(inq)
        return self.state

    def test_frames_to_terminal_docked(self) -> None:
        state = self.load(inquire(10, node="A"))
        self.assertEqual(6, safety.frames_to_terminal(state))

    def test_frames_to_terminal_mid_edge(self) -> None:
        # A→B 边走掉 760/2760ms：剩 2000ms = 2 帧，再加 B→C 3 帧
        state = self.load(inquire(10, node="A", state="MOVING", next_node="B",
                                  progress_ms=760, total_ms=2760))
        self.assertEqual(5, safety.frames_to_terminal(state))

    def test_frames_to_terminal_paused_mid_edge(self) -> None:
        # 被守卫暂停（WAITING+PAUSED）与移动中同账：从 next_node_id 起算
        state = self.load(inquire(10, node="A", state="WAITING", next_node="B",
                                  move_dir="PAUSED", progress_ms=760, total_ms=2760))
        self.assertEqual(5, safety.frames_to_terminal(state))

    def test_must_rush_boundary(self) -> None:
        # A 到终点 6 帧 + 余量 60：533+6+60=599 < 600 不触发，534 起触发
        self.assertFalse(safety.must_rush(self.load(inquire(533, node="A"))))
        self.assertTrue(safety.must_rush(self.load(inquire(534, node="A"))))

    def test_must_rush_when_position_unknown(self) -> None:
        # 位置缺失/不可达 → 视同时间不够，停止一切绕路
        self.assertTrue(safety.must_rush(self.load(inquire(10, node=""))))


if __name__ == "__main__":
    unittest.main()
