"""Record each round's server inquire (both sides' full state) to a JSONL file.

One match -> one file. Each inquire message already carries both players'
state, tasks, contests, events, action results and score preview, so the file
is a complete replay of the round-by-round match from the public view.
"""
import json
import os
import time
from typing import Any, Optional

# The `debug` block mirrors the whole payload again in client-debug mode; drop it
# so the file stays about half the size without losing any real information.
_TRIM_KEYS = ("debug",)


class MatchRecorder:
    def __init__(self, out_dir: str, player_id: int) -> None:
        self.out_dir = out_dir
        self.player_id = player_id
        self._fh = None
        self._path: Optional[str] = None
        self._rounds = 0

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def rounds(self) -> int:
        return self._rounds

    def _ensure_open(self, match_id: str) -> None:
        if self._fh is not None:
            return
        os.makedirs(self.out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe = (match_id or "match").replace("/", "_").replace("\\", "_")
        self._path = os.path.join(self.out_dir, f"{safe}_{self.player_id}_{stamp}.jsonl")
        self._fh = open(self._path, "w", encoding="utf-8")
        self._write({"kind": "meta", "playerId": self.player_id, "matchId": match_id})

    def _write(self, obj: dict[str, Any]) -> None:
        assert self._fh is not None
        self._fh.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._fh.flush()

    def record_inquire(self, data: dict[str, Any]) -> None:
        self._ensure_open(data.get("matchId", ""))
        rec = {k: v for k, v in data.items() if k not in _TRIM_KEYS}
        rec["kind"] = "inquire"
        self._write(rec)
        self._rounds += 1

    def record_over(self, data: dict[str, Any]) -> None:
        # `over` carries the authoritative final scores for both sides; the
        # in-match inquire previews only credit delivery/task points on delivery.
        self._ensure_open(data.get("matchId", ""))
        rec = dict(data)
        rec["kind"] = "over"
        self._write(rec)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
