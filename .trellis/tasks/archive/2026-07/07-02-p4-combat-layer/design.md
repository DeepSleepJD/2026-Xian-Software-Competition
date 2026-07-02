# P4 对抗层补全 Design

## Boundaries

- `client/lychee/state.py` 只负责解析与只读 helper，不产生策略决策。
- `client/lychee/strategy/combat.py` 只读 `GameState` 并产出 `Intent`；不直接调用网络、不修改其他策略内部状态。
- `client/lychee/pathing.py` 继续提供图算法与路径成本，新增守卫惩罚时保持换图兼容。
- `client/lychee/arbiter.py` 的类别仲裁不改协议，只依赖 combat 更高主动作优先级压过 `MOVE`。

## Data Flow

1. `Runtime` 每帧更新 `GameState`。
2. `CombatStrategy` 先根据 `GameState` 查找本方下一跳和敌方守卫：
   - 若本方停靠/等待且相邻目标有敌卡，产出高优先级 `BREAK_GUARD`。
   - 若本方 MOVING 且 `nextNodeId` 有敌卡，产出独立小分队额度的 `SQUAD_WEAKEN`。
   - 若存在相关本方未结算窗口，选择最高价值的一个产出 `WINDOW_CARD` intent；窗口类别可与主动作共存。
3. `DeliveryStrategy` / `EconomyStrategy` 仍可按原逻辑产出 `MOVE`、任务、资源动作。
4. `arbiter.merge_intents()` 按 priority 合并；combat 主动作优先，窗口出牌独立保留。

## Contracts

- `GameState.enemy_guard_at(node_id)` 返回敌方、active、defense>0 的 `Guard`，否则 `None`。
- `GameState.blocked_by_guard()` 只根据本方上一帧 `ACTION_REJECTED` / `ActionResult` 的 `MOVE_BLOCKED_BY_GUARD` 推断，优先返回本方 `next_node_id` 或最近一次 `MOVE` 目标。
- `GameState.my_open_contests()` 等价于本方参与、未 resolved、非 SUPPRESSED 的窗口，作为 `my_contests()` 的明确语义别名。
- `CombatStrategy` 的 `BREAK_GUARD` 投入解算坏果优先，单次好/坏果各不超过 2，不声明超过库存的投入。
- 零弹药时不产出高优先级主动作，让路给 economy/delivery 寻找资源或绕行。
- `WINDOW_CARD` 始终带 `contestId` 与 `card`，且每帧最多一张；无力争夺相关窗口时显式 `ABSTAIN`，无关窗口不提交。
- `SQUAD_WEAKEN` 只在 MOVING 且下一节点有敌方有效设卡时触发，并按当前防守值估算已在途小分队是否足够，避免过量派遣。

## Pathing Design

- `choke_nodes(state, src, dst)` 通过“移除节点后 src/dst 是否仍连通”计算所有必经点；排除 `src` 与 `dst`。
- `_step_cost()` 在进入带敌方有效设卡的 `to_node` 时加入小额帧/鲜度惩罚；果品足够时近似 1-6 帧，果品不足时按守卫剩余风化时间保守估计。
- 惩罚只影响路径排序，不替代 combat 的合法性检查；真正破卡仍由主车队 `BREAK_GUARD` 执行。

## Trade-offs

- 本迭代先做“被卡能打 + 不上死边 + 窗口不缺席 + MOVING 后设卡最小削弱”，主动设卡和完整小分队策略后置，降低一次改动的风险。
- 窗口出牌先采用规则克制与资源余量启发，不尝试预测对手混合策略。
- 经济层振荡先用目标承诺/原路折返保护，不重写整体净值框架。

## Rollback

- 若 combat 行为异常，可从 `client/main.py` 的策略列表移除 `CombatStrategy()`，恢复 P3 行为。
- `pathing` 守卫惩罚应保持小范围、纯函数式；测试失败时可只回滚惩罚，保留 `choke_nodes()`。
