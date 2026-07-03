"""拦截封锁流集成测试：真实样例地图上验证"对手上钩→冻结"的完整决策链。

装配与 main.py 一致（[CombatStrategy(economy), DeliveryStrategy(), economy] 经 arbiter
合并）。设计文档 §5 触发时序的端到端复现——单元测试证明各零件，这里证明它们串起来
在真实咽喉 S10（KEY_PASS）上把 commit 上边的对手冻死。
"""

import json
import unittest
from pathlib import Path

from lychee import arbiter
from lychee.state import GameState
from lychee.strategy.combat import CombatStrategy
from lychee.strategy.delivery import DeliveryStrategy
from lychee.strategy.economy import EconomyStrategy

REFS = Path(__file__).resolve().parents[2] / "refs" / "debug-kit-v1"
MY_ID = 1001
OPP_ID = 2002


def make_state() -> GameState:
    with open(REFS / "start消息.json", encoding="utf-8") as f:
        data = json.load(f)["msg_data"]
    # start 样例里两名玩家都不是 1001/2002 时也无妨：显式给双方 id/teamId
    data["players"] = [{"playerId": MY_ID, "teamId": "RED", "name": "me"},
                       {"playerId": OPP_ID, "teamId": "BLUE", "name": "op"}]
    state = GameState(MY_ID)
    state.update_start(data)
    return state


def inquire(*, round_no: int, opp_committed: bool) -> dict:
    """我 camp 在 S10；opp_committed=True 时对手已上 S09→S10 边（MOVING、剩余充裕）。"""
    opp = {"playerId": OPP_ID, "teamId": "BLUE", "currentNodeId": "S09"}
    if opp_committed:
        opp.update({"state": "MOVING", "nextNodeId": "S10",
                    "edgeProgressMs": 0, "edgeTotalMs": 55200})   # 剩余 ~56 帧
    else:
        opp.update({"state": "IDLE"})
    return {
        "round": round_no, "phase": "NORMAL",
        "players": [
            {"playerId": MY_ID, "teamId": "RED", "state": "IDLE",
             "currentNodeId": "S10", "nextNodeId": "", "verified": False,
             "goodFruit": 90, "badFruit": 2, "freshness": 85.0,
             "squadAvailable": 8, "guardActionPoint": 4},
            opp,
        ],
        "nodes": [], "contests": [], "events": [], "tasks": [],
    }


class InterceptionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = make_state()
        self.economy = EconomyStrategy()
        self.strategies = [CombatStrategy(economy=self.economy),
                           DeliveryStrategy(), self.economy]

    def actions(self, inq: dict) -> list[dict]:
        self.state.update_inquire(inq)
        intents: list = []
        for strat in self.strategies:
            intents.extend(strat.propose(self.state) or [])
        return arbiter.merge_intents(intents, self.state.me)

    def test_freezes_opponent_on_commit(self) -> None:
        # 对手 commit 上 S09→S10 边 → 整栈合并输出在 S10 设满防卡（把他冻死半路）
        acts = self.actions(inquire(round_no=200, opp_committed=True))
        self.assertIn({"action": "SET_GUARD", "targetNodeId": "S10", "extraGoodFruit": 2}, acts)
        # camp 生效：不发离开 S10 的 MOVE
        self.assertNotIn("MOVE", [a.get("action") for a in acts])

    def test_camps_without_guard_before_commit(self) -> None:
        # 对手还停在 S09 未上边：继续 camp（不走位），但不早设卡（等他 commit）
        acts = self.actions(inquire(round_no=200, opp_committed=False))
        self.assertNotIn("SET_GUARD", [a.get("action") for a in acts])
        self.assertNotIn("MOVE", [a.get("action") for a in acts])


if __name__ == "__main__":
    unittest.main()
