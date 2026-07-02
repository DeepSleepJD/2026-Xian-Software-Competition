# P4 对抗层后续 backlog

## Goal

在上轮 P4 已完成破卡、出牌、削卡兜底的基础上，补齐主动设卡、资源泛化和天气感知，让客户端能主动拖慢对手、系统性领取关键资源，并在酷暑/暴雨/山雾下调整保鲜与路径估值。

本轮承接归档任务 `.trellis/tasks/archive/2026-07/07-02-p4-combat-layer` 的 `Next Session Backlog`：

- B-3 我方设卡
- D-2 资源泛化
- D-3 天气感知

参考实现基线 commit：`abdb7a7 P4 对抗层补全：破卡、出牌与削卡兜底`。

## Confirmed Facts

- `client/lychee/strategy/combat.py` 已提供高优先级 `CombatStrategy`，当前负责 `BREAK_GUARD`、`SQUAD_WEAKEN` 和窗口出牌。
- `client/lychee/pathing.py` 已有 `choke_nodes()`、敌方设卡路径惩罚、`shortest_path()` / `all_costs()` / `path_cost()`。
- `client/lychee/strategy/economy.py` 当前资源候选只覆盖 `ICE_BOX`，使用逻辑也只主动使用冰鉴。
- `GameState` 已解析 `resource_specs`、`node_states[].resource_stock`、双方 `PlayerState`、`weather_active`、`weather_forecast`、`score_preview`、守卫状态和基础 helper。
- 任务书 6.2：`SET_GUARD` 只能设在主车队当前节点，S15 禁设，处理 4 帧，额外好果 0-2，每队最多 2 个有效设卡。
- 任务书 3.3/8.3：`ICE_BOX` 保鲜；`FAST_HORSE`/`SHORT_HORSE` 是移动资源；`PASS_TOKEN`/`OFFICIAL_PERMIT` 只支付 `YAN_DIE`；`INTEL` 可给近距离节点添加探路标记。
- 任务书 2.5/3.2.2：`HOT` 全图鲜度系数 x1.5；`HEAVY_RAIN` 命中水路/码头时鲜度系数 x1.3，水路移动通行倍率 1350；`MOUNTAIN_FOG` 命中山路移动通行倍率 1100。天气提前 30 帧预告，`inquire.weather.active/forecast` 已解析。

## Requirements

- B-3 我方设卡：
  - 只在主车队空闲、当前节点非 S15、当前节点适合设卡、好果底仓安全、我方有效设卡未达 2 个时提交。
  - 使用图结构而非硬编码节点：优先当前节点是否在对手到终点剩余路径的必经点集合中，并偏好 `KEY_PASS` / `PASS`。
  - 只在我方交付进度领先、设卡净值为正时行动，避免为了设卡牺牲交付。
  - 动作格式必须为 `{"action": "SET_GUARD", "targetNodeId": cur, "extraGoodFruit": n}`，同帧不得压掉更紧急的破卡动作。
- D-2 资源泛化：
  - 将资源候选从仅 `ICE_BOX` 扩展为语义表驱动，至少覆盖 `ICE_BOX`、`FAST_HORSE`、`SHORT_HORSE`、`PASS_TOKEN`、`OFFICIAL_PERMIT`、`INTEL`。
  - 脚下或顺路 0 绕路资源一律可领取；绕路资源继续进入净值/一步前瞻框架。
  - 马类资源需要纳入领取估值，并能在合适时机主动 `USE_RESOURCE`，避免已有马 buff 或疾行令冲突导致反复被拒。
  - 文书资源只作为窗口牌成本库存，不主动使用。
  - 情报可先以保守策略纳入领取；主动使用仅在能直接减少前方关键处理帧数时触发。
- D-3 天气感知：
  - 路径估值按当前 `weather_active` 调整命中边的移动帧数与鲜度损耗。
  - `weather_forecast` 可用于近期路径估值或保鲜预判，避免刚上水路/山路就撞天气。
  - `HOT` 期间冰鉴使用阈值应前移；暴雨/山雾应让水路/山路边在估值中变贵。

## Acceptance Criteria

- [x] `CombatStrategy` 能在合成图中对领先且站在对手必经 `KEY_PASS`/`PASS` 节点的场景提出合法 `SET_GUARD`，并在 S15、好果不足、已有己方有效设卡数达 2、或未领先时不设卡。
- [x] `EconomyStrategy` 能领取脚下/顺路的 `SHORT_HORSE`、`FAST_HORSE`、`PASS_TOKEN`、`OFFICIAL_PERMIT`、`INTEL`，且继续保留现有 `ICE_BOX` 领取行为。
- [x] `EconomyStrategy` 能在合适的移动前或移动中使用马类资源，并对 `HORSE_BUFF_CONFLICT` / 资源不足反馈退避。
- [x] `EconomyStrategy` 不主动 `USE_RESOURCE` 文书类资源。
- [x] 情报使用若纳入本轮实现，必须带 `targetNodeId`，仅在停靠且目标距离不超过规则上限时触发；若不纳入主动使用，则领取库存行为必须有测试覆盖。
- [x] `pathing` 在 `HOT`、`HEAVY_RAIN`、`MOUNTAIN_FOG` 下调整边成本：HOT 增加鲜度损耗，暴雨增加水路帧数/鲜度，山雾增加山路帧数。
- [x] 冰鉴使用在 HOT 活跃或即将进入 HOT 时更积极，已有非天气场景测试保持不回退。
- [x] `cd client && python -m unittest discover -s tests` 通过。

## Notes

- 先做可单测、低耦合的策略扩展；完整陪练客户端或全对局调参不作为本轮硬门槛，除非基础单测通过后仍有时间。
- 不硬编码 S10/S15 以外的地图结构。S15 禁设来自规则/终点语义，其他咽喉点必须由图和当前状态推导。
- 保持现有交付铁律：设卡/资源/天气估值不能导致已接近终局时放弃送达。
- 本轮 `INTEL` 主动使用保持 claim-only：资源会纳入领取估值，主动 `USE_RESOURCE` 留给后续结合探路标记寿命/处理节点收益统一实现。
