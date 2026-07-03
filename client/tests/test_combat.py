"""CombatStrategy 单测：攻坚破卡与窗口出牌。"""

import unittest

from lychee.arbiter import merge_intents
from lychee.state import GameState
from lychee.strategy import Intent
from lychee.strategy.combat import (
    CombatStrategy, PRIORITY_COMBAT_MAIN, PRIORITY_SET_GUARD, PRIORITY_SQUAD_SCOUT,
    SCOUT_PENDING_TIMEOUT, SQUAD_RESERVE_BEFORE_GATE, SQUAD_RESERVE_LOCKED,
)

MY_ID = 1001
OPP_ID = 2002

START = {
    "matchId": "combat-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "S09", "nodeType": "STATION"},
        {"nodeId": "S10", "nodeType": "KEY_PASS"},
        {"nodeId": "S15", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S09", "toNodeId": "S10",
         "routeType": "ROAD", "distance": 30, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S10", "toNodeId": "S15",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {"roles": {"terminalNodeIds": ["S15"]}}},
}

RUSH_OBSTACLE_START = {
    "matchId": "rush-obstacle-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "S01", "nodeType": "START", "start": True},
        {"nodeId": "S06", "nodeType": "STATION"},
        {"nodeId": "S02", "nodeType": "STATION"},
        {"nodeId": "S10", "nodeType": "KEY_PASS"},
        {"nodeId": "S15", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "S01", "toNodeId": "S06",
         "routeType": "MOUNTAIN", "distance": 1, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "S06", "toNodeId": "S10",
         "routeType": "MOUNTAIN", "distance": 1, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "S10", "toNodeId": "S15",
         "routeType": "MOUNTAIN", "distance": 1, "bidirectional": True},
        {"edgeId": "E4", "fromNodeId": "S01", "toNodeId": "S02",
         "routeType": "WATER", "distance": 3, "bidirectional": True},
        {"edgeId": "E5", "fromNodeId": "S02", "toNodeId": "S15",
         "routeType": "WATER", "distance": 3, "bidirectional": True},
    ],
    "map": {"gameplay": {
        "roles": {"startNodeId": "S01", "terminalNodeIds": ["S15"]},
    }},
}


def inquire(round_no: int, *, node: str = "S09", state: str = "IDLE",
            good: int = 98, bad: int = 2, freshness: float = 85.0,
            guard_points: int = 4, contests: list | None = None,
            nodes: list | None = None, phase: str = "NORMAL",
            next_node: str = "", move_dir: str = "", squad_available: int = 8,
            squad_in_flight: int = 0, opp_node: str = "S10",
            opp_next: str = "", opp_state: str = "IDLE",
            opp_progress_ms: int = 0, opp_total_ms: int = 0,
            resources: dict | None = None, events: list | None = None,
            buffs: list | None = None, tasks: list | None = None,
            task_score: int = 0, total_score: int = 0,
            opp_total_score: int = 0, verified: bool = False,
            opp_squads: int = 0) -> dict:
    return {
        "round": round_no,
        "phase": phase,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "moveDirection": move_dir,
                     "goodFruit": good, "badFruit": bad,
                     "freshness": freshness, "guardActionPoint": guard_points,
                     "squadAvailable": squad_available,
                     "squadInFlight": squad_in_flight, "verified": verified,
                     "resources": resources or {}, "buffs": buffs or [],
                     "taskScore": task_score, "totalScore": total_score},
                    {"playerId": OPP_ID, "teamId": "BLUE", "state": opp_state,
                     "currentNodeId": opp_node, "nextNodeId": opp_next,
                     "edgeProgressMs": opp_progress_ms, "edgeTotalMs": opp_total_ms,
                     "totalScore": opp_total_score, "squadAvailable": opp_squads}],
        "nodes": nodes or [],
        "contests": contests or [],
        "events": events or [],
        "tasks": tasks or [],
    }


def opp_committed_to_s10(progress_ms: int = 0, total_ms: int = 30000) -> dict:
    """对手已 commit 上 S09→S10 边（MOVING、剩余边帧充裕）→ freeze_window_open。"""
    return {"opp_node": "S09", "opp_next": "S10", "opp_state": "MOVING",
            "opp_progress_ms": progress_ms, "opp_total_ms": total_ms}


def guard_s10(defense: int = 6, age: int = 0) -> list[dict]:
    return [{"nodeId": "S10", "guard": {"active": True, "ownerTeamId": "BLUE",
                                         "defense": defense, "initialDefense": defense,
                                         "maxDefense": 7, "ageRound": age}}]


def reinforce_dispatch_event(round_no: int) -> list[dict]:
    """对手派 SQUAD_REINFORCE 的公开事件（13:22 局 r296 形态）。"""
    return [{"eventId": f"EV_{round_no}", "type": "SQUAD_DISPATCH", "round": round_no,
             "payload": {"playerId": OPP_ID, "action": "SQUAD_REINFORCE",
                         "targetNodeId": "S10", "orderId": f"SQ_{round_no}"}}]


def obstacle_s10() -> list[dict]:
    return [{"nodeId": "S10", "hasObstacle": True, "obstacleType": "LANDSLIDE"}]


def task(task_id: str, node: str, *, score: int = 30) -> dict:
    return {"taskId": task_id, "taskTemplateId": "T01", "nodeId": node,
            "processType": "PASS_NODE", "processRound": 3, "score": score,
            "refreshRound": 1, "expireRound": 500, "active": True,
            "completed": False, "failed": False,
            "ownerPlayerId": 0, "protectionPlayerId": 0}


def friendly_guard(node_id: str) -> dict:
    return {"nodeId": node_id, "guard": {"active": True, "ownerTeamId": "RED",
                                         "defense": 6, "initialDefense": 6,
                                         "maxDefense": 7}}


SCOUT_START = {
    "matchId": "scout-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True, "x": 0, "y": 0},
        {"nodeId": "B", "nodeType": "STATION", "x": 6, "y": 0},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True, "x": 8, "y": 0},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 4, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {
        "roles": {"startNodeId": "A", "terminalNodeIds": ["C"]},
        "processNodes": [
            {"nodeId": "B", "processType": "TRANSFER", "processRound": 5,
             "canWindow": True},
        ],
    }},
}

GATE_SCOUT_START = {
    "matchId": "gate-scout-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True, "x": 0, "y": 0},
        {"nodeId": "B", "nodeType": "GATE", "x": 6, "y": 0},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True, "x": 8, "y": 0},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 4, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {
        "roles": {"startNodeId": "A", "gateNodeId": "B", "terminalNodeIds": ["C"]},
        "processNodes": [
            {"nodeId": "B", "processType": "VERIFY", "processRound": 6,
             "canWindow": True},
        ],
    }},
}

ECON_SCOUT_START = {
    "matchId": "economy-scout-test",
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True, "x": 0, "y": 0},
        {"nodeId": "B", "nodeType": "STATION", "x": 6, "y": 0},
        {"nodeId": "D", "nodeType": "STATION", "x": 6, "y": 2},
        {"nodeId": "C", "nodeType": "FINISH", "terminal": True, "x": 8, "y": 0},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B",
         "routeType": "ROAD", "distance": 4, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C",
         "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "A", "toNodeId": "D",
         "routeType": "ROAD", "distance": 4, "bidirectional": True},
    ],
    "map": {"gameplay": {
        "roles": {"startNodeId": "A", "terminalNodeIds": ["C"]},
        "processNodes": [
            {"nodeId": "B", "processType": "TRANSFER", "processRound": 5,
             "canWindow": True},
        ],
    }},
}


class CombatStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = CombatStrategy()

    def intents(self, inq: dict) -> list[Intent]:
        self.state.update_inquire(inq)
        return self.strategy.propose(self.state)

    def actions(self, inq: dict) -> list[dict]:
        return [a for it in self.intents(inq) for a in it.actions]

    def scout_actions_with_eta(self, start: dict, eta: int) -> list[dict]:
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        self.strategy = CombatStrategy()
        self.strategy._eta_to_path_index = lambda _state, _prefix: eta
        return self.actions(inquire(10, node="A", opp_node="C"))

    def test_breaks_adjacent_enemy_guard_with_bad_fruit_first(self) -> None:
        intents = self.intents(inquire(320, nodes=guard_s10()))
        main = [it for it in intents if it.kind == "combat"][0]
        self.assertEqual(PRIORITY_COMBAT_MAIN, main.priority)
        self.assertEqual({"action": "BREAK_GUARD", "targetNodeId": "S10",
                          "goodFruit": 0, "badFruit": 2}, main.actions[0])

    def test_break_guard_does_not_overkill_with_bad_fruit(self) -> None:
        acts = self.actions(inquire(320, nodes=guard_s10(defense=1)))
        self.assertIn({"action": "BREAK_GUARD", "targetNodeId": "S10",
                       "goodFruit": 0, "badFruit": 1}, acts)

    def test_combat_break_suppresses_delivery_move_in_arbiter(self) -> None:
        intents = self.intents(inquire(320, nodes=guard_s10()))
        intents.append(Intent(kind="delivery", priority=100,
                              actions=[{"action": "MOVE", "targetNodeId": "S10"}]))
        actions = merge_intents(intents)
        self.assertIn({"action": "BREAK_GUARD", "targetNodeId": "S10",
                       "goodFruit": 0, "badFruit": 2}, actions)
        self.assertNotIn({"action": "MOVE", "targetNodeId": "S10"}, actions)

    def test_does_not_break_while_moving(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_partial_break_withheld_when_opponent_can_repump(self) -> None:
        # P4m 一击闸：火力 3 < 防 6 且对手有兵可远程增援（同帧序增援先落地）
        # → 不出手——白丢果子还休整 5 帧，改等风化/强通
        acts = self.actions(inquire(320, good=0, bad=1, opp_squads=8, nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_partial_break_allowed_when_opponent_out_of_squads(self) -> None:
        acts = self.actions(inquire(320, good=0, bad=1, opp_squads=0, nodes=guard_s10()))
        self.assertIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_partial_break_allowed_in_rush_phase(self) -> None:
        # RUSH 禁新提交小分队动作（任务书 1157）→ 增援威胁消失，半血刀照出
        acts = self.actions(inquire(320, good=0, bad=1, opp_squads=8, phase="RUSH",
                                    nodes=guard_s10()))
        self.assertIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_no_ammo_does_not_emit_high_priority_wait(self) -> None:
        acts = self.actions(inquire(320, nodes=guard_s10(), good=0, bad=0))
        self.assertEqual([], [a for a in acts if a["action"] in ("BREAK_GUARD", "WAIT")])

    def test_sets_guard_on_commit_when_ahead(self) -> None:
        # 我 camp 在 S10，对手已 commit 上 S09→S10 边（MOVING、剩余边帧充裕）→ 冻结窗口开
        intents = self.intents(inquire(200, node="S10", **opp_committed_to_s10()))
        guard = [it for it in intents if it.kind == "combat.guard"][0]
        self.assertEqual(PRIORITY_SET_GUARD, guard.priority)
        self.assertEqual({"action": "SET_GUARD", "targetNodeId": "S10",
                          "extraGoodFruit": 2}, guard.actions[0])

    def test_rolls_guard_when_opponent_far_in_band(self) -> None:
        # P4m 第四刀：对手停在 S09 未 commit，但到 S10 的 ETA=45 ∈ [20, 风化带)
        # → 领先足够，先手滚动卡（旧行为：等 commit；新行为：关门再走）
        acts = self.actions(inquire(200, node="S10", opp_node="S09"))
        self.assertIn({"action": "SET_GUARD", "targetNodeId": "S10",
                       "extraGoodFruit": 2}, acts)

    def test_no_rolling_guard_when_opponent_too_close(self) -> None:
        # 对手 ETA=15 < 20：4 帧读条窗口不稳，留给 set-on-commit 半路关门
        start = {**START, "matchId": "close-test", "edges": [
            {"edgeId": "E1", "fromNodeId": "S09", "toNodeId": "S10",
             "routeType": "ROAD", "distance": 10, "bidirectional": True},
            START["edges"][1]]}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(200, node="S10", opp_node="S09"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_squad_reserve_drops_when_opponent_locked(self) -> None:
        # P4m 决策#1（铁律唯一豁免）：我方有效卡压在对手到终点的必经咽喉 S10 上
        # → 对手够不到我方前路，保留量 6 → 2，腾 4 支给 G3 增援维持锁门卡
        self.state.update_inquire(inquire(
            200, node="S15", opp_node="S09", nodes=[friendly_guard("S10")]))
        self.assertEqual(SQUAD_RESERVE_LOCKED, CombatStrategy._squad_reserve(self.state))

    def test_squad_reserve_stays_six_without_lock(self) -> None:
        self.state.update_inquire(inquire(200, node="S15", opp_node="S09"))
        self.assertEqual(SQUAD_RESERVE_BEFORE_GATE,
                         CombatStrategy._squad_reserve(self.state))

    def test_no_rolling_guard_when_opponent_too_far(self) -> None:
        # 对手 ETA=135：到货时卡只剩防 2 < 3（风化成渣）→ 白设，不设
        start = {**START, "matchId": "far-test", "edges": [
            {"edgeId": "E1", "fromNodeId": "S09", "toNodeId": "S10",
             "routeType": "ROAD", "distance": 90, "bidirectional": True},
            START["edges"][1]]}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(200, node="S10", opp_node="S09"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_no_guard_when_freeze_window_too_narrow(self) -> None:
        # 对手已上边但只剩 4 帧（< 设卡读条4+安全2）→ 到站前设不完，别设
        acts = self.actions(inquire(200, node="S10",
                                    **opp_committed_to_s10(progress_ms=26000, total_ms=30000)))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_set_guard_yields_to_onnode_task_claim(self) -> None:
        # A2：同帧 economy 抢脚下任务(110) 与 combat 设卡(108) → 仲裁选抢任务
        claim = Intent(kind="economy", priority=110,
                       actions=[{"action": "CLAIM_TASK", "taskId": "T_x"}])
        guard = Intent(kind="combat.guard", priority=PRIORITY_SET_GUARD,
                       actions=[{"action": "SET_GUARD", "targetNodeId": "S10",
                                 "extraGoodFruit": 2}])
        acts = merge_intents([guard, claim])
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_x"}], acts)

    def test_set_guard_still_beats_bare_delivery_move(self) -> None:
        # 无经济动作时设卡(108) 仍先于纯走位(100) 触发
        move = Intent(kind="delivery", priority=100,
                      actions=[{"action": "MOVE", "targetNodeId": "S11"}])
        guard = Intent(kind="combat.guard", priority=PRIORITY_SET_GUARD,
                       actions=[{"action": "SET_GUARD", "targetNodeId": "S10",
                                 "extraGoodFruit": 2}])
        acts = merge_intents([move, guard])
        self.assertEqual([{"action": "SET_GUARD", "targetNodeId": "S10",
                           "extraGoodFruit": 2}], acts)

    def test_does_not_set_guard_at_terminal(self) -> None:
        acts = self.actions(inquire(200, node="S15", opp_node="S09"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_when_not_ahead(self) -> None:
        acts = self.actions(inquire(200, node="S10", opp_node="S10"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_sets_guard_when_ahead_on_score_with_freeze_window(self) -> None:
        # G6 放宽领先闸：领先分 + 冻结窗口开 + 对手仍能完赛 → 仍设卡（freeze EV > 悬赏喂分）
        intents = self.intents(inquire(200, node="S10", total_score=10, opp_total_score=0,
                                        **opp_committed_to_s10()))
        guard = [it for it in intents if it.kind == "combat.guard"]
        self.assertEqual(1, len(guard))

    def test_no_guard_when_deadline_or_opponent_doomed(self) -> None:
        # 临近死线（must_rush）时即使冻结窗口开也不设卡——让路直冲；此帧对手同时判死，
        # 覆盖"领先且对手判死不徒增悬赏"的弱化领先闸（二者在近终点同时成立）
        acts = self.actions(inquire(585, node="S10", total_score=10, opp_total_score=0,
                                    **opp_committed_to_s10()))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_when_two_friendly_guards_active(self) -> None:
        nodes = [friendly_guard("S09"), friendly_guard("S15")]
        acts = self.actions(inquire(200, node="S10", opp_node="S09", nodes=nodes))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_over_existing_guard(self) -> None:
        acts = self.actions(inquire(200, node="S10", opp_node="S09",
                                    nodes=[friendly_guard("S10")]))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_does_not_set_guard_below_good_fruit_floor(self) -> None:
        # 好果 < 地板 40（烧 3 好果后跌破）→ 护交付好果，不设卡（冻结窗口开也不设）
        acts = self.actions(inquire(200, node="S10", good=41, **opp_committed_to_s10()))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_sets_guard_above_good_fruit_floor(self) -> None:
        # 好果 50（烧 3 后 47 ≥ 40）→ 冻结窗口开时设满防卡
        intents = self.intents(inquire(200, node="S10", good=50, **opp_committed_to_s10()))
        self.assertEqual(1, len([it for it in intents if it.kind == "combat.guard"]))

    def test_break_guard_blocked_when_paused_mid_edge(self) -> None:
        # P4d 死锁根因①：半路被守卫暂停（WAITING+PAUSED+nextNodeId 保留）不是可攻坚状态，
        # 发 BREAK_GUARD 必被判 MOVING_ACTION_FORBIDDEN（任务书 8.2）
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_break_guard_blocked_mid_edge_without_pause_flag(self) -> None:
        # nextNodeId 非空即在边上，即使字段变体缺 PAUSED 标记也不得攻坚
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    nodes=guard_s10()))
        self.assertNotIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_break_guard_still_fires_when_docked_waiting(self) -> None:
        # 防回归锚点：真停靠节点（nextNodeId 空、非 PAUSED）的 WAITING 仍可攻坚
        acts = self.actions(inquire(320, state="WAITING", nodes=guard_s10()))
        self.assertIn({"action": "BREAK_GUARD", "targetNodeId": "S10",
                       "goodFruit": 0, "badFruit": 2}, acts)

    def test_squad_weaken_keeps_dispatching_when_paused(self) -> None:
        # P4d 死锁根因②：被暂停成 WAITING 后削卡不能熄火——它是唯一快速清卡手段
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10()))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_weaken_stops_after_reinforce_dispatch_evidence(self) -> None:
        # P4m 止损：对手派增援的事件一出现（不等落地），削卡战即停——消耗战必败
        self.intents(inquire(319, events=reinforce_dispatch_event(318), opp_squads=6))
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(), opp_squads=6))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_weaken_resumes_when_reinforcer_out_of_squads(self) -> None:
        # 证据在册但对手兵尽（<2）→ 增援威胁消失，削卡恢复
        self.intents(inquire(319, events=reinforce_dispatch_event(318), opp_squads=6))
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(), opp_squads=1))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_defense_rise_on_aged_guard_sets_evidence(self) -> None:
        # 兜底探测：非新设敌卡（age>0）防值 2→4 = 增援落地（13:22 局 r317 形态）
        self.intents(inquire(318, state="WAITING", next_node="S10",
                             move_dir="PAUSED", nodes=guard_s10(defense=2, age=20),
                             opp_squads=6, squad_in_flight=1))
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(defense=4, age=22),
                                    opp_squads=6))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_fresh_guard_defense_track_no_false_positive(self) -> None:
        # 同点卡消亡后重设（防值 0→新卡 age=0）不误判为增援，首支探针照发
        self.intents(inquire(318, state="WAITING", next_node="S10",
                             move_dir="PAUSED", nodes=guard_s10(defense=2, age=29),
                             opp_squads=6, squad_in_flight=1))
        self.intents(inquire(319, state="WAITING", next_node="S10", opp_squads=6))
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(defense=4, age=0),
                                    opp_squads=6))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_reinforces_own_choke_guard_below_max(self) -> None:
        # G3：我方在对手必经咽喉 S10 的卡防御 6<上限 7（被削/风化）→ 远程增援补回
        acts = self.actions(inquire(200, node="S10", opp_node="S09",
                                    nodes=[friendly_guard("S10")]))
        self.assertIn({"action": "SQUAD_REINFORCE", "targetNodeId": "S10"}, acts)

    def test_no_reinforce_at_max_defense(self) -> None:
        at_max = [{"nodeId": "S10", "guard": {"active": True, "ownerTeamId": "RED",
                   "defense": 7, "initialDefense": 7, "maxDefense": 7}}]
        acts = self.actions(inquire(200, node="S10", opp_node="S09", nodes=at_max))
        self.assertNotIn("SQUAD_REINFORCE", [a["action"] for a in acts])

    def test_no_reinforce_without_enough_squads(self) -> None:
        # 只剩 3 支 < 2(增援) + 2(保留地板) → 不增援，留人手削卡
        acts = self.actions(inquire(200, node="S10", opp_node="S09", squad_available=3,
                                    nodes=[friendly_guard("S10")]))
        self.assertNotIn("SQUAD_REINFORCE", [a["action"] for a in acts])

    def test_no_reinforce_when_guard_not_opponent_choke(self) -> None:
        # 对手已越过 S10（停在 S10 自身）→ S10 不再是其必经咽喉，补了白费
        acts = self.actions(inquire(200, node="S09", opp_node="S10",
                                    nodes=[friendly_guard("S10")]))
        self.assertNotIn("SQUAD_REINFORCE", [a["action"] for a in acts])

    def test_no_reinforce_in_rush(self) -> None:
        acts = self.actions(inquire(200, node="S10", opp_node="S09", phase="RUSH",
                                    nodes=[friendly_guard("S10")]))
        self.assertNotIn("SQUAD_REINFORCE", [a["action"] for a in acts])

    def test_squad_weaken_paused_stops_when_enough_in_flight(self) -> None:
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(),
                                    squad_in_flight=3))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_squad_weaken_paused_respects_squad_floor(self) -> None:
        acts = self.actions(inquire(320, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=guard_s10(),
                                    squad_available=1))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_squad_weakens_next_node_guard_while_moving(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", next_node="S10", nodes=guard_s10()))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "S10"}, acts)

    def test_squad_weaken_stops_when_enough_in_flight(self) -> None:
        acts = self.actions(inquire(320, state="MOVING", next_node="S10",
                                    nodes=guard_s10(), squad_in_flight=3))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_clears_obstacle_on_terminal_path_next_hop(self) -> None:
        # P4d 实测：咽喉道路障碍无人清 = MOVE 永拒 = 卡死未送达（任务书 2.4.4）
        intents = self.intents(inquire(100, opp_node="", nodes=obstacle_s10()))
        clear = [it for it in intents if it.kind == "combat.clear"][0]
        self.assertEqual(PRIORITY_COMBAT_MAIN, clear.priority)
        self.assertEqual({"action": "CLEAR", "targetNodeId": "S10"}, clear.actions[0])

    def test_squad_clears_adjacent_first_common_rush_target_obstacle(self) -> None:
        acts = self.actions(inquire(100, nodes=obstacle_s10()))
        self.assertIn({"action": "SQUAD_CLEAR", "targetNodeId": "S10"}, acts)
        self.assertNotIn({"action": "CLEAR", "targetNodeId": "S10"}, acts)

    def test_clears_obstacle_on_first_common_rush_next_hop(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(RUSH_OBSTACLE_START)
        self.strategy = CombatStrategy()
        nodes = [{"nodeId": "S06", "hasObstacle": True, "obstacleType": "ROCKFALL"}]
        intents = self.intents(inquire(1, node="S01", opp_node="S01", nodes=nodes))
        clear = [it for it in intents if it.kind == "combat.clear"][0]
        self.assertEqual({"action": "CLEAR", "targetNodeId": "S06"}, clear.actions[0])

    def test_clear_beats_delivery_move_in_arbiter(self) -> None:
        intents = self.intents(inquire(100, opp_node="", nodes=obstacle_s10()))
        intents.append(Intent(kind="delivery", priority=100,
                              actions=[{"action": "MOVE", "targetNodeId": "S10"}]))
        actions = merge_intents(intents)
        self.assertIn({"action": "CLEAR", "targetNodeId": "S10"}, actions)
        self.assertNotIn({"action": "MOVE", "targetNodeId": "S10"}, actions)

    def test_no_clear_when_mid_edge(self) -> None:
        # 清障是主车队停靠动作，半路（含被暂停）不得提交
        acts = self.actions(inquire(100, state="WAITING", next_node="S10",
                                    move_dir="PAUSED", nodes=obstacle_s10()))
        self.assertNotIn("CLEAR", [a["action"] for a in acts])

    def test_no_clear_without_obstacle(self) -> None:
        acts = self.actions(inquire(100))
        self.assertNotIn("CLEAR", [a["action"] for a in acts])

    def test_no_set_guard_when_must_rush(self) -> None:
        # P4d 送达优先：S10 到终点 3 帧，590+3+60 ≥ 600，设卡（纯刷分）让路
        acts = self.actions(inquire(590, node="S10", opp_node="S09"))
        self.assertNotIn("SET_GUARD", [a["action"] for a in acts])

    def test_break_guard_unaffected_by_must_rush(self) -> None:
        # 攻坚打的是终点路径上的卡，是送达的一部分，不受送达优先约束
        acts = self.actions(inquire(550, nodes=guard_s10()))
        self.assertIn("BREAK_GUARD", [a["action"] for a in acts])

    def test_plays_xian_gong_first_for_relevant_window(self) -> None:
        # G7 默认三联献贡：鲜度≥80、好果>1 时首选献贡
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}, acts)

    def test_plays_bing_zheng_when_not_fresh_enough_for_xian_gong(self) -> None:
        contests = [{"contestId": "C1", "contestType": "PASS", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, freshness=70.0))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}, acts)

    def test_only_one_relevant_window_card_per_frame(self) -> None:
        contests = [
            {"contestId": "C1", "contestType": "RESOURCE", "targetNodeId": "",
             "redPlayerId": MY_ID, "bluePlayerId": OPP_ID},
            {"contestId": "C2", "contestType": "PASS", "targetNodeId": "S10",
             "redPlayerId": MY_ID, "bluePlayerId": OPP_ID},
        ]
        acts = [a for a in self.actions(inquire(44, contests=contests))
                if a["action"] == "WINDOW_CARD"]
        self.assertEqual([{"action": "WINDOW_CARD", "contestId": "C2", "card": "XIAN_GONG"}], acts)

    def test_irrelevant_window_gets_no_explicit_abstain(self) -> None:
        contests = [{"contestId": "C1", "contestType": "RESOURCE", "targetNodeId": "",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertNotIn("WINDOW_CARD", [a["action"] for a in acts])

    def test_task_window_uses_marginal_task_value(self) -> None:
        contests = [{"contestId": "C1", "contestType": "TASK", "taskId": "T_x",
                     "targetNodeId": "S08", "redPlayerId": MY_ID,
                     "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests,
                                    tasks=[task("T_x", "S08")]))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}, acts)

    def test_task_window_abstains_when_task_score_capped(self) -> None:
        contests = [{"contestId": "C1", "contestType": "TASK", "taskId": "T_x",
                     "targetNodeId": "S08", "redPlayerId": MY_ID,
                     "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests,
                                    tasks=[task("T_x", "S08")], task_score=130))
        self.assertNotIn("WINDOW_CARD", [a["action"] for a in acts])

    def test_resource_window_uses_resource_value_and_cap(self) -> None:
        contests = [{"contestId": "C1", "contestType": "RESOURCE",
                     "resourceType": "ICE_BOX", "redPlayerId": MY_ID,
                     "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}, acts)

        acts = self.actions(inquire(45, contests=contests, resources={"ICE_BOX": 2}))
        self.assertNotIn("WINDOW_CARD", [a["action"] for a in acts])

    def test_plays_yan_die_from_document_resource_without_use_resource(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, freshness=70.0,
                                    guard_points=1, resources={"PASS_TOKEN": 1}))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "YAN_DIE"}, acts)
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_gate_window_spends_last_guard_point(self) -> None:
        contests = [{"contestId": "C1", "contestType": "GATE", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, freshness=70.0, guard_points=1))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}, acts)

    def test_forced_xian_gong_ignores_opponent_card_history(self) -> None:
        # G7 强制献贡：不看对手出牌历史，能出献贡就一律献贡（旧倾向自适应已删）
        contests = [{"contestId": "C3", "contestType": "PASS", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        reveals = [
            {"eventId": "R1", "type": "WINDOW_CARD_REVEAL", "round": 40,
             "payload": {"contestId": "C1", "roundIndex": 1,
                         "redCard": "YAN_DIE", "blueCard": "XIAN_GONG"}},
            {"eventId": "R2", "type": "WINDOW_CARD_REVEAL", "round": 41,
             "payload": {"contestId": "C2", "roundIndex": 1,
                         "redCard": "YAN_DIE", "blueCard": "XIAN_GONG"}},
        ]
        acts = self.actions(inquire(44, contests=contests, events=reveals,
                                    resources={"FAST_HORSE": 1}))
        # 对手连出献贡，旧逻辑会切 QIANG_XING 反制；强制版仍出献贡（接受平局）
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C3", "card": "XIAN_GONG"}, acts)

    def test_mirror_same_card_high_id_switches_to_counter(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "roundIndex": 2, "redPlayerId": 999, "bluePlayerId": MY_ID}]
        reveals = [{"eventId": "R1", "type": "WINDOW_CARD_REVEAL", "round": 40,
                    "payload": {"contestId": "C1", "roundIndex": 1,
                                "redCard": "BING_ZHENG", "blueCard": "BING_ZHENG"}}]
        acts = self.actions(inquire(44, contests=contests, events=reveals))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}, acts)

    def test_mirror_same_card_low_id_repeats_original(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "roundIndex": 2, "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        reveals = [{"eventId": "R1", "type": "WINDOW_CARD_REVEAL", "round": 40,
                    "payload": {"contestId": "C1", "roundIndex": 1,
                                "redCard": "BING_ZHENG", "blueCard": "BING_ZHENG"}}]
        acts = self.actions(inquire(44, contests=contests, events=reveals))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}, acts)

    def test_no_mirror_reveal_keeps_default_choice(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "roundIndex": 2, "redPlayerId": 999, "bluePlayerId": MY_ID}]
        acts = self.actions(inquire(44, contests=contests))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "XIAN_GONG"}, acts)

    def test_free_qiang_xing_is_played_when_other_cards_unavailable(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, good=0, freshness=70.0,
                                    guard_points=0,
                                    buffs=[{"type": "FAST_HORSE", "remainingRound": 3}]))
        self.assertIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"}, acts)

    def test_qiang_xing_needs_buff_or_horse(self) -> None:
        contests = [{"contestId": "C1", "contestType": "DOCK", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        acts = self.actions(inquire(44, contests=contests, good=0, freshness=70.0,
                                    guard_points=0))
        self.assertNotIn({"action": "WINDOW_CARD", "contestId": "C1", "card": "QIANG_XING"},
                         acts)

    def test_xian_gong_keeps_one_good_fruit_floor(self) -> None:
        contests = [{"contestId": "C3", "contestType": "PASS", "targetNodeId": "S10",
                     "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}]
        reveals = [
            {"eventId": "R1", "type": "WINDOW_CARD_REVEAL", "round": 40,
             "payload": {"contestId": "C1", "roundIndex": 1,
                         "redCard": "YAN_DIE", "blueCard": "BING_ZHENG"}},
            {"eventId": "R2", "type": "WINDOW_CARD_REVEAL", "round": 41,
             "payload": {"contestId": "C2", "roundIndex": 1,
                         "redCard": "YAN_DIE", "blueCard": "BING_ZHENG"}},
        ]
        acts = self.actions(inquire(44, contests=contests, events=reveals,
                                    good=1, guard_points=0))
        self.assertNotIn({"action": "WINDOW_CARD", "contestId": "C3", "card": "XIAN_GONG"},
                         acts)

    def test_squad_scouts_upcoming_process_node(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        intents = self.intents(inquire(10, node="A", opp_node="C"))
        scout = [it for it in intents if it.actions[0]["action"] == "SQUAD_SCOUT"][0]
        self.assertEqual(PRIORITY_SQUAD_SCOUT, scout.priority)
        self.assertEqual({"action": "SQUAD_SCOUT", "targetNodeId": "B"}, scout.actions[0])

    def test_squad_scout_dedupes_pending_and_marker(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"},
                      self.actions(inquire(10, node="A", opp_node="C")))
        self.assertNotIn("SQUAD_SCOUT",
                         [a["action"] for a in self.actions(inquire(11, node="A", opp_node="C"))])

        add = [{"eventId": "S1", "type": "SCOUT_MARKER_ADD", "round": 12,
                "payload": {"playerId": MY_ID, "targetNodeId": "B", "expireRound": 50}}]
        self.assertNotIn("SQUAD_SCOUT",
                         [a["action"] for a in self.actions(inquire(12, node="A", opp_node="C",
                                                                    events=add))])
        consume = [{"eventId": "S2", "type": "SCOUT_MARKER_CONSUME", "round": 13,
                    "payload": {"playerId": MY_ID, "targetNodeId": "B"}}]
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"},
                      self.actions(inquire(13, node="A", opp_node="C", events=consume)))

    def test_squad_scout_pending_timeout_covers_full_dispatch_delay(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"},
                      self.actions(inquire(10, node="A", opp_node="C")))
        acts = self.actions(inquire(20, node="A", opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])
        acts = self.actions(inquire(10 + SCOUT_PENDING_TIMEOUT, node="A", opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])
        acts = self.actions(inquire(10 + SCOUT_PENDING_TIMEOUT + 1, node="A", opp_node="C"))
        self.assertIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_reserve_holds_six_until_gate_verified(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        self.state.update_inquire(inquire(100, node="A", opp_node="C"))
        self.assertEqual(SQUAD_RESERVE_BEFORE_GATE, self.strategy._squad_reserve(self.state))
        self.state.update_inquire(inquire(360, node="A", opp_node="C"))
        self.assertEqual(SQUAD_RESERVE_BEFORE_GATE, self.strategy._squad_reserve(self.state))
        self.state.update_inquire(inquire(360, node="A", opp_node="C", verified=True))
        self.assertEqual(0, self.strategy._squad_reserve(self.state))

    def test_squad_scout_never_dips_below_gate_reserve(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(100, node="A", squad_available=6, opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(360, node="A", squad_available=5, opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(100, node="A", squad_available=7, opp_node="C"))
        self.assertIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_scout_guarder_reserve_covers_full_weaken(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        nodes = [{"nodeId": "B", "guard": {"active": True, "ownerTeamId": "BLUE",
                                            "defense": 6, "initialDefense": 6}}]
        acts = self.actions(inquire(100, node="A", nodes=nodes,
                                    squad_available=6, opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(100, node="A", nodes=nodes,
                                    squad_available=7, opp_node="C"))
        self.assertIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_actions_stop_in_rush_phase(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(400, node="A", phase="RUSH", opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])

        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = CombatStrategy()
        acts = self.actions(inquire(400, state="WAITING", phase="RUSH",
                                    next_node="S10", move_dir="PAUSED",
                                    nodes=guard_s10()))
        self.assertNotIn("SQUAD_WEAKEN", [a["action"] for a in acts])

    def test_squad_scout_requires_landing_margin_before_arrival(self) -> None:
        acts = self.scout_actions_with_eta(SCOUT_START, eta=4)
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])
        acts = self.scout_actions_with_eta(SCOUT_START, eta=5)
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"}, acts)

    def test_squad_scout_applies_regular_eta_cap(self) -> None:
        acts = self.scout_actions_with_eta(SCOUT_START, eta=25)
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"}, acts)
        acts = self.scout_actions_with_eta(SCOUT_START, eta=26)
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_scout_allows_gate_marker_up_to_lifetime_window(self) -> None:
        acts = self.scout_actions_with_eta(GATE_SCOUT_START, eta=48)
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"}, acts)
        acts = self.scout_actions_with_eta(GATE_SCOUT_START, eta=49)
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_scout_uses_economy_current_plan_when_worthwhile(self) -> None:
        class StubEconomy:
            current_plan = ("D", 5)

        start = {**ECON_SCOUT_START, "map": {"gameplay": {
            "roles": {"startNodeId": "A", "terminalNodeIds": ["C"]},
            "processNodes": [],
        }}}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        self.strategy = CombatStrategy(economy=StubEconomy())
        acts = self.actions(inquire(10, node="A", opp_node="C"))
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "D"}, acts)

    def test_squad_scout_ignores_low_value_economy_plan(self) -> None:
        class StubEconomy:
            current_plan = ("D", 2)

        start = {**ECON_SCOUT_START, "map": {"gameplay": {
            "roles": {"startNodeId": "A", "terminalNodeIds": ["C"]},
            "processNodes": [],
        }}}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        self.strategy = CombatStrategy(economy=StubEconomy())
        acts = self.actions(inquire(10, node="A", opp_node="C"))
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])

    def test_squad_scout_picks_nearest_candidate_between_route_and_economy(self) -> None:
        class StubEconomy:
            current_plan = ("D", 5)

        self.state = GameState(MY_ID)
        self.state.update_start(ECON_SCOUT_START)
        self.strategy = CombatStrategy(economy=StubEconomy())
        self.strategy._eta_to_path_index = lambda _state, prefix: 6 if prefix[-1] == "D" else 8
        acts = self.actions(inquire(10, node="A", opp_node="C"))
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "D"}, acts)

        self.strategy = CombatStrategy(economy=StubEconomy())
        self.strategy._eta_to_path_index = lambda _state, prefix: 9 if prefix[-1] == "D" else 5
        acts = self.actions(inquire(11, node="A", opp_node="C"))
        self.assertIn({"action": "SQUAD_SCOUT", "targetNodeId": "B"}, acts)

    def test_squad_weaken_wins_over_scout(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(SCOUT_START)
        self.strategy = CombatStrategy()
        nodes = [{"nodeId": "B", "guard": {"active": True, "ownerTeamId": "BLUE",
                                            "defense": 6, "initialDefense": 6}}]
        acts = self.actions(inquire(10, node="A", state="MOVING", next_node="B",
                                    nodes=nodes, opp_node="C"))
        self.assertIn({"action": "SQUAD_WEAKEN", "targetNodeId": "B"}, acts)
        self.assertNotIn("SQUAD_SCOUT", [a["action"] for a in acts])


if __name__ == "__main__":
    unittest.main()
