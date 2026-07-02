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


if __name__ == "__main__":
    unittest.main()
