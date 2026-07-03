# P4m 执行清单

验证命令（通用）：
- 单测：`cd client && python -m unittest discover -s tests`
- demo 局：`python tools/run_match.py --seed 20260618 --no-ui`
- 陪练局：`python tools/run_match.py --no-ui --client-cmd-b "python tools/adversary_guard.py {player_id} {host} {port}"`（具体参数以脚本现状为准）

测试从简（用户指令）：每里程碑跑单测；对局回归只在 M1（合并后基线）、M6/M7（收尾）跑，中间里程碑可疑再加。

- [ ] **M1 合并 xichen-intercept**：`git merge xichen-intercept`；解 combat.py/_squad_reserve 冲突（铁律语义为基 + `_opponent_locked` 锁死态=2，见 design#1）；单测全绿（≈275+）；demo 20260618 + 现有陪练各一局确认合并后基线（demo ≥768、陪练 ≥757 且 100% 交付）。**commit（回退点 1）**
- [ ] **M2 被冻逃生实验**（timebox ~1h）：runtime env 探针 `LYCHEE_FROZEN_PROBE`；vs adversary_guard 跑一局拿三种动作（改道 MOVE / FORCED_PASS / BREAK_GUARD）在冻结态的 actionResults；结论写入本任务 research/ 或 docs。探针代码不默认激活。
- [ ] **M3 hold 闸门重做**：safety.py 删 GAP 判定、删 guard_ever_seen、删条件 5、12 帧上限改时间预算制（无状态）；`_break_action` 加一击闸（attack<defense 且对手可增援→不出手）；单测：13:22 局 r255 场景（对手同边领先+未设过卡→hold）、时间预算耗尽放行、亮卡不 hold、一击闸正反例、P4h 候选级剔除回归。**commit（回退点 2）**
- [ ] **M4 削卡战止损**：state.py 解析对手 SQUAD_REINFORCE 事件→mem 粘滞标记（含防值回升兜底）；`_propose_squad_weaken` 加止损闸；单测：探针首削放行、增援观测后停手、对手无兵/已交付照常削。**commit（回退点 3）**
- [ ] **M5 领先权治理器**：economy 候选过滤链加 `gate_race`（含一步前瞻）；单测：农夫对手不触发、竞速对手剔除慢候选、已落后不禁食、无竞争咽喉放行。**commit（回退点 4）**
- [ ] **M6 滚动设卡**：G2 set-on-commit 推广为沿途滚动（未 commit 但领先 ≥20 帧且对手必经也设）；2 卡上限/好果预算/悬赏分差闸/RUSH 兼容；单测：领先设卡、落后不设、第 2 张卡、预算不足不设；demo 20260618 回归。**commit（回退点 5）**
- [ ] **M7 陪练 --reinforce + 收尾回归**：adversary_guard.py 反应式增援模式；三局回归：demo 20260618（≥768）、旧陪练（≥757 100%交付）、--reinforce 关门打狗局（100% 交付且 ≥600，验收核心）；按 M2 结论实装或记档逃生舱；spec/CLAUDE.md 进度更新。**commit（收尾）**

回滚：各里程碑独立 commit，`git revert` 单点回退；行为旋钮见 design#8 常量表。
