# P4c 资源利用与出牌修正设计

## Boundaries

本任务只修改策略层和对应单测，保持 `GameState`、`Intent`、arbiter 合约不变。新增动作必须通过现有 intent/propose/merge 流程输出，不绕过 arbiter。

## Economy Design

资源估值仍由 `RESOURCE_BASE_VALUES` 和候选净值框架驱动。低价值资源通过较小 base value 自然避免绕路领取；硬需求资源通过候选阶段检查当前交付路径上的 `process_nodes[*].required_resource_types` 临时抬价。

硬需求判断应基于动态状态：

- 交付路径来自 delivery/strategy 已有路径信息或当前候选上下文中可访问的路径。
- 处理点来自 `state.process_nodes`。
- 资源类型来自 `required_resource_types`，不写死节点 ID。

`USE_RESOURCE` 白名单放在经济层主动使用资源的公共出口或每个资源使用提议点附近，保证未来新增文书逻辑也不会误发主动使用。

## Combat Design

### Scout Ledger

`CombatStrategy` 维护两个实例级结构：

- 有效本队标记：`node_id -> expire_round`
- 在途 scout 订单：`node_id -> dispatch_round`

每帧从新增事件流中读取：

- `SCOUT_MARKER_ADD`：若 `playerId` 为我方，登记 expire round 并清除在途。
- `SCOUT_MARKER_EXPIRE` / `SCOUT_MARKER_CONSUME`：清除本队对应节点标记。
- 超过 8 帧仍未看到 ADD 的在途订单视为失败，可重发。

`NodeState.scouted` 只能作为辅助，不作为唯一事实来源。

### Scout Proposal

新增 `_propose_squad_scout`，在 `_terminal_path` 上从当前位置向前找最近重处理节点：

- `process_round >= 4`
- ETA <= 40
- 无有效本队标记，无未超时在途订单
- `me.squad_available - 1 >= 4`

返回 `Intent(priority=127, category="squad", action={"action": "SQUAD_SCOUT", "targetNodeId": node_id})`。现有 weaken 保持 128 优先级；propose 顺序或 arbiter 都应确保同帧只最终发送一个 squad 动作。

### Window Cards

`CombatStrategy` 增加对手窗口明牌计数：

- 扫 `WINDOW_CARD_REVEAL` 事件。
- 用 `state.my_team_id` 判断对面颜色列。
- 记录总明牌数和各卡牌次数。
- 总明牌 >= 2 且 `BING_ZHENG` 占比 >= 60% 时认为对手兵正倾向。

出牌函数根据成本和场景选择：

- 默认：`BING_ZHENG`、`YAN_DIE`、`XIAN_GONG`、`ABSTAIN`
- 对手兵正倾向：`XIAN_GONG`、`BING_ZHENG`、`YAN_DIE`、`ABSTAIN`

`BING_ZHENG` 的 reserve 规则：

- `state.phase == "RUSH"` 或窗口类型为 `GATE` / `PASS`：reserve = 0
- 其他：reserve = 1

`YAN_DIE` 可用性只看文书库存总和；系统自动消耗文书，策略不得发文书 `USE_RESOURCE`。

## Compatibility

- 保持现有 action 字段命名；新增 `SQUAD_SCOUT` 使用文档指定 `targetNodeId`。
- 不修改协议解析结构，除非现有状态事件读取缺字段且测试暴露。
- 不改变现有天气、路径、交付优先级。

## Rollback

若 scout 或 window card 改动导致 match 回归，可通过单独回退 `combat.py` 新增分支保留经济修复；若经济候选抬价误选资源，可先禁用硬需求抬价并保留基础值降权。
