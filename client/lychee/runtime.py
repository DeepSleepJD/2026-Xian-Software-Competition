"""主循环 + 铁律兜底。此文件写完锁定，策略开发不碰它。

铁律（违反即输，见 CLAUDE.md / 架构文档第三.3 节）：
1. 每帧必回 action：策略层抛异常、超预算 → 发空 actions 心跳。
2. action.round 恒等于当前 inquire.round。
3. error 消息不致命：记录后继续等下一帧（包没进结算 ≠ 比赛结束）。
4. over / EOF 优雅退出。

实现方式：单线程同步收发 + 每帧时间预算检查（默认 400ms，LYCHEE_BUDGET_MS 可调）。
不用看门狗线程——避免竞态复杂度，策略计算本身必须有界（design.md 补充决策）。
"""

import os
import sys
import time
import traceback

from . import arbiter, protocol
from .recorder import Recorder
from .state import GameState
from .strategy import Strategy

DEFAULT_BUDGET_MS = 400


def _log(text: str) -> None:
    print(text, flush=True)


class Runtime:
    def __init__(self, conn, player_id: int, player_name: str, version: str,
                 strategies: list[Strategy], recorder: Recorder) -> None:
        self._conn = conn
        self._player_id = player_id
        self._player_name = player_name
        self._version = version
        self._strategies = strategies
        self._recorder = recorder
        self._state = GameState(player_id)
        self._match_id = ""
        self._budget_sec = int(os.environ.get("LYCHEE_BUDGET_MS", DEFAULT_BUDGET_MS)) / 1000.0
        self._error_count = 0

    def run(self) -> int:
        self._send(protocol.build_registration(self._player_id, self._player_name, self._version))
        while True:
            try:
                message = self._conn.read()
            except EOFError:
                _log("连接被服务端关闭，退出")
                return 0
            except OSError as exc:
                _log(f"连接异常退出: {exc}")
                return 1
            self._recorder.recv(message)

            # 消息分发全程护栏：任何单条消息处理失败都不允许终结主循环
            try:
                result = self._dispatch(message)
            except Exception:
                _log(f"消息处理异常（已兜底继续）:\n{traceback.format_exc()}")
                result = None
            if result is not None:
                return result

    def _dispatch(self, message: dict) -> int | None:
        name, data = protocol.parse_message(message)
        if name == protocol.MSG_INQUIRE:
            self._on_inquire(data)
        elif name == protocol.MSG_START:
            self._on_start(data)
        elif name == protocol.MSG_OVER:
            self._on_over(data)
            return 0
        elif name == protocol.MSG_ERROR:
            self._error_count += 1
            _log(f"收到 error（第{self._error_count}次，继续比赛）: "
                 f"code={data.get('errorCode')} round={data.get('round')} msg={data.get('message')}")
        else:
            _log(f"忽略未知消息: msg_name={name!r}")
        return None

    def _on_start(self, data: dict) -> None:
        self._state.update_start(data)
        self._match_id = self._state.match_id
        round_no = data.get("round", 1)
        _log(f"start: match={self._match_id} round={round_no} player={self._player_id}")
        self._send(protocol.build_ready(self._match_id, round_no, self._player_id))

    def _on_inquire(self, data: dict) -> None:
        deadline = time.monotonic() + self._budget_sec
        round_no = data.get("round")
        if not isinstance(round_no, int):
            _log(f"inquire 缺 round 字段，无法响应本帧: {data.keys()}")
            return
        actions = self._compute_actions(data, deadline)
        message = protocol.build_action(self._match_id, round_no, self._player_id, actions)
        try:
            self._send(message)
        except (TypeError, ValueError):
            # 策略产出无法序列化等构造问题 → 退回空心跳；网络错误则外层 OSError 自然终止
            _log(f"action 构造/序列化失败（已退回心跳）:\n{traceback.format_exc()}")
            self._send(protocol.build_action(self._match_id, round_no, self._player_id, []))

    def _compute_actions(self, data: dict, deadline: float) -> list[dict]:
        """策略计算全程护栏：异常或超预算 → 空 actions。"""
        try:
            self._state.update_inquire(data)
            intents = []
            for strategy in self._strategies:
                if time.monotonic() >= deadline:
                    _log(f"round={self._state.round} 策略计算超预算，跳过剩余策略发已得意图")
                    break
                intents.extend(strategy.propose(self._state) or [])
            return arbiter.merge_intents(intents, self._state.me)
        except Exception:
            _log(f"round={self._state.round} 策略异常（已兜底空心跳）:\n{traceback.format_exc()}")
            return []

    def _on_over(self, data: dict) -> None:
        players = data.get("players") or []
        summary = ", ".join(f"{p.get('playerId')}:{p.get('totalScore')}"
                            for p in players if isinstance(p, dict))
        _log(f"over: overRound={data.get('overRound')} resultType={data.get('resultType')} "
             f"reason={data.get('overReason')} winner={data.get('winnerPlayerId')} 总分[{summary}]")
        for p in players:
            if isinstance(p, dict) and p.get("playerId") == self._player_id:
                _log(f"我方结算: online={p.get('online')} delivered={p.get('delivered')} "
                     f"deliverRound={p.get('deliverRound')} scoreDetail={p.get('scoreDetail')}")

    def _send(self, message: dict) -> None:
        self._conn.write(message)
        self._recorder.send(message)
