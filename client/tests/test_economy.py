"""EconomyStrategy 单测：合成小地图逐帧驱动任务/冰鉴状态机。

地图（在 delivery 测试图基础上加一个岔路节点 E）：
    A(起点) → B(TRANSFER处理2帧) → C(宫门,VERIFY) → D(终点)
                └—— E（岔路，无处理）
全部 ROAD 双向，主线边 distance=2（3帧/边），B—E distance=4（6帧）。
"""

import unittest

from lychee.state import GameState
from lychee.strategy.economy import (
    EconomyStrategy, PRIORITY_ECONOMY, PRIORITY_ICE_USE, TASK_SCORE_GOAL,
    _use_resource_action,
)

MY_ID = 1001
OPP_ID = 2002

START = {
    "matchId": "m-test",
    "round": 1,
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "t"},
                {"playerId": OPP_ID, "teamId": "BLUE", "name": "o"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "STATION"},
        {"nodeId": "C", "nodeType": "GATE"},
        {"nodeId": "D", "nodeType": "FINISH", "terminal": True},
        {"nodeId": "E", "nodeType": "STATION"},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B", "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C", "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "C", "toNodeId": "D", "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E4", "fromNodeId": "B", "toNodeId": "E", "routeType": "ROAD", "distance": 4, "bidirectional": True},
    ],
    "map": {"gameplay": {
        "roles": {"startNodeId": "A", "gateNodeId": "C", "terminalNodeIds": ["D"]},
        "processNodes": [
            {"nodeId": "B", "processType": "TRANSFER", "processRound": 2, "canWindow": True},
            {"nodeId": "C", "processType": "VERIFY", "processRound": 6, "canWindow": True},
        ],
    }},
}


def task(task_id: str, node: str, *, score: int = 30, proc: int = 3, expire: int = 500,
         owner: int = 0, protect: int = 0, active: bool = True, completed: bool = False,
         template: str = "T01") -> dict:
    return {"taskId": task_id, "taskTemplateId": template, "nodeId": node,
            "processType": "CLAIM_TASK", "processRound": proc, "score": score,
            "refreshRound": 1, "expireRound": expire, "active": active,
            "completed": completed, "failed": False,
            "ownerPlayerId": owner, "protectionPlayerId": protect}


def inquire(round_no: int, *, node: str = "A", state: str = "IDLE", phase: str = "NORMAL",
            verified: bool = False, process: dict | None = None, next_node: str | None = None,
            action_results: list | None = None, tasks: list | None = None,
            nodes: list | None = None, resources: dict | None = None,
            task_score: int = 0, freshness: float = 100.0,
            buffs: list | None = None, weather: dict | None = None,
            contests: list | None = None) -> dict:
    return {
        "round": round_no, "phase": phase,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "currentProcess": process, "verified": verified,
                     "goodFruit": 90, "freshness": freshness,
                     "resources": resources or {}, "taskScore": task_score,
                     "buffs": buffs or []}],
        "tasks": tasks or [],
        "nodes": nodes or [],
        "contests": contests or [],
        "actionResults": action_results or [],
        "weather": weather or {},
    }


class EconomyTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = EconomyStrategy()

    def step(self, inq: dict) -> list:
        self.state.update_inquire(inq)
        return self.strategy.propose(self.state)

    def acts(self, inq: dict) -> list[dict]:
        return [a for it in self.step(inq) for a in it.actions]

    def test_moves_toward_task_then_claims(self) -> None:
        # A 上有 B 点任务：先赶路
        acts = self.acts(inquire(1, node="A", tasks=[task("T_1", "B")]))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)
        # 到 B：直接领取（固定处理站点上领取不受处理门限制）
        acts = self.acts(inquire(2, node="B", tasks=[task("T_1", "B")]))
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_1"}], acts)

    def test_priority_is_economy(self) -> None:
        intents = self.step(inquire(1, node="A", tasks=[task("T_1", "B")]))
        self.assertEqual(1, len(intents))
        self.assertEqual(PRIORITY_ECONOMY, intents[0].priority)

    def test_quiet_during_claim_process(self) -> None:
        proc = {"action": "CLAIM_TASK", "objectKey": "TASK:T_1", "taskId": "T_1", "remainRound": 2}
        self.assertEqual([], self.step(inquire(2, node="B", state="PROCESSING",
                                               process=proc, tasks=[task("T_1", "B")])))

    def test_quiet_when_moving(self) -> None:
        self.assertEqual([], self.step(inquire(2, node="A", state="MOVING", next_node="B",
                                               tasks=[task("T_1", "B")])))

    def test_quiet_after_goal_reached(self) -> None:
        inq = inquire(1, node="A", tasks=[task("T_1", "B")], task_score=TASK_SCORE_GOAL)
        self.assertEqual([], self.step(inq))

    def test_quiet_in_rush_and_after_verify(self) -> None:
        self.assertEqual([], self.step(inquire(1, node="A", phase="RUSH", tasks=[task("T_1", "B")])))
        self.assertEqual([], self.step(inquire(2, node="A", verified=True, tasks=[task("T_1", "B")])))

    def test_skips_opponent_owned_or_protected(self) -> None:
        # 对方归属/保护的任务不碰；没有其他候选 → 原地蹲守等刷新
        self.assertEqual([{"action": "WAIT"}],
                         self.acts(inquire(1, tasks=[task("T_1", "B", owner=OPP_ID)])))
        self.assertEqual([{"action": "WAIT"}],
                         self.acts(inquire(2, tasks=[task("T_1", "B", protect=OPP_ID)])))

    def test_own_protection_ok(self) -> None:
        acts = self.acts(inquire(1, tasks=[task("T_1", "B", protect=MY_ID)]))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)

    def test_skips_expiring_task(self) -> None:
        # A→B 3 帧 + 读条 3 帧 > expire=4 → 追不上，放弃（转为蹲守）
        self.assertEqual([{"action": "WAIT"}],
                         self.acts(inquire(1, tasks=[task("T_1", "B", expire=4)])))

    def test_skips_completed_inactive(self) -> None:
        self.assertEqual([{"action": "WAIT"}],
                         self.acts(inquire(1, tasks=[task("T_1", "B", completed=True)])))
        self.assertEqual([{"action": "WAIT"}],
                         self.acts(inquire(2, tasks=[task("T_1", "B", active=False)])))

    def test_prefers_on_route_task(self) -> None:
        # B 顺路（绕路 0）、E 岔路（绕路 12 帧）：同分值选 B
        acts = self.acts(inquire(1, node="A", tasks=[task("T_e", "E"), task("T_b", "B")]))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)
        acts = self.acts(inquire(2, node="B", tasks=[task("T_e", "E"), task("T_b", "B")]))
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_b"}], acts)

    def test_detours_for_task_when_worth(self) -> None:
        # 只有 E 有任务：值得绕路去（任务 30 分 vs 12 帧绕路）。
        # 第 1 帧到站 B 固定处理未完成先静默，处理受理后恢复赶路
        self.assertEqual([], self.step(inquire(1, node="B", tasks=[task("T_e", "E")])))
        acts = self.acts(inquire(2, node="B", tasks=[task("T_e", "E")],
                                 action_results=[{"round": 1, "playerId": MY_ID,
                                                  "action": "PROCESS", "accepted": True}]))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "E"}], acts)

    def test_small_task_secured_then_far_task_chased(self) -> None:
        # 一步前瞻：脚下 15 分先落袋（读条仅 3 帧），随后仍去追绕路的 30 分。
        # （单步比值制会因小任务性价比高而永远放弃大任务，实测漏掉 90 里程碑）
        t = [task("T_here", "A", score=15), task("T_far", "E", score=30)]
        acts = self.acts(inquire(1, node="A", tasks=t))
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_here"}], acts)
        # 小任务完成后：追大任务
        t2 = [task("T_here", "A", score=15, completed=True), task("T_far", "E", score=30)]
        acts = self.acts(inquire(2, node="A", tasks=t2))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)

    def test_lingers_when_no_candidates_and_time_ample(self) -> None:
        # 无任何候选、离截止尚早：原地 WAIT 蹲刷新（压制 delivery 的赶路）
        intents = self.step(inquire(1, node="A", resources={"ICE_BOX": 2}))
        self.assertEqual([{"action": "WAIT"}], [a for it in intents for a in it.actions])
        self.assertEqual(PRIORITY_ECONOMY, intents[0].priority)

    def test_no_linger_near_deadline(self) -> None:
        # 现在动身刚好来得及：不再蹲守，放行 delivery
        self.assertEqual([], self.step(inquire(555, node="A", resources={"ICE_BOX": 2})))

    def test_no_linger_at_unprocessed_station(self) -> None:
        # 固定处理站点欠处理：不 WAIT（否则饿死 delivery 的 PROCESS）
        self.assertEqual([], self.step(inquire(1, node="B", resources={"ICE_BOX": 2})))

    def test_waits_for_station_process_before_leaving(self) -> None:
        # 停在固定处理站点 B、处理未完成：不抢 MOVE（让位 delivery 的 PROCESS）
        self.assertEqual([], self.step(inquire(1, node="B", tasks=[task("T_e", "E")])))
        # 观察到处理读条完成后：恢复赶路
        proc = {"action": "PROCESS", "targetNodeId": "B", "remainRound": 1}
        self.assertEqual([], self.step(inquire(2, node="B", state="PROCESSING",
                                               process=proc, tasks=[task("T_e", "E")])))
        acts = self.acts(inquire(3, node="B", tasks=[task("T_e", "E")]))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "E"}], acts)

    def test_claim_rejected_retries_then_backs_off(self) -> None:
        # 第一次被拒：下帧重试
        self.acts(inquire(1, node="B", tasks=[task("T_1", "B")]))
        rej = [{"round": 1, "playerId": MY_ID, "action": "CLAIM_TASK",
                "accepted": False, "result": "ACTION_REJECTED", "errorCode": "OBJECT_BUSY"}]
        acts = self.acts(inquire(2, node="B", tasks=[task("T_1", "B")], action_results=rej))
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_1"}], acts)
        # 第二次被拒：拉黑该任务一段时间（无其他候选 → 静默）
        rej2 = [{"round": 2, "playerId": MY_ID, "action": "CLAIM_TASK",
                 "accepted": False, "result": "ACTION_REJECTED", "errorCode": "OBJECT_BUSY"}]
        self.assertEqual([], self.step(inquire(3, node="B", tasks=[task("T_1", "B")],
                                               action_results=rej2)))

    def test_obstacle_task_claimed_from_adjacent(self) -> None:
        # E 有障碍（清障类任务）：进不去，站相邻节点 B 处理
        nodes = [{"nodeId": "E", "hasObstacle": True, "obstacleType": "ROCK"}]
        acts = self.acts(inquire(1, node="B", nodes=nodes, tasks=[task("T_e", "E")],
                                 action_results=[{"round": 0, "playerId": MY_ID,
                                                  "action": "PROCESS", "accepted": True}]))
        self.assertEqual([{"action": "CLAIM_TASK", "taskId": "T_e"}], acts)

    def test_consumable_task_needs_stock(self) -> None:
        # T06 类模板需要消耗马：没有库存不接（转蹲守），有库存接
        start = dict(START)
        start["taskTemplates"] = [{"taskTemplateId": "T06", "processRound": 3, "score": 30,
                                   "requiredResourceTypes": ["SHORT_HORSE"]}]
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        t = [task("T_1", "B", template="T06")]
        self.assertEqual([{"action": "WAIT"}], self.acts(inquire(1, node="A", tasks=t)))
        acts = self.acts(inquire(2, node="A", tasks=t, resources={"SHORT_HORSE": 1}))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)


class EconomyIceBoxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = EconomyStrategy()

    def step(self, inq: dict) -> list:
        self.state.update_inquire(inq)
        return self.strategy.propose(self.state)

    def acts(self, inq: dict) -> list[dict]:
        return [a for it in self.step(inq) for a in it.actions]

    def test_claims_ice_box_en_route(self) -> None:
        nodes = [{"nodeId": "B", "resourceStock": {"ICE_BOX": 1}}]
        acts = self.acts(inquire(1, node="A", nodes=nodes))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)
        acts = self.acts(inquire(2, node="B", nodes=nodes))
        self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "B",
                           "resourceType": "ICE_BOX"}], acts)

    def test_no_claim_when_holding_enough(self) -> None:
        nodes = [{"nodeId": "B", "resourceStock": {"ICE_BOX": 1}}]
        acts = self.acts(inquire(1, node="A", nodes=nodes, resources={"ICE_BOX": 2}))
        self.assertNotIn("CLAIM_RESOURCE", [a["action"] for a in acts])

    def test_claims_ice_box_after_task_goal(self) -> None:
        # 任务分拿满只关任务候选，冰鉴领取不连坐（P3 修正：756 局停 S07
        # 脚下冰鉴 0 绕路却因整体闭嘴没领）
        nodes = [{"nodeId": "A", "resourceStock": {"ICE_BOX": 1}}]
        acts = self.acts(inquire(1, node="A", nodes=nodes, tasks=[task("T_1", "B")],
                                 task_score=TASK_SCORE_GOAL))
        self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "A",
                           "resourceType": "ICE_BOX"}], acts)

    def test_ice_en_route_claimed_before_task(self) -> None:
        # 一步前瞻：脚下的冰鉴先领（读条 2 帧），再去做前面的任务。
        # 单步贪心会因"前面总有更大的任务"而永远跳过顺路冰鉴（实测全场 0 领取）
        nodes = [{"nodeId": "B", "resourceStock": {"ICE_BOX": 1}}]
        t = [task("T_c", "C", score=30)]
        # 先在 B 完成固定处理（到站帧静默 → 处理受理）
        self.step(inquire(1, node="B", nodes=nodes, tasks=t))
        acts = self.acts(inquire(2, node="B", nodes=nodes, tasks=t,
                                 action_results=[{"round": 1, "playerId": MY_ID,
                                                  "action": "PROCESS", "accepted": True}]))
        self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "B",
                           "resourceType": "ICE_BOX"}], acts)

    def test_must_rush_silences_candidates_and_wait(self) -> None:
        # P4d 送达优先：A 到终点 17 帧，525+17+60 ≥ 600 触发全局硬闸。
        # 对照：经济层自身候选账（done≈543 ≤ 560）本会接受该任务，硬闸必须先行
        self.assertEqual([], self.acts(inquire(525, node="A", tasks=[task("T_1", "B")])))

    def test_must_rush_keeps_ice_use(self) -> None:
        # 硬闸只停候选/蹲守；冰鉴使用保交付有效性，保留
        acts = self.acts(inquire(525, node="A", freshness=81.5,
                                 resources={"ICE_BOX": 1}, tasks=[task("T_1", "B")]))
        self.assertIn({"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}, acts)
        self.assertNotIn("MOVE", [a["action"] for a in acts])

    def test_uses_ice_box_at_threshold(self) -> None:
        # freshness 81.5 ≤ 80+2：停靠即用；优先级 120 压过任务
        intents = self.step(inquire(1, node="A", freshness=81.5,
                                    resources={"ICE_BOX": 1}, tasks=[task("T_1", "B")]))
        use = [it for it in intents if it.actions[0]["action"] == "USE_RESOURCE"]
        self.assertEqual(1, len(use))
        self.assertEqual(PRIORITY_ICE_USE, use[0].priority)
        self.assertEqual({"action": "USE_RESOURCE", "resourceType": "ICE_BOX"},
                         use[0].actions[0])

    def test_no_use_far_from_threshold(self) -> None:
        # freshness 87、主线短边（损耗 ~0.17）不会跌破 80：不用
        acts = self.acts(inquire(1, node="A", freshness=87.0, resources={"ICE_BOX": 1}))
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_no_use_without_ice_box(self) -> None:
        acts = self.acts(inquire(1, node="A", freshness=81.5))
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_predictive_use_before_long_edge(self) -> None:
        # 大距离边 A→B（distance=50 → 69帧 → 损耗 ~3.8）：83.5 出发途中跌破 80 → 提前用
        start = {**START, "edges": [
            {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B", "routeType": "ROAD",
             "distance": 50, "bidirectional": True},
            {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C", "routeType": "ROAD",
             "distance": 2, "bidirectional": True},
            {"edgeId": "E3", "fromNodeId": "C", "toNodeId": "D", "routeType": "ROAD",
             "distance": 2, "bidirectional": True},
        ]}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        # 经济层静默（任务分已满）：用 delivery 下一跳（A→B）预判；83.5 - 3.8 < 80 → 用
        acts = self.acts(inquire(1, node="A", freshness=83.5, resources={"ICE_BOX": 1},
                                 task_score=TASK_SCORE_GOAL))
        self.assertIn({"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}, acts)

    def test_does_not_spend_ice_box_in_top_freshness_band(self) -> None:
        weather = {"active": [{"weatherId": "W1", "type": "HOT", "region": "ALL",
                               "remainRound": 20}]}
        acts = self.acts(inquire(1, node="A", freshness=94.5,
                                 resources={"ICE_BOX": 1}, weather=weather))
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_use_rejected_backs_off(self) -> None:
        self.acts(inquire(1, node="A", freshness=81.5, resources={"ICE_BOX": 1}))
        rej = [{"round": 1, "playerId": MY_ID, "action": "USE_RESOURCE",
                "accepted": False, "result": "ACTION_REJECTED",
                "errorCode": "RESOURCE_NOT_ENOUGH"}]
        acts = self.acts(inquire(2, node="A", freshness=81.5,
                                 resources={"ICE_BOX": 1}, action_results=rej))
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_ice_use_active_even_after_goal_and_in_rush(self) -> None:
        acts = self.acts(inquire(1, node="A", phase="RUSH", freshness=81.5,
                                 resources={"ICE_BOX": 1}, task_score=90))
        self.assertEqual([{"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}], acts)

    def test_hot_weather_uses_ice_box_earlier(self) -> None:
        weather = {"active": [{"weatherId": "W1", "type": "HOT", "region": "ALL",
                               "remainRound": 20}]}
        acts = self.acts(inquire(1, node="A", freshness=84.0,
                                 resources={"ICE_BOX": 1}, weather=weather))
        self.assertIn({"action": "USE_RESOURCE", "resourceType": "ICE_BOX"}, acts)


class EconomyGeneralResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = EconomyStrategy()

    def acts(self, inq: dict) -> list[dict]:
        self.state.update_inquire(inq)
        return [a for it in self.strategy.propose(self.state) for a in it.actions]

    def test_claims_active_resources_at_current_node(self) -> None:
        for resource_type in ("SHORT_HORSE", "FAST_HORSE"):
            with self.subTest(resource_type=resource_type):
                self.setUp()
                nodes = [{"nodeId": "B", "resourceStock": {resource_type: 1}}]
                acts = self.acts(inquire(1, node="B", nodes=nodes,
                                         task_score=TASK_SCORE_GOAL))
                self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "B",
                                   "resourceType": resource_type}], acts)

    def test_document_resource_claim_requires_open_contest(self) -> None:
        nodes = [{"nodeId": "B", "resourceStock": {"PASS_TOKEN": 1}}]
        acts = self.acts(inquire(1, node="B", nodes=nodes, task_score=TASK_SCORE_GOAL))
        self.assertNotIn("CLAIM_RESOURCE", [a["action"] for a in acts])

        contest = {"contestId": "C1", "contestType": "PASS", "targetNodeId": "B",
                   "redPlayerId": MY_ID, "bluePlayerId": OPP_ID}
        acts = self.acts(inquire(2, node="B", nodes=nodes, task_score=TASK_SCORE_GOAL,
                                 contests=[contest]))
        self.assertEqual([{"action": "CLAIM_RESOURCE", "targetNodeId": "B",
                           "resourceType": "PASS_TOKEN"}], acts)

    def test_document_resources_are_not_actively_used(self) -> None:
        acts = self.acts(inquire(1, node="A",
                                 resources={"PASS_TOKEN": 1, "OFFICIAL_PERMIT": 1},
                                 task_score=TASK_SCORE_GOAL))
        self.assertNotIn("USE_RESOURCE", [a["action"] for a in acts])

    def test_intel_is_used_on_current_gate_verify(self) -> None:
        acts = self.acts(inquire(1, node="C", phase="RUSH",
                                 resources={"INTEL": 1}, task_score=TASK_SCORE_GOAL))
        self.assertEqual([{"action": "USE_RESOURCE", "resourceType": "INTEL",
                           "targetNodeId": "C"}], acts)

    def test_intel_is_not_claimed_without_hard_requirement(self) -> None:
        nodes = [{"nodeId": "B", "resourceStock": {"INTEL": 1}}]
        acts = self.acts(inquire(1, node="B", nodes=nodes, task_score=TASK_SCORE_GOAL))
        self.assertNotIn("CLAIM_RESOURCE", [a["action"] for a in acts])

    def test_low_value_intel_is_not_claimed_by_detour(self) -> None:
        nodes = [{"nodeId": "E", "resourceStock": {"INTEL": 1}}]
        acts = self.acts(inquire(1, node="A", nodes=nodes, task_score=TASK_SCORE_GOAL))
        self.assertNotIn("CLAIM_RESOURCE", [a["action"] for a in acts])
        self.assertNotIn({"action": "MOVE", "targetNodeId": "B"}, acts)

    def test_required_resource_on_delivery_path_is_hard_need(self) -> None:
        start = {**START, "map": {"gameplay": {
            "roles": {"startNodeId": "A", "gateNodeId": "C", "terminalNodeIds": ["D"]},
            "processNodes": [
                {"nodeId": "C", "processType": "VERIFY", "processRound": 6,
                 "canWindow": True, "requiredResourceTypes": ["BOAT_RIGHT"]},
            ],
        }}}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        nodes = [{"nodeId": "E", "resourceStock": {"BOAT_RIGHT": 1}}]
        acts = self.acts(inquire(1, node="B", nodes=nodes, task_score=TASK_SCORE_GOAL))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "E"}], acts)

    def test_use_resource_whitelist_rejects_documents(self) -> None:
        with self.assertRaises(AssertionError):
            _use_resource_action("PASS_TOKEN")

    def test_uses_fast_horse_before_long_edge(self) -> None:
        start = {**START, "edges": [
            {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B", "routeType": "ROAD",
             "distance": 50, "bidirectional": True},
            {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C", "routeType": "ROAD",
             "distance": 2, "bidirectional": True},
            {"edgeId": "E3", "fromNodeId": "C", "toNodeId": "D", "routeType": "ROAD",
             "distance": 2, "bidirectional": True},
        ]}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        acts = self.acts(inquire(1, node="A", resources={"FAST_HORSE": 1},
                                 task_score=TASK_SCORE_GOAL))
        self.assertIn({"action": "USE_RESOURCE", "resourceType": "FAST_HORSE"}, acts)

    def test_horse_use_backs_off_after_rejection(self) -> None:
        self.test_uses_fast_horse_before_long_edge()
        rej = [{"round": 1, "playerId": MY_ID, "action": "USE_RESOURCE",
                "accepted": False, "result": "ACTION_REJECTED",
                "errorCode": "HORSE_BUFF_CONFLICT"}]
        acts = self.acts(inquire(2, node="A", resources={"FAST_HORSE": 1},
                                 task_score=TASK_SCORE_GOAL, action_results=rej))
        self.assertNotIn({"action": "USE_RESOURCE", "resourceType": "FAST_HORSE"}, acts)

    def test_does_not_use_horse_when_rush_speed_active(self) -> None:
        start = {**START, "edges": [
            {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B", "routeType": "ROAD",
             "distance": 50, "bidirectional": True},
            {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C", "routeType": "ROAD",
             "distance": 2, "bidirectional": True},
            {"edgeId": "E3", "fromNodeId": "C", "toNodeId": "D", "routeType": "ROAD",
             "distance": 2, "bidirectional": True},
        ]}
        self.state = GameState(MY_ID)
        self.state.update_start(start)
        acts = self.acts(inquire(1, node="A", resources={"FAST_HORSE": 1},
                                 task_score=TASK_SCORE_GOAL,
                                 buffs=[{"type": "RUSH_SPEED", "remainingRound": 5}]))
        self.assertNotIn({"action": "USE_RESOURCE", "resourceType": "FAST_HORSE"}, acts)


if __name__ == "__main__":
    unittest.main()
