"""DeliveryStrategy 状态机单测：合成小地图逐帧驱动。

地图：A(起点) → B(TRANSFER处理2帧) → C(宫门,VERIFY处理点) → D(终点)，全部 ROAD 双向。
宫门同时挂在 processNodes 里（真实地图 S14 即如此），用于覆盖"宫门绝不发 PROCESS"。
"""

import unittest

from lychee.state import GameState
from lychee.strategy.delivery import DeliveryStrategy

MY_ID = 1001

START = {
    "matchId": "m-test",
    "round": 1,
    "durationRound": 600,
    "players": [{"playerId": MY_ID, "teamId": "RED", "name": "t"},
                {"playerId": 2002, "teamId": "BLUE", "name": "o"}],
    "nodes": [
        {"nodeId": "A", "nodeType": "START", "start": True},
        {"nodeId": "B", "nodeType": "STATION"},
        {"nodeId": "C", "nodeType": "GATE"},
        {"nodeId": "D", "nodeType": "FINISH", "terminal": True},
    ],
    "edges": [
        {"edgeId": "E1", "fromNodeId": "A", "toNodeId": "B", "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E2", "fromNodeId": "B", "toNodeId": "C", "routeType": "ROAD", "distance": 2, "bidirectional": True},
        {"edgeId": "E3", "fromNodeId": "C", "toNodeId": "D", "routeType": "ROAD", "distance": 2, "bidirectional": True},
    ],
    "map": {"gameplay": {
        "roles": {"startNodeId": "A", "gateNodeId": "C", "terminalNodeIds": ["D"]},
        "processNodes": [
            {"nodeId": "B", "processType": "TRANSFER", "processRound": 2, "canWindow": True},
            {"nodeId": "C", "processType": "VERIFY", "processRound": 6, "canWindow": True},
        ],
    }},
}


def inquire(round_no: int, *, node: str = "A", state: str = "IDLE", phase: str = "NORMAL",
            verified: bool = False, process: dict | None = None, next_node: str | None = None,
            action_results: list | None = None, good_fruit: int = 90, freshness: float = 80.0) -> dict:
    return {
        "round": round_no, "phase": phase,
        "players": [{"playerId": MY_ID, "teamId": "RED", "state": state,
                     "currentNodeId": node, "nextNodeId": next_node,
                     "currentProcess": process, "verified": verified,
                     "goodFruit": good_fruit, "freshness": freshness}],
        "actionResults": action_results or [],
    }


class DeliveryStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = GameState(MY_ID)
        self.state.update_start(START)
        self.strategy = DeliveryStrategy()

    def step(self, inq: dict) -> list[dict]:
        self.state.update_inquire(inq)
        intents = self.strategy.propose(self.state)
        return [a for it in intents for a in it.actions]

    def test_full_delivery_flow(self) -> None:
        # 起点：直接向 B 移动
        acts = self.step(inquire(1, node="A"))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)
        # 移动中：心跳
        self.assertEqual([], self.step(inquire(2, node="A", state="MOVING", next_node="B")))
        # 到达处理站点 B：提交 PROCESS
        acts = self.step(inquire(3, node="B"))
        self.assertEqual([{"action": "PROCESS", "targetNodeId": "B"}], acts)
        # 读条中：心跳
        proc = {"action": "PROCESS", "targetNodeId": "B", "remainRound": 1}
        self.assertEqual([], self.step(inquire(4, node="B", state="PROCESSING", process=proc)))
        # 读条结束仍在 B：处理完成 → 继续移动向 C
        acts = self.step(inquire(5, node="B"))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "C"}], acts)
        # 到宫门 C，NORMAL 阶段：等待
        self.assertEqual([], self.step(inquire(6, node="C")))
        # RUSH 阶段：提交验核
        acts = self.step(inquire(7, node="C", phase="RUSH"))
        self.assertEqual([{"action": "VERIFY_GATE"}], acts)
        # 验核读条中：心跳
        vproc = {"action": "VERIFY_GATE", "targetNodeId": "C", "remainRound": 3}
        self.assertEqual([], self.step(inquire(8, node="C", phase="RUSH", process=vproc)))
        # 验核完成：移动向终点 D
        acts = self.step(inquire(9, node="C", phase="RUSH", verified=True))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "D"}], acts)
        # 到终点已验核：交付
        acts = self.step(inquire(10, node="D", phase="RUSH", verified=True))
        self.assertEqual([{"action": "DELIVER"}], acts)

    def test_no_deliver_without_fruit_or_freshness(self) -> None:
        self.assertEqual([], self.step(inquire(1, node="D", verified=True, good_fruit=0)))
        self.assertEqual([], self.step(inquire(2, node="D", verified=True, freshness=0.0)))

    def _trap_inquire(self, round_no: int, *, opp_node: str, opp_next: str = "",
                      opp_ap: int = 4) -> dict:
        inq = inquire(round_no, node="A")
        inq["players"][0]["squadAvailable"] = 0
        inq["players"].append({"playerId": 2002, "teamId": "BLUE", "state": "IDLE",
                               "currentNodeId": opp_node, "nextNodeId": opp_next,
                               "guardActionPoint": opp_ap})
        return inq

    def test_holds_move_while_opponent_squats_choke(self) -> None:
        # 防陷阱闸门（P4e）：对手停在咽喉 B 且可设卡、我方无小分队 → 本帧不进边
        self.assertEqual([], self.step(self._trap_inquire(20, opp_node="B")))
        # 对手离站上边（B→C 半路）→ 恢复移动
        acts = self.step(self._trap_inquire(21, opp_node="B", opp_next="C"))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "B"}], acts)

    def test_delivered_goes_quiet(self) -> None:
        inq = inquire(1, node="D", verified=True)
        inq["players"][0]["delivered"] = True
        self.assertEqual([], self.step(inq))

    def test_gate_process_not_reissued_when_verified(self) -> None:
        # 已验核路过宫门：不再验核，直接走
        acts = self.step(inquire(1, node="C", phase="RUSH", verified=True))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "D"}], acts)

    def test_revisit_process_node_reprocesses(self) -> None:
        # 第一次经过 B 处理完成
        self.step(inquire(1, node="B"))
        proc = {"action": "PROCESS", "targetNodeId": "B", "remainRound": 1}
        self.step(inquire(2, node="B", state="PROCESSING", process=proc))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "C"}],
                         self.step(inquire(3, node="B")))
        # 离开又回来：需要重新处理
        self.step(inquire(4, node="C"))
        acts = self.step(inquire(5, node="B"))
        self.assertEqual([{"action": "PROCESS", "targetNodeId": "B"}], acts)

    def test_move_rejected_repeatedly_triggers_detour(self) -> None:
        # 无替代路线的小图上：连续被拒后仍会回到原目标（绕行失败即硬闯），不崩溃
        self.step(inquire(1, node="A"))
        for n in range(2, 9):
            rej = [{"round": n - 1, "playerId": MY_ID, "action": "MOVE",
                    "accepted": False, "result": "ACTION_REJECTED",
                    "errorCode": "MOVE_BLOCKED_BY_GUARD"}]
            acts = self.step(inquire(n, node="A", action_results=rej))
            self.assertEqual(1, len(acts))
            self.assertEqual("MOVE", acts[0]["action"])

    def test_process_rejected_retries(self) -> None:
        self.step(inquire(1, node="B"))  # 发出 PROCESS
        rej = [{"round": 1, "playerId": MY_ID, "action": "PROCESS",
                "accepted": False, "result": "ACTION_REJECTED", "errorCode": "OBJECT_BUSY"}]
        acts = self.step(inquire(2, node="B", action_results=rej))
        self.assertEqual([{"action": "PROCESS", "targetNodeId": "B"}], acts)

    def test_gate_never_receives_process(self) -> None:
        # 宫门挂在 processNodes（VERIFY 型）：验核完成极快、从未观察到读条时，
        # 也绝不能对宫门发 PROCESS（会被拒并卡死在宫门）
        acts = self.step(inquire(1, node="C", phase="RUSH"))
        self.assertEqual([{"action": "VERIFY_GATE"}], acts)
        acts = self.step(inquire(2, node="C", phase="RUSH", verified=True))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "D"}], acts)

    def test_one_frame_process_completes_via_accepted_result(self) -> None:
        # 处理帧数极短（变体地图 processRound=1）：观察不到 currentProcess，
        # 靠上一帧 PROCESS 受理结果推断完成，不得反复重发 PROCESS
        self.step(inquire(1, node="B"))  # 发出 PROCESS
        ok = [{"round": 1, "playerId": MY_ID, "action": "PROCESS",
               "accepted": True, "result": "SUCCESS"}]
        acts = self.step(inquire(2, node="B", action_results=ok))
        self.assertEqual([{"action": "MOVE", "targetNodeId": "C"}], acts)

    def test_interrupted_process_redone_after_move_reject(self) -> None:
        # 读条被窗口争夺打断（任务书 4.3 进度清零）：完成推断会误判 →
        # 靠 MOVE 被拒（PROCESS_REQUIRED）纠偏，重新处理
        self.step(inquire(1, node="B"))
        proc = {"action": "PROCESS", "targetNodeId": "B", "remainRound": 3}
        self.step(inquire(2, node="B", state="PROCESSING", process=proc))
        # 读条消失但处理未完成 → 误判完成发 MOVE（预期内）
        acts = self.step(inquire(3, node="B"))
        self.assertEqual("MOVE", acts[0]["action"])
        rej = [{"round": 3, "playerId": MY_ID, "action": "MOVE",
                "accepted": False, "result": "ACTION_REJECTED",
                "errorCode": "PROCESS_REQUIRED"}]
        acts = self.step(inquire(4, node="B", action_results=rej))
        self.assertEqual([{"action": "PROCESS", "targetNodeId": "B"}], acts)

    def test_guard_block_at_processed_station_keeps_moving(self) -> None:
        # 已处理完的站点上 MOVE 被设卡拒绝（拒因在目标侧）：
        # 不得重置处理簿记去白费几帧重处理，应继续 MOVE 并累计绕行计数
        self.step(inquire(1, node="B"))
        proc = {"action": "PROCESS", "targetNodeId": "B", "remainRound": 1}
        self.step(inquire(2, node="B", state="PROCESSING", process=proc))
        self.assertEqual("MOVE", self.step(inquire(3, node="B"))[0]["action"])
        for n in range(4, 10):
            rej = [{"round": n - 1, "playerId": MY_ID, "action": "MOVE",
                    "accepted": False, "result": "ACTION_REJECTED",
                    "errorCode": "MOVE_BLOCKED_BY_GUARD"}]
            acts = self.step(inquire(n, node="B", action_results=rej))
            self.assertEqual(1, len(acts))
            self.assertEqual("MOVE", acts[0]["action"])

    def test_economy_process_not_mistaken_for_station_process(self) -> None:
        # 站点 B 上出现资源领取读条（P2 经济层会有）：不算固定处理证据，
        # 读条结束后仍须提交 PROCESS
        self.step(inquire(1, node="B"))
        claim = {"action": "CLAIM_RESOURCE", "objectKey": "RESOURCE:B:ICE_BOX",
                 "resourceType": "ICE_BOX", "remainRound": 1}
        rej = [{"round": 1, "playerId": MY_ID, "action": "PROCESS",
                "accepted": False, "result": "ACTION_REJECTED", "errorCode": "OBJECT_BUSY"}]
        self.assertEqual([], self.step(inquire(2, node="B", state="PROCESSING",
                                               process=claim, action_results=rej)))
        acts = self.step(inquire(3, node="B"))
        self.assertEqual([{"action": "PROCESS", "targetNodeId": "B"}], acts)


if __name__ == "__main__":
    unittest.main()
