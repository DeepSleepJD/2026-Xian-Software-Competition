# P3 优化层：任务110冲刺 / 第二冰鉴 / 马类加速 / T06 解锁

## 背景

P2 经济层完成后对打官方 demo 702 分（基线）。P3 按 `docs/P3优化层开发准备.md`
机会清单性价比顺序叠加优化，目标 ~750+。

## 需求（按顺序实施，每项独立验证）

1. **任务分 110 冲刺（预期 +35）**：`TASK_SCORE_GOAL` 90→110，跑对局确认交付帧
   不恶化、csv 任务分提升。若有 130 档继续试。
2. **第二冰鉴（预期 +12~18）**：复盘为何 702 局只领到 1 个（S03/S06/S07 各 1），
   修复联动使能顺路领第 2 个。
3. **马类加速（收益待定量）**：先实测 move multiplier，再决定是否纳入估值
   （资源候选进前瞻贪心，value=省下帧数×0.12×系数）。注意 HORSE_BUFF_CONFLICT 互斥。
4. **T06 争马换乘任务（+30/个）**：领马解锁 requiredResourceTypes 门槛的联动估值。

## 验收标准

- 每项优化跑 `tools/run_match.py --no-ui` 对局（seed 默认），对比 702 基线：
  交付率 100% 不掉、总分不降；分项归因看 `refs/debug-kit-v1/arena/server/data.csv`
- 单测全绿：`cd client && python -m unittest discover -s tests`
- 里程碑粒度 commit；跳过 trellis-check（负责人规矩）

## 不做

- 窗口出牌/对抗（P4）、自对弈调参（P5）、INTEL 探路（仅顺路白捡）、蹲守选址优化
