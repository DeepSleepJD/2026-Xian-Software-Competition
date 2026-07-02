"""策略层公共契约：Strategy 基类 + Intent。

策略模块（delivery/economy/combat）只读 GameState、只产 Intent，
不直接发包、不互相调用。Intent 经 arbiter 仲裁合并成每帧最终 actions。
M2 定稿契约后冻结，改动需三人同步。
"""

from dataclasses import dataclass, field

from ..state import GameState


@dataclass
class Intent:
    kind: str                       # 意图类型，如 "move" / "deliver" / "combat"
    priority: int                   # 仲裁优先级，大者先；同类别动作冲突时只放行最高者
    actions: list[dict] = field(default_factory=list)  # 候选动作（协议 actions[] 元素）
    note: str = ""                  # 调试备注（不发给服务端）


class Strategy:
    def propose(self, state: GameState) -> list[Intent]:
        return []


class NoopStrategy(Strategy):
    """M1 占位：恒不出招，先保骨架 600 帧不掉线。"""
