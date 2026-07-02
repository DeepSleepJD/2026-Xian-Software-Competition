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

### B0 强对手陪练（用户定：先造陪练再改路线）—— 已完成
- [x] 发现自对弈致命坑：近镜像客户端在可争夺站点(S02)同帧处理→每拍同牌必平→
      DRAW 冷却重试→双方 0% 死锁（任务书 5.4.4）。self-play 不可用于近镜像对比。
- [x] `tools/adversary_racer.py`：帧数最短路(山路快线)+抢脚下任务(含相邻T04)+用马+
      起手错1拍。忠实复现现网 1336 败法：陪练走山路 MOUNTAIN:120|WATER:60 raw180
      r483 交付；我方 ROAD raw105 task140。725 vs 720（seed 20260618/12345 一致），
      均 100% 交付、无死锁。→ Phase B 路线改动的验证基座。
- [x] `tools/selfplay.py`：候选 vs 冻结基线(git worktree)，多种子换边（附镜像死锁告诫）。
- [ ] commit B0 陪练工具（里程碑）

### B1 路线成本模型
- [ ] 实现全路线期望分枚举（pathing 新函数 / 或改 shortest_path 成本）
- [ ] 放宽/移除 P4e 慢边禁令
- [ ] 验证：vs adversary_racer 反超（目标明显 > 720）；vs demo 不回归(768)；vs 设卡陪练不回归
- [ ] commit

### 已知遗留（本任务外，低现网风险，需记录）
- 镜像 DOCK 死锁：若真实对手与我方帧级同步在同一可争夺站点处理，双方会平局冷却卡死。
  现网到站差≥1帧即被规则 740 化解，风险低；但"隔壁~775 同源对手"值得警惕，后续考虑
  加"平局N次后错拍/绕行"兜底。

## 验证命令
- 单测：`cd client && python -m unittest discover -s tests`
- 对局：`python tools/run_match.py --no-ui --seed 20260618`（换 12345）
- 陪练：见 tools/adversary_guard.py 用法
