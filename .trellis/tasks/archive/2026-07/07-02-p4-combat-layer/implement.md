# P4 对抗层补全 Implementation Plan

## Checklist

1. 状态层
   - 给 `Event` 增加 `error_code` 解析。
   - 给 `GameState` 增加 `my_state()`、`enemy_guard_at()`、`blocked_by_guard()`、`my_open_contests()`、`my_guard_points`、`my_good`、`my_bad`。
   - 补 `test_state.py` 合成用例。
2. 寻路层
   - 新增 `choke_nodes()` 与连通性辅助。
   - `_step_cost()` 加敌方守卫惩罚，并补 `test_pathing.py`。
3. CombatStrategy
   - 新建 `client/lychee/strategy/combat.py`，定义优先级高于 economy/delivery。
   - 实现下一跳识别、攻坚投入解算、MOVING 小分队削卡、窗口出牌。
   - 补 `test_combat.py` 覆盖破卡、零弹药让路、小分队削卡、窗口出牌、仲裁压制 MOVE。
4. 接线
   - 在 `client/main.py` 接入 `CombatStrategy()`，顺序放在 economy/delivery 前。
   - 更新必要 import。
5. 经济层振荡
   - 增加目标承诺迟滞与原路折返保护，补现有 economy 合成测试。

## Validation

- `cd client && python -m unittest discover -s tests`
- 如时间允许，增加回放 fixture 断言 `looog/game_result (3)/(4)` 的守卫阻挡帧能被 state helper 识别。

## Risky Files

- `client/lychee/state.py`：解析契约冻结点，新增 helper 必须只读且容错。
- `client/lychee/pathing.py`：成本变化会影响 delivery/economy 选路，守卫惩罚必须只在存在敌方有效设卡时生效。
- `client/lychee/strategy/economy.py`：振荡修复需避免破坏 P3 任务/冰鉴收益。

## Next Session Backlog

- B-3 我方设卡：补主动设卡净值模型，优先 KEY_PASS/PASS 必经点，控制同时有效设卡上限与好果底仓。
- D-2 资源泛化：从 ICE_BOX 扩展到马类、文书、INTEL 等资源语义表，并纳入顺路/绕路估值。
- D-3 天气感知：按 HOT/HEAVY_RAIN/MOUNTAIN_FOG 调整鲜度阈值和路径边代价，并利用 forecast 预判。

## Start Gate

- 规则原文 6.3.1 / 8.2 已读。
- `docs/P4-对抗层改动清单.md` P0 范围已转成验收标准。
- 当前任务可进入 Phase 1.4 `task.py start` 后实施。
