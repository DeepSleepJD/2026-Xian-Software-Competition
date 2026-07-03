"""意图仲裁：各策略 Intent 合并为每帧最终 actions。

协议第 8 章"动作类别限制"：主车队动作/小分队动作/终局急策/窗口出牌同帧各限 1 个，
超限 = INVALID_ACTION_CONFLICT（非法动作，累计扣分）。
仲裁规则：按 priority 降序，每个类别只放行第一个，其余丢弃（策略层靠优先级竞争）。
类别划分依据附录 E 动作索引表：SQUAD_* 为小分队，RUSH_SPEED/RUSH_PROTECT 为急策
（BREAK_ORDER 只作 rushTactic 绑定、不独立发送），WINDOW_CARD 为全局窗口出牌额度，
其余（含 USE_RESOURCE/PROCESS/DOCK 等）均为主车队动作；未知动作名保守按主车队处理。
"""

from .strategy import Intent

_SQUAD_ACTIONS = {"SQUAD_SCOUT", "SQUAD_CLEAR", "SQUAD_REINFORCE", "SQUAD_WEAKEN"}
_RUSH_ACTIONS = {"RUSH_SPEED", "RUSH_PROTECT"}


def _category(action: dict) -> str:
    name = action.get("action", "")
    if name in _SQUAD_ACTIONS:
        return "squad"
    if name in _RUSH_ACTIONS:
        return "rush"
    if name == "WINDOW_CARD":
        return "window"
    return "main"


def merge_intents(intents: list[Intent], me=None) -> list[dict]:
    ordered = sorted(intents, key=lambda it: it.priority, reverse=True)
    taken: set[str] = set()
    actions: list[dict] = []
    for intent in ordered:
        for action in intent.actions:
            cat = _category(action)
            if cat in taken:
                continue
            taken.add(cat)
            actions.append(action)
    escort = _escort_move(taken, me)
    if escort is not None:
        actions.insert(0, escort)
    return actions


def _escort_move(taken: set[str], me) -> dict | None:
    """半路派小分队若不同帧捆绑 MOVE(nextNodeId)，服务器会让主车队停走 1 帧。

    未文档化服务器行为（2026-07-03 日志实证）：边上单发 SQUAD_* 187/187 掉 1 tick，
    捆绑 [MOVE, SQUAD_*] 5/5 进度连续；主+小分队同帧各 1 个合法（协议第 8 章）。
    仅 state=MOVING 时护航：WAITING/PAUSED（守卡拦停）下 MOVE 会被拒，不添乱。
    """
    if me is None or "squad" not in taken or "main" in taken:
        return None
    if getattr(me, "state", "") != "MOVING" or not getattr(me, "next_node_id", ""):
        return None
    return {"action": "MOVE", "targetNodeId": me.next_node_id}
