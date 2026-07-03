"""每帧收发落盘 jsonl：复盘 + 回归测试数据源。

铁律：录制绝不能影响比赛——任何 IO 异常吞掉并自动停用。
环境变量：LYCHEE_RECORD=0 关闭；LYCHEE_RECORD_DIR 指定输出目录（默认 client/logs/）；
LYCHEE_RECORD_FULL=1 关闭瘦身、写原始报文（排查服务端新字段时用）。

瘦身（默认开启，仅作用于 recv inquire，不改 start/over/error/send）：
- 丢弃 msg_data.debug：本地调试专用，近乎完整复制 players/nodes/events/tasks 等，
  state.update_inquire 从不读取，约占每帧一半体积。
- 丢弃 msg_data.edges：静态地图边，每帧重复且与 start 完全一致；state.update_inquire
  缺失时按协议第 7 章回退 start.edges，重放零影响。
- 削减 nodes[] 静态字段（x/y/name/nodeType/start/terminal/visible/resourceVisible）：
  NodeState.from_dict 只读动态字段（guard/resourceStock/hasObstacle/计数等），
  静态属性以 start.Node 为准（见 state.py 契约），保留所有动态及未知新字段。
"""

import json
import os
import time
from pathlib import Path


# inquire.nodes[] 中纯静态、由 start.Node 承载的字段；其余（含未来新增动态字段）保留
_NODE_STATIC_KEYS = frozenset((
    "x", "y", "name", "nodeType", "start", "terminal", "visible", "resourceVisible",
))


def _slim_inquire(data: dict) -> dict:
    """剔除 inquire msg_data 中的冗余块，返回新 dict（不改动原消息）。"""
    out = {k: v for k, v in data.items() if k not in ("debug", "edges")}
    nodes = out.get("nodes")
    if isinstance(nodes, list):
        out["nodes"] = [
            {k: v for k, v in nd.items() if k not in _NODE_STATIC_KEYS}
            for nd in nodes if isinstance(nd, dict)
        ]
    return out


class Recorder:
    def __init__(self, path: Path) -> None:
        self._file = None
        self._full = False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8")
        except OSError:
            self._file = None

    @classmethod
    def disabled(cls) -> "Recorder":
        rec = cls.__new__(cls)
        rec._file = None
        rec._full = False
        return rec

    @classmethod
    def from_env(cls, player_id: int) -> "Recorder":
        if os.environ.get("LYCHEE_RECORD", "1") == "0":
            return cls.disabled()
        base = os.environ.get("LYCHEE_RECORD_DIR")
        directory = Path(base) if base else Path(__file__).resolve().parent.parent / "logs"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        rec = cls(directory / f"match_{player_id}_{stamp}.jsonl")
        rec._full = os.environ.get("LYCHEE_RECORD_FULL", "0") == "1"
        return rec

    def recv(self, message: dict) -> None:
        self._write("recv", message)

    def send(self, message: dict) -> None:
        self._write("send", message)

    def _write(self, direction: str, message: dict) -> None:
        if self._file is None:
            return
        try:
            out = message
            if (not self._full) and direction == "recv" and message.get("msg_name") == "inquire":
                data = message.get("msg_data")
                if isinstance(data, dict):
                    out = dict(message)
                    out["msg_data"] = _slim_inquire(data)
            line = json.dumps({"t": time.time(), "dir": direction, "msg": out},
                              ensure_ascii=False, separators=(",", ":"))
            self._file.write(line + "\n")
            self._file.flush()
        except (OSError, TypeError, ValueError):
            self._file = None  # 录制出错即停用，比赛继续
