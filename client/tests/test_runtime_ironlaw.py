"""铁律层单测：策略无论怎么作死，每帧 inquire 必有 round 匹配的 action 回包。

不碰 socket：用 FakeConn 喂录制格式的消息序列（架构文档第三.4 节可测试性要求）。
"""

import json
import unittest
from collections import deque

from lychee.recorder import Recorder
from lychee.runtime import Runtime
from lychee.strategy import Intent, NoopStrategy, Strategy


class FakeConn:
    def __init__(self, incoming: list[dict]) -> None:
        self.incoming = deque(incoming)
        self.sent: list[dict] = []

    def read(self) -> dict:
        if not self.incoming:
            raise EOFError("no more messages")
        return self.incoming.popleft()

    def write(self, message: dict) -> None:
        json.dumps(message, ensure_ascii=False)  # 模拟真实序列化：非法内容同样抛 TypeError
        self.sent.append(message)


class CrashingStrategy(Strategy):
    def propose(self, state):
        raise RuntimeError("策略炸了")


class UnserializableStrategy(Strategy):
    def propose(self, state):
        return [Intent(kind="bad", priority=1, actions=[{"action": object()}])]


def make_messages(frames: int) -> list[dict]:
    msgs = [{"msg_name": "start", "msg_data": {"matchId": "m1", "round": 1}}]
    for n in range(1, frames + 1):
        msgs.append({"msg_name": "inquire", "msg_data": {"round": n}})
    msgs.append({"msg_name": "over", "msg_data": {"round": frames, "players": []}})
    return msgs


def run_with(strategy: Strategy, messages: list[dict]) -> FakeConn:
    conn = FakeConn(messages)
    rt = Runtime(conn, player_id=1001, player_name="t", version="0",
                 strategies=[strategy], recorder=Recorder.disabled())
    assert rt.run() == 0
    return conn


class IronLawTests(unittest.TestCase):
    def assert_one_action_per_round(self, conn: FakeConn, frames: int) -> None:
        actions = [m for m in conn.sent if m["msg_name"] == "action"]
        self.assertEqual(frames, len(actions))
        for n, msg in enumerate(actions, start=1):
            self.assertEqual(n, msg["msg_data"]["round"])
            self.assertEqual("m1", msg["msg_data"]["matchId"])

    def test_noop_strategy_answers_every_frame(self) -> None:
        conn = run_with(NoopStrategy(), make_messages(600))
        self.assertEqual("registration", conn.sent[0]["msg_name"])
        self.assertEqual("ready", conn.sent[1]["msg_name"])
        self.assert_one_action_per_round(conn, 600)

    def test_crashing_strategy_falls_back_to_heartbeat(self) -> None:
        conn = run_with(CrashingStrategy(), make_messages(600))
        actions = [m for m in conn.sent if m["msg_name"] == "action"]
        self.assertEqual(600, len(actions))
        self.assertTrue(all(m["msg_data"]["actions"] == [] for m in actions))

    def test_unserializable_action_falls_back_to_heartbeat(self) -> None:
        conn = run_with(UnserializableStrategy(), make_messages(3))
        self.assert_one_action_per_round(conn, 3)
        actions = [m for m in conn.sent if m["msg_name"] == "action"]
        self.assertTrue(all(m["msg_data"]["actions"] == [] for m in actions))

    def test_error_message_does_not_kill_loop(self) -> None:
        msgs = make_messages(2)
        msgs.insert(2, {"msg_name": "error",
                        "msg_data": {"round": 1, "errorCode": "ACTION_TOO_LATE", "message": "x"}})
        conn = run_with(NoopStrategy(), msgs)
        self.assert_one_action_per_round(conn, 2)

    def test_malformed_message_does_not_kill_loop(self) -> None:
        msgs = make_messages(2)
        msgs.insert(2, {"msg_name": "inquire"})          # 没有 msg_data
        msgs.insert(3, {"whatever": True})               # 没有 msg_name
        conn = run_with(NoopStrategy(), msgs)
        self.assert_one_action_per_round(conn, 2)


class CardStrategy(Strategy):
    def propose(self, state):
        return [Intent(kind="w", priority=1, actions=[
            {"action": "WINDOW_CARD", "contestId": "C1", "card": "BING_ZHENG"}])]


class CardFieldFallbackTests(unittest.TestCase):
    """本地裁判旧 schema（cardType）自适应：空 error 紧跟含牌发包 → 一次性切换。"""

    def setUp(self) -> None:
        from lychee import protocol
        protocol.reset_card_field()

    tearDown = setUp

    @staticmethod
    def _cards(conn: FakeConn) -> list[dict]:
        return [a for m in conn.sent if m["msg_name"] == "action"
                for a in m["msg_data"]["actions"] if a.get("action") == "WINDOW_CARD"]

    def test_empty_error_after_card_switches_to_card_type(self) -> None:
        msgs = make_messages(2)
        msgs.insert(2, {"msg_name": "error", "msg_data": {}})   # 本地裁判空回执
        conn = run_with(CardStrategy(), msgs)
        cards = self._cards(conn)
        self.assertEqual(2, len(cards))
        self.assertIn("card", cards[0])            # 第 1 帧仍是现网格式
        self.assertNotIn("card", cards[1])         # error 后切换旧 schema
        self.assertEqual("BING_ZHENG", cards[1]["cardType"])

    def test_error_with_fields_keeps_live_format(self) -> None:
        # 现网 error 带字段（如 ACTION_TOO_LATE）：不触发切换
        msgs = make_messages(2)
        msgs.insert(2, {"msg_name": "error",
                        "msg_data": {"round": 1, "errorCode": "ACTION_TOO_LATE"}})
        conn = run_with(CardStrategy(), msgs)
        self.assertTrue(all("card" in c for c in self._cards(conn)))

    def test_empty_error_without_card_send_keeps_live_format(self) -> None:
        msgs = make_messages(2)
        msgs.insert(2, {"msg_name": "error", "msg_data": {}})
        conn = run_with(NoopStrategy(), msgs)      # 从未发过牌 → 不切换
        from lychee import protocol
        self.assertEqual("card", protocol.window_card_field())
        self.assertEqual(2, len([m for m in conn.sent if m["msg_name"] == "action"]))


if __name__ == "__main__":
    unittest.main()
