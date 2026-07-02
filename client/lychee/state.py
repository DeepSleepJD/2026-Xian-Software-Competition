"""GameState 世界模型：策略层的唯一输入。

M1 占位版：仅缓存原始消息 + 关键标识，保证数据流打通。
M2 定稿：对照通信协议第 5/7 章逐字段类型化（地图、双方队伍、任务、资源、
天气、设卡、事件、actionResults），并加派生量（如到各节点最短路）。
定稿后此契约冻结，改动需三人同步。
"""


class GameState:
    def __init__(self, player_id: int) -> None:
        self.player_id = player_id
        self.match_id = ""
        self.round = 0
        # M1：原始消息直通，策略层暂时自行取字段；M2 全部类型化后移除
        self.start_raw: dict = {}
        self.inquire_raw: dict = {}

    def update_start(self, data: dict) -> None:
        self.start_raw = data
        self.match_id = data.get("matchId", "")

    def update_inquire(self, data: dict) -> None:
        self.inquire_raw = data
        self.round = data.get("round", self.round)
