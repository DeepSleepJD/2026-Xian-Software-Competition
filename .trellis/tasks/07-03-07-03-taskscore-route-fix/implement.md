# 执行计划

## Phase A（本轮）

- [x] A1 economy.py `_candidates`：相邻认领仅限 CLEAR_OBSTACLE；其他障碍节点任务跳过
- [x] A1 单测：obstacle 上的 PASS_NODE 任务不产生相邻 claim；CLEAR_OBSTACLE 任务仍相邻可领
- [x] A2 combat.py：`PRIORITY_SET_GUARD 129→108`
- [x] A2 单测：同帧有 on-node CLAIM_TASK 与 SET_GUARD 时，仲裁选 CLAIM_TASK；无经济动作时仍出 SET_GUARD
- [x] 全量单测：171 例全绿
- [x] run_match vs demo seed 20260618 + 12345：768=768，无回归（当前环境基线 768，非旧 774），100% 交付
- [x] run_match vs 设卡陪练：747→757（+10，多抢一个 WATER 任务），100% 交付
- [x] commit（里程碑）

## Phase B（Phase A 通过后）

- [ ] 从 looog 日志提取"山路最优"地图，写离线路线断言夹具
- [ ] 实现全路线期望分枚举（pathing 新函数 / 或改 shortest_path 成本）
- [ ] 放宽/移除 P4e 慢边禁令
- [ ] 夹具断言选山路；vs demo 不回归；vs 陪练不回归
- [ ] commit

## 验证命令
- 单测：`cd client && python -m unittest discover -s tests`
- 对局：`python tools/run_match.py --no-ui --seed 20260618`（换 12345）
- 陪练：见 tools/adversary_guard.py 用法
