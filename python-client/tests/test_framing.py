import json
import os
import socket
import tempfile
import unittest

from lychee_basic_client.framing import DIAGNOSTIC_ENV, FrameDecodeError, read_frame, write_frame


class FramingTests(unittest.TestCase):
    def test_write_and_read_frame(self) -> None:
        left, right = socket.socketpair()
        try:
            write_frame(left, {"msg_name": "ping"})
            self.assertEqual({"msg_name": "ping"}, read_frame(right))
        finally:
            left.close()
            right.close()

    def test_malformed_json_frame_writes_diagnostic(self) -> None:
        left, right = socket.socketpair()
        with tempfile.TemporaryDirectory() as tmpdir:
            diagnostic_path = os.path.join(tmpdir, "frames.jsonl")
            old_path = os.environ.get(DIAGNOSTIC_ENV)
            os.environ[DIAGNOSTIC_ENV] = diagnostic_path
            try:
                body = b'{"msg_name":"inquire",{bad'
                left.sendall(f"{len(body):05d}".encode("ascii") + body)

                with self.assertRaises(FrameDecodeError) as raised:
                    read_frame(right)

                self.assertEqual(diagnostic_path, raised.exception.diagnostic_path)
                with open(diagnostic_path, encoding="utf-8") as file:
                    record = json.loads(file.readline())
                self.assertEqual("invalid_json", record["reason"])
                self.assertEqual(len(body), record["declaredLength"])
                self.assertIn("{bad", record["bodyHead"])
            finally:
                if old_path is None:
                    os.environ.pop(DIAGNOSTIC_ENV, None)
                else:
                    os.environ[DIAGNOSTIC_ENV] = old_path
                left.close()
                right.close()


if __name__ == "__main__":
    unittest.main()
