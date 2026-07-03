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

    def test_holds_even_before_any_enemy_guard_seen(self) -> None:
        # P4m：13:22 现网局对手全场第一张卡就是杀招——"见过卡才防"先验已删
        state = self.load(TRAP_START, trap_inquire(100))
        self.assertTrue(safety.hold_before_choke(state, "B"))

    def test_holds_regardless_of_guard_action_points(self) -> None:
        # P4m 勘误：guardActionPoint 是兵争牌货币（任务书 3.3.5），与设卡无关；
        # GAP=0 的对手好果充足照样能关门
        state = self.load(TRAP_START, trap_inquire(100, opp_ap=0, nodes=seen_enemy_guard()))
        self.assertTrue(safety.hold_before_choke(state, "B"))

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

    def test_holds_even_with_full_squads(self) -> None:
        # P4m：削卡消耗战对会增援的对手必败（同帧序增援先落地，13:22 局实证
        # 削卡反把卡续长 60 帧）——"够兵可削穿"是伪安全放行，已删
        state = self.load(TRAP_START, trap_inquire(100, squads=8, nodes=seen_enemy_guard()))
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

    def test_no_hold_when_opponent_beyond_choke(self) -> None:
        # 对手在 B 之外的 C（未朝 B 走）：不算威胁——全路径回身 ETA 扩面已论证否决
        # （会对"跟在领先对手身后"连环 hold），预算制释放兜住尾部风险
        state = self.load(LONG_TRAP_START, trap_inquire(100, opp_node="C"))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_hold_time_budget(self) -> None:
        # P4m：12 帧死等上限 → 时间预算制。A 到终点 6 帧，预算线 =
        # 600 - 6 - FP_TAX_RESERVE(50) - RUSH_SAFETY_MARGIN(60) = 484：
        # r483 还等得起，r484 起必须动身（真被关门还有改道+强通税已预留）
        state = self.load(TRAP_START, trap_inquire(483, nodes=seen_enemy_guard()))
        self.assertTrue(safety.hold_before_choke(state, "B"))
        state = self.load(TRAP_START, trap_inquire(484, nodes=seen_enemy_guard()))
        self.assertFalse(safety.hold_before_choke(state, "B"))

    def test_hold_persists_beyond_twelve_frames_within_budget(self) -> None:
        # 13:22 局需要连续等 62 帧（对手 r291 到站、r317 才离开）——旧 12 帧上限杯水车薪
        state = GameState(MY_ID)
        state.update_start(TRAP_START)
        for round_no in range(100, 170):
            state.update_inquire(trap_inquire(round_no, nodes=seen_enemy_guard()))
            self.assertTrue(safety.hold_before_choke(state, "B"))


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
        # 无在场对手 = 竞速压力不存在，行为只受时间账约束
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


# 拦截层死线测试地图：A —(ROAD d=2, 3帧)— B(KEY_PASS, 咽喉) — C(终点)
DEADLINE_START = {
    "matchId": "deadline-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "KEY_PASS"},
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


def deadline_inquire(round_no: int, *, me_node: str = "A", me_good: int = 50,
                     me_fresh: float = 90.0, opp_node: str = "A",
                     opp_delivered: bool = False, opp_retired: bool = False,
                     opp_present: bool = True, opp_buffs: list | None = None,
                     opp_resources: dict | None = None,
                     nodes: list | None = None) -> dict:
    players = [{"playerId": MY_ID, "teamId": "RED", "state": "IDLE",
                "currentNodeId": me_node, "goodFruit": me_good, "freshness": me_fresh}]
    if opp_present:
        players.append({"playerId": OPP_ID, "teamId": "BLUE", "state": "IDLE",
                        "currentNodeId": opp_node, "freshness": 90.0,
                        "delivered": opp_delivered, "retired": opp_retired,
                        "buffs": opp_buffs or [], "resources": opp_resources or {}})
    return {"round": round_no, "players": players, "nodes": nodes or []}


def my_guard(node_id: str, defense: int = 6) -> list[dict]:
    return [{"nodeId": node_id,
             "guard": {"active": True, "ownerTeamId": "RED", "defense": defense,
                       "initialDefense": defense, "maxDefense": 7}}]


class OpponentCannotFinishTests(unittest.TestCase):
    def load(self, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(DEADLINE_START)
        state.update_inquire(inq)
        return state

    def test_healthy_opponent_can_finish(self) -> None:
        self.assertFalse(safety.opponent_cannot_finish(self.load(deadline_inquire(100))))

    def test_near_deadline_opponent_cannot_finish(self) -> None:
        # A→C 干净行程 6 帧 + 余量 20 = 26；round 595 → 595+26 > 600
        self.assertTrue(safety.opponent_cannot_finish(self.load(deadline_inquire(595))))

    def test_delivered_opponent_is_not_cannot_finish(self) -> None:
        self.assertFalse(safety.opponent_cannot_finish(
            self.load(deadline_inquire(100, opp_node="C", opp_delivered=True))))

    def test_retired_opponent_cannot_finish(self) -> None:
        self.assertTrue(safety.opponent_cannot_finish(
            self.load(deadline_inquire(100, opp_retired=True))))

    def test_absent_opponent_cannot_finish(self) -> None:
        self.assertTrue(safety.opponent_cannot_finish(
            self.load(deadline_inquire(100, opp_present=False))))

    def test_my_guard_tax_pushes_opponent_over_deadline(self) -> None:
        # round 560：无卡 560+6+20=586<600 能完赛；我方在咽喉 B 满防卡 tax=min(50,15+30)=45
        # → 560+6+45+20=631>600 判死
        base = self.load(deadline_inquire(560))
        self.assertFalse(safety.opponent_cannot_finish(base))
        taxed = self.load(deadline_inquire(560, nodes=my_guard("B", 6)))
        self.assertTrue(safety.opponent_cannot_finish(taxed))


class OppMovePerFrameTests(unittest.TestCase):
    def load(self, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(DEADLINE_START)
        state.update_inquire(inq)
        return state

    def test_base_speed_without_buffs(self) -> None:
        self.assertEqual(1000, safety.opp_move_per_frame(self.load(deadline_inquire(100))))

    def test_fast_horse_buff(self) -> None:
        state = self.load(deadline_inquire(
            100, opp_buffs=[{"type": "FAST_HORSE", "remainingRound": 5}]))
        self.assertEqual(1200, safety.opp_move_per_frame(state))

    def test_held_short_horse_resource(self) -> None:
        state = self.load(deadline_inquire(100, opp_resources={"SHORT_HORSE": 1}))
        self.assertEqual(1150, safety.opp_move_per_frame(state))

    def test_rush_buff(self) -> None:
        state = self.load(deadline_inquire(
            100, opp_buffs=[{"type": "RUSH_SPEED", "remainingRound": 5}]))
        self.assertEqual(1300, safety.opp_move_per_frame(state))


class FreshnessDeadlineTests(unittest.TestCase):
    def load(self, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(DEADLINE_START)
        state.update_inquire(inq)
        return state

    def test_healthy_no_deadline(self) -> None:
        state = self.load(deadline_inquire(100, me_good=50, me_fresh=90.0))
        self.assertFalse(safety.freshness_deadline_hit(state))

    def test_low_good_hits_deadline(self) -> None:
        state = self.load(deadline_inquire(100, me_good=1, me_fresh=90.0))
        self.assertTrue(safety.freshness_deadline_hit(state))

    def test_low_freshness_hits_deadline(self) -> None:
        state = self.load(deadline_inquire(100, me_good=50, me_fresh=3.0))
        self.assertTrue(safety.freshness_deadline_hit(state))

    def test_delivery_deadline_combines_rush_and_freshness(self) -> None:
        # 健康 + 时间充裕 → 不触发
        self.assertFalse(safety.delivery_deadline_hit(
            self.load(deadline_inquire(100, me_good=50, me_fresh=90.0))))
        # must_rush 触发（round 595）
        self.assertTrue(safety.delivery_deadline_hit(
            self.load(deadline_inquire(595, me_good=50, me_fresh=90.0))))
        # 鲜度线触发（好果 1）
        self.assertTrue(safety.delivery_deadline_hit(
            self.load(deadline_inquire(100, me_good=1, me_fresh=90.0))))


# 拦截控制器测试图：A —(ROAD d=10, 14帧)— B(KEY_PASS 咽喉) — C(终点)
# 进入 B 的边够长（14>GUARD_SETUP 4），可表达"我先到咽喉+对手上边冻结窗口"
INTERCEPT_START = {
    "matchId": "intercept-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "KEY_PASS"},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"startNodeId": "A", "terminalNodeIds": ["C"]}}},
}

# B 有旁路 A—D—C → 不是咽喉
INTERCEPT_BYPASS = {
    **INTERCEPT_START,
    "matchId": "intercept-bypass",
    "nodes": INTERCEPT_START["nodes"] + [{"nodeId": "D", "nodeType": "STATION"}],
    "edges": INTERCEPT_START["edges"] + [
        {"edgeId": "E3", "fromNodeId": "A", "toNodeId": "D",
         "routeType": "ROAD", "distance": 10, "bidirectional": True},
        {"edgeId": "E4", "fromNodeId": "D", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
}


def intercept_inquire(round_no: int = 200, *, me_node: str = "A", me_next: str = "",
                      opp_node: str = "A", opp_next: str = "", opp_state: str = "IDLE",
                      opp_progress_ms: int = 0, opp_total_ms: int = 0,
                      me_buffs: list | None = None, opp_resources: dict | None = None,
                      nodes: list | None = None) -> dict:
    return {
        "round": round_no,
        "players": [
            {"playerId": MY_ID, "teamId": "RED", "state": "IDLE",
             "currentNodeId": me_node, "nextNodeId": me_next, "goodFruit": 50,
             "freshness": 90.0, "buffs": me_buffs or []},
            {"playerId": OPP_ID, "teamId": "BLUE", "state": opp_state,
             "currentNodeId": opp_node, "nextNodeId": opp_next,
             "edgeProgressMs": opp_progress_ms, "edgeTotalMs": opp_total_ms,
             "resources": opp_resources or {}},
        ],
        "nodes": nodes or [],
    }


def friendly_guard_node(node_id: str, defense: int = 6) -> list[dict]:
    return [{"nodeId": node_id,
             "guard": {"active": True, "ownerTeamId": "RED", "defense": defense,
                       "initialDefense": defense, "maxDefense": 7}}]


class EtaTests(unittest.TestCase):
    def load(self, start: dict, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(start)
        state.update_inquire(inq)
        return state

    def test_me_eta_pure_frames(self) -> None:
        state = self.load(INTERCEPT_START, intercept_inquire(me_node="A"))
        self.assertEqual(14, safety.me_eta(state, "B"))     # A→B = 14 帧
        self.assertEqual(17, safety.me_eta(state, "C"))     # +B→C 3 帧

    def test_opp_eta_faster_with_horse(self) -> None:
        base = self.load(INTERCEPT_START, intercept_inquire(opp_node="A"))
        horsed = self.load(INTERCEPT_START,
                           intercept_inquire(opp_node="A", opp_resources={"FAST_HORSE": 1}))
        self.assertLess(safety.opp_eta(horsed, "B"), safety.opp_eta(base, "B"))


class InterceptionNodeTests(unittest.TestCase):
    def load(self, start: dict, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(start)
        state.update_inquire(inq)
        return state

    def test_ahead_returns_opponent_choke(self) -> None:
        # 我在咽喉 B、对手在 A：me_eta(B)=0 +4 ≤ opp_eta(B)=14 → 拦截点 B
        state = self.load(INTERCEPT_START, intercept_inquire(me_node="B", opp_node="A"))
        self.assertEqual("B", safety.interception_node(state))

    def test_behind_returns_none(self) -> None:
        # 我在 A、对手在 B：我到 B 反而更晚 → 无拦截点
        state = self.load(INTERCEPT_START, intercept_inquire(me_node="A", opp_node="B"))
        self.assertIsNone(safety.interception_node(state))

    def test_no_choke_returns_none(self) -> None:
        state = self.load(INTERCEPT_BYPASS, intercept_inquire(me_node="B", opp_node="A"))
        self.assertIsNone(safety.interception_node(state))

    def test_already_blocking_returns_none(self) -> None:
        # 对手前方已有我方有效卡 → 一张卡已冻死他，别再滚动 camp
        state = self.load(INTERCEPT_START, intercept_inquire(
            me_node="B", opp_node="A", nodes=friendly_guard_node("B")))
        self.assertIsNone(safety.interception_node(state))

    def test_opponent_absent_returns_none(self) -> None:
        inq = intercept_inquire(me_node="B", opp_node="A")
        inq["players"] = inq["players"][:1]
        state = self.load(INTERCEPT_START, inq)
        self.assertIsNone(safety.interception_node(state))


class FreezeWindowTests(unittest.TestCase):
    def load(self, inq: dict) -> GameState:
        state = GameState(MY_ID)
        state.update_start(INTERCEPT_START)
        state.update_inquire(inq)
        return state

    def test_open_when_committed_with_margin(self) -> None:
        # 对手 MOVING A→B，剩余 10000ms=10 帧 ≥ 6 → 窗口开
        state = self.load(intercept_inquire(
            opp_node="A", opp_next="B", opp_state="MOVING",
            opp_progress_ms=4000, opp_total_ms=14000))
        self.assertTrue(safety.freeze_window_open(state, "B"))

    def test_closed_when_not_committed(self) -> None:
        # 对手停在 A（未上边）→ 窗口关，早设会被强通
        state = self.load(intercept_inquire(opp_node="A"))
        self.assertFalse(safety.freeze_window_open(state, "B"))

    def test_closed_when_window_too_narrow(self) -> None:
        # 剩余 4000ms=4 帧 < 6 → 到站前设不完
        state = self.load(intercept_inquire(
            opp_node="A", opp_next="B", opp_state="MOVING",
            opp_progress_ms=10000, opp_total_ms=14000))
        self.assertFalse(safety.freeze_window_open(state, "B"))


KEYPASS_START = {
    **TRAP_START,
    "matchId": "weathering-test",
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "KEY_PASS"},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True},
    ],
}


def guard_obj(defense: int, initial: int, age: int):
    state = GameState(MY_ID)
    state.update_start(KEYPASS_START)
    state.update_inquire({
        "round": 100,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": "IDLE",
                     "currentNodeId": "A"}],
        "nodes": [{"nodeId": "B",
                   "guard": {"active": True, "ownerTeamId": "BLUE",
                             "defense": defense, "initialDefense": initial,
                             "maxDefense": 7, "ageRound": age}}],
    })
    return state, state.enemy_guard_at("B")


class GuardWeatheringRemainingTests(unittest.TestCase):
    """任务书 924-936：KEY_PASS 且设卡防值 ≥4 首损 45 帧，否则 30；之后每 30 帧 -1。"""

    def test_fresh_keypass_full_defense(self) -> None:
        state, guard = guard_obj(defense=4, initial=4, age=0)
        # 首损还差 45，之后 3 次 × 30
        self.assertEqual(safety.guard_weathering_remaining(state, "B", guard), 45 + 90)

    def test_keypass_low_initial_uses_30(self) -> None:
        state, guard = guard_obj(defense=2, initial=2, age=10)
        # 初始防 <4 → 首损 30；age 10 → 还差 20；再 1 次 × 30
        self.assertEqual(safety.guard_weathering_remaining(state, "B", guard), 20 + 30)

    def test_after_first_decay_cycles_of_30(self) -> None:
        state, guard = guard_obj(defense=5, initial=6, age=70)
        # 首损 45 已过，(70-45)%30=25 → 下次风化差 5；再 4 次 × 30
        self.assertEqual(safety.guard_weathering_remaining(state, "B", guard), 5 + 120)

    def test_zero_defense_is_zero(self) -> None:
        state, guard = guard_obj(defense=1, initial=4, age=0)
        guard.defense = 0
        self.assertEqual(safety.guard_weathering_remaining(state, "B", guard), 0)


if __name__ == "__main__":
    unittest.main()
