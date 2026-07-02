import contextlib
import io
import os
import socket
import tempfile
import unittest

from lychee_basic_client.config import Config
from lychee_basic_client.framing import DIAGNOSTIC_ENV, write_frame
from lychee_basic_client.session import ClientSession


class ClientSessionTests(unittest.TestCase):
    def test_session_skips_single_malformed_frame_and_continues(self) -> None:
        client, server = socket.socketpair()
        with tempfile.TemporaryDirectory() as tmpdir:
            diagnostic_path = os.path.join(tmpdir, "frames.jsonl")
            old_path = os.environ.get(DIAGNOSTIC_ENV)
            os.environ[DIAGNOSTIC_ENV] = diagnostic_path
            try:
                body = b'{"msg_name":"inquire",{bad'
                server.sendall(f"{len(body):05d}".encode("ascii") + body)
                write_frame(server, {"msg_name": "over", "msg_data": {}})

                config = Config(
                    host="127.0.0.1",
                    port=30000,
                    player_id=1001,
                    player_name="codex-py",
                    version="0.1",
                )
                stderr = io.StringIO()
                stdout = io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                    result = ClientSession(client, config).run()

                self.assertEqual(0, result)
                self.assertIn("malformed frame skipped", stderr.getvalue())
                self.assertTrue(os.path.exists(diagnostic_path))
            finally:
                if old_path is None:
                    os.environ.pop(DIAGNOSTIC_ENV, None)
                else:
                    os.environ[DIAGNOSTIC_ENV] = old_path
                client.close()
                server.close()


if __name__ == "__main__":
    unittest.main()
