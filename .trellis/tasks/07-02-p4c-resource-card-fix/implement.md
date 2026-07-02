# P4c 实施计划

## Checklist

- [x] 阅读 backend spec index 和相关指南。
- [x] 检查 `combat.py`、`economy.py`、state/event 模型、现有测试，确认字段名和本地模式。
- [x] 实现经济层估值下调与硬需求资源抬价。
- [x] 增加 `USE_RESOURCE` 白名单，保证文书永不主动使用。
- [x] 实现 scout 标记台账、在途订单、`_propose_squad_scout`。
- [x] 调整 combat propose 流程，保持 weaken 优先于 scout。
- [x] 实现窗口出牌重构和对手 `WINDOW_CARD_REVEAL` 建模。
- [x] 修正 `_break_action` 坏果过杀，并在协议字段确认后实现脚下 `INTEL` 使用。
- [x] 更新 `client/tests/test_economy.py`、`client/tests/test_combat.py` 等相关单测。
- [x] 运行 `cd client && python -m unittest discover -s tests`。
- [x] 运行 seed 20260618 和 12345 demo 回归；两把均为 774 分。

## Validation Commands

```bash
cd client
python -m unittest discover -s tests
```

```bash
python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --no-ui --seed 20260618
python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --no-ui --seed 12345
```

## Risk Points

- `SCOUT_MARKER_*` 事件字段名可能和文档描述略有差异；实现要兼容 payload 平铺和嵌套。
- `Contest` / window 对象字段名需按现有代码和测试确认，避免改坏已有窗口出牌。
- 硬需求资源抬价需要拿到当前路径；若经济层没有直接路径上下文，优先复用已有路径辅助，不引入跨层循环依赖。
- demo 分数可能受运行耗时影响；先保证单测和策略行为，再做 match 回归。
