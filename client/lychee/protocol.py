"""协议消息构造与解析。

M1 最小版：外层 msg_name/msg_data 拆解 + 客户端上行三类消息构造。
M2 扩展：start/inquire 全字段类型化解析（对照通信协议文档逐字段核对）+ action 合法性预检。
"""

import os
from typing import Any

MSG_START = "start"
MSG_INQUIRE = "inquire"
MSG_OVER = "over"
MSG_ERROR = "error"

# WINDOW_CARD 的牌字段名：协议文档与现网均为 "card"（2026-07-03 现网日志逐拍验证），
# 但调测 kit 的本地裁判 exe 是旧 schema "cardType"（二进制字符串 + INVALID_JSON 实证），
# 发 "card" 会被整条判 PROTOCOL_ERROR 吞帧记 ABSTAIN。默认现网格式；
# 本地不匹配时由 runtime 收到空 error 回执后调 use_card_type_field() 一次性切换。
_DEFAULT_CARD_FIELD = os.environ.get("LYCHEE_WINDOW_CARD_FIELD", "card")
_card_field = _DEFAULT_CARD_FIELD


def window_card_field() -> str:
    return _card_field


def use_card_type_field() -> None:
    global _card_field
    _card_field = "cardType"


def reset_card_field() -> None:
    """单测隔离用。"""
    global _card_field
    _card_field = _DEFAULT_CARD_FIELD


def parse_message(message: dict) -> tuple[str, dict]:
    """拆外层信封，返回 (msg_name, msg_data)。字段缺失不抛异常，交由调用方按类型分发。"""
    name = message.get("msg_name", "")
    data = message.get("msg_data") or {}
    return name, data


def build_registration(player_id: int, player_name: str, version: str) -> dict[str, Any]:
    return {
        "msg_name": "registration",
        "msg_data": {
            "playerId": player_id,
            "playerName": player_name,
            "version": version,
        },
    }


def build_ready(match_id: str, round_no: int, player_id: int) -> dict[str, Any]:
    return {
        "msg_name": "ready",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
        },
    }


def build_action(match_id: str, round_no: int, player_id: int, actions: list[dict]) -> dict[str, Any]:
    """构造 action 消息。actions 为空列表即心跳。WINDOW_CARD 按当前牌字段名出线。"""
    if _card_field != "card":
        actions = [_rewrite_card_field(a) for a in actions]
    return {
        "msg_name": "action",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
            "actions": actions,
        },
    }


def _rewrite_card_field(action: dict) -> dict:
    if action.get("action") != "WINDOW_CARD" or "card" not in action:
        return action
    rewritten = dict(action)
    rewritten[_card_field] = rewritten.pop("card")
    return rewritten
