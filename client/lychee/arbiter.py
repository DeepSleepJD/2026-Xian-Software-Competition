"""意图仲裁：各策略 Intent 合并为每帧最终 actions。

M1 首版：按 priority 降序拼接。
M2/M4 扩展：同类动作去冲突（如两个策略同时要 MOVE）、动作数上限、合法性联动预检。
"""

from .strategy import Intent


def merge_intents(intents: list[Intent]) -> list[dict]:
    ordered = sorted(intents, key=lambda it: it.priority, reverse=True)
    actions: list[dict] = []
    for intent in ordered:
        actions.extend(intent.actions)
    return actions
