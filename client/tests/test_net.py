"""framing 单测。运行方式（cwd = client/）：python -m unittest discover -s tests"""

import socket
import unittest

from lychee.net import read_frame, write_frame


class FramingTests(unittest.TestCase):
    def test_write_and_read_frame(self) -> None:
        left, right = socket.socketpair()
        try:
            write_frame(left, {"msg_name": "ping"})
            self.assertEqual({"msg_name": "ping"}, read_frame(right))
        finally:
            left.close()
            right.close()

    def test_sticky_frames_read_in_order(self) -> None:
        """粘包：一次性写入两帧，接收方按长度前缀依次拆出。"""
        left, right = socket.socketpair()
        try:
            write_frame(left, {"msg_name": "a", "msg_data": {"round": 1}})
            write_frame(left, {"msg_name": "b", "msg_data": {"中文": "跨包也要完整解码"}})
            self.assertEqual("a", read_frame(right)["msg_name"])
            second = read_frame(right)
            self.assertEqual("b", second["msg_name"])
            self.assertEqual("跨包也要完整解码", second["msg_data"]["中文"])
        finally:
            left.close()
            right.close()

    def test_partial_frame_is_buffered(self) -> None:
        """半包：body 分两段到达，read_frame 收齐才返回。"""
        left, right = socket.socketpair()
        try:
            import json
            body = json.dumps({"msg_name": "x"}).encode("utf-8")
            frame = f"{len(body):05d}".encode("ascii") + body
            left.sendall(frame[:7])
            left.sendall(frame[7:])
            self.assertEqual({"msg_name": "x"}, read_frame(right))
        finally:
            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()
