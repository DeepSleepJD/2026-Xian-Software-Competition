"""每帧收发落盘 jsonl：复盘 + 回归测试数据源。

铁律：录制绝不能影响比赛——任何 IO 异常吞掉并自动停用。
环境变量：LYCHEE_RECORD=0 关闭；LYCHEE_RECORD_DIR 指定输出目录（默认 client/logs/）。
"""

import json
import os
import time
from pathlib import Path


class Recorder:
    def __init__(self, path: Path) -> None:
        self._file = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8")
        except OSError:
            self._file = None

    @classmethod
    def disabled(cls) -> "Recorder":
        rec = cls.__new__(cls)
        rec._file = None
        return rec

    @classmethod
    def from_env(cls, player_id: int) -> "Recorder":
        if os.environ.get("LYCHEE_RECORD", "1") == "0":
            return cls.disabled()
        base = os.environ.get("LYCHEE_RECORD_DIR")
        directory = Path(base) if base else Path(__file__).resolve().parent.parent / "logs"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return cls(directory / f"match_{player_id}_{stamp}.jsonl")

    def recv(self, message: dict) -> None:
        self._write("recv", message)

    def send(self, message: dict) -> None:
        self._write("send", message)

    def _write(self, direction: str, message: dict) -> None:
        if self._file is None:
            return
        try:
            line = json.dumps({"t": time.time(), "dir": direction, "msg": message},
                              ensure_ascii=False, separators=(",", ":"))
            self._file.write(line + "\n")
            self._file.flush()
        except (OSError, TypeError, ValueError):
            self._file = None  # 录制出错即停用，比赛继续
