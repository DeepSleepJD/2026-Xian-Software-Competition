"""协议消息构造与解析。

M1 最小版：外层 msg_name/msg_data 拆解 + 客户端上行三类消息构造。
M2 扩展：start/inquire 全字段类型化解析（对照通信协议文档逐字段核对）+ action 合法性预检。
"""

from typing import Any

MSG_START = "start"
MSG_INQUIRE = "inquire"
MSG_OVER = "over"
MSG_ERROR = "error"


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
    """构造 action 消息。actions 为空列表即心跳。"""
    return {
        "msg_name": "action",
        "msg_data": {
            "matchId": match_id,
            "round": round_no,
            "playerId": player_id,
            "actions": actions,
        },
    }
