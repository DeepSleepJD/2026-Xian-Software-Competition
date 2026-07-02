# P4d 守卫半路自锁死锁修复 执行计划

依赖顺序：Step 1-2（R1/R2 核心修复）→ Step 3（R3 兜底）→ Step 4（R4 工具）→ Step 5（对局验证）。
Step 1-2 与 Step 4 无代码依赖，可并行；Step 5 依赖全部完成。

> 执行记录（2026-07-02）：Step 1-6 全部完成。Step 5 复现对照局暴露追加需求 R5
> （S10 开局 LANDSLIDE 障碍、我方无清障能力 → 与守卫死锁同级的卡死缺陷，历史局
> 靠 demo 做 T04 掩盖），按 R5/改动 5 实施后重新走完 Step 5 验收，结果见 prd.md。

## Step 1：核心修复单测先行（红）

- [ ] `client/tests/test_combat.py` 新增用例（先写先跑，确认当前代码红）：
  - `test_break_guard_blocked_when_paused_mid_edge`：WAITING + move_direction="PAUSED" +
    next_node_id 非空 + 目标节点敌卡有效 → propose 无 BREAK_GUARD 动作；
  - `test_squad_weaken_keeps_dispatching_when_paused`：同状态 + squad_available 充足 →
    产出 SQUAD_WEAKEN；squad_in_flight ≥ ceil(defense/2) 后停手；squad_available<2 不派；
  - `test_break_guard_still_fires_when_docked`：next_node_id=""、move_direction 非 PAUSED、
    邻点敌卡 → BREAK_GUARD 照常（防回归锚点）。
- 验证：`cd client && python -m unittest tests.test_combat` → 新用例红、老用例绿。

## Step 2：修 combat.py（R1 + R2）

- [ ] `_propose_break_guard` 加闸：`if me.next_node_id or me.move_direction == "PAUSED": return None`
      （位置：`_STATIONARY_STATES` 检查之后、`cur` 取值之前）。
- [ ] `_propose_squad_weaken` 状态判据替换为 en_route 判定（design.md 改动 2 代码）。
- 验证：`cd client && python -m unittest tests.test_combat` 全绿。
- 回滚点：两处单函数改动，git 粒度独立可 revert。

## Step 3：safety.py「送达优先」（R3）

- [ ] 新增 `client/lychee/strategy/safety.py`：`RUSH_SAFETY_MARGIN`、`frames_to_terminal(state)`、
      `must_rush(state)`（算式与接线表见 design.md 改动 3）。
- [ ] `combat.propose`：must_rush 时跳过 `_propose_set_guard`（break/weaken/scout/出牌保留）。
- [ ] `economy.propose`：must_rush 时跳过 `_propose_economy`（ice/horse/intel use 保留）。
- [ ] 新增 `client/tests/test_safety.py` + `test_economy.py`/`test_combat.py` 接线用例
      （清单见 design.md 单测设计）。
- 验证：`cd client && python -m unittest discover -s tests` 全量绿（83 例 + 新增）。
- 回滚点：新模块 + 两处调用点；紧急退化可置 `RUSH_SAFETY_MARGIN = 0`。

## Step 4：设卡对手工具（R4）

- [ ] 新增 `tools/adversary_guard.py`（设计见 design.md 改动 4）：复用 lychee 包，
      选点（choke 自动 + `--guard-node` 覆盖）→ 赶路（MOVE+PROCESS）→ 对手上边当帧 SET_GUARD
      → 风化后补设。入参约定 `<player_id> <host> <port>`，兼容 run_match 模板占位符。
- 验证（工具自检）：挂 `--demo-cmd` 跑一局能正常连接、到点、设卡（看 tools/logs/demo_2002.log
  与 server/log.txt 出现 SET_GUARD 受理记录），对局能跑完出分。

## Step 5：对局验证（验收闸）

- [ ] **死锁复现对照（可选但建议）**：先用 git stash 临时还原 combat.py 修复跑一局设卡对手局，
      确认能复现 MOVING_ACTION_FORBIDDEN 刷屏 → 证明工具有效，再恢复修复。
- [ ] **设卡对手局**：
      `python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --demo-cmd "python tools/adversary_guard.py {player_id} {host} {port}" --no-ui`
      通过标准：我方 delivered=true（server/data.csv）；
      `grep -c MOVING_ACTION_FORBIDDEN` 于 server/log.txt、client_debug.txt 中我方记录 = 0；
      被卡段冻结帧数 ≪ 190（看回放或日志中 PAUSED 持续帧数，预期个位数~十几帧）。
- [ ] **demo 回归局**：seed 20260618 与 12345 各一局
      `python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --seed <seed> --no-ui`
      通过标准：100% 交付、分数不低于 771 水平（小幅波动可接受，未送达/断崖即失败）。
- [ ] 全量单测最终跑一遍：`cd client && python -m unittest discover -s tests`。

## Step 6：收尾（Phase 3）

- [ ] CLAUDE.md「当前进度」补 P4d 一行（败因 + 修复 + 验证结果数字）。
- [ ] 更新项目记忆 `lychee-competition-status.md`（死锁根因与修复经验：半路 PAUSED 三字段
      判别、削卡是暂停态唯一快清手段）。
- [ ] 里程碑粒度 commit（分两笔：核心修复+兜底；工具+验证产物按需）。
- 流程约定：跳过 trellis-check 重质检；单测绿 + run_match 能跑即推进。

## 失败处置

- Step 5 设卡对手局若仍未送达：先看是削卡资源不足（squad_available）还是新的状态组合
  未覆盖（dump 我方 state/moveDir/nextNodeId 三元组逐帧），回到 Step 1 补用例再修，
  不做无单测的盲改。
- demo 回归掉分 >30：二分定位到改动 1/2/3 中哪一项（互相独立可单独 revert）。
