# 设计

## Phase A — 执行修复

### A1 NOT_AT_TARGET_NODE（economy.py `_candidates`）
协议任务书 690 行铁律：**除 T04 清障任务外，主车队必须停在任务目标节点才能处理；T04 可在目标障碍节点或相邻节点处理**。协议 294 行：目标站点有障碍时不可 MOVE 到达。

现状 bug：`_candidates` 里凡 `ns.has_obstacle` 就把 claim_nodes 设为相邻节点，导致 PASS_NODE/STATION_PROCESS 任务被从相邻节点误发 → NOT_AT_TARGET_NODE。

改法：
- `is_clear = t.process_type == "CLEAR_OBSTACLE" or t.task_template_id == "T04"`
- 目标节点有障碍：
  - `is_clear` → claim_nodes = 相邻节点（保留现有行为）
  - 否则 → `continue`（跳过；节点不可达，障碍清除后该任务会重新进候选）
- 无障碍 → claim_nodes = [t.node_id]

### A2 抢任务优先于设卡（combat.py）
优先级同属 arbiter "main" 槽，每帧只放行一个。现 `PRIORITY_SET_GUARD=129 > PRIORITY_ECONOMY=110` → 设卡挤掉抢任务。

改法：`PRIORITY_SET_GUARD 129 → 108`（落在 economy 110 与 delivery 100 之间）。效果：
- 有经济动作（抢任务/领资源/用冰鉴/用马 110-120）时先做，设卡让位；
- 无经济动作（raw 拿满 / 无可行任务）时设卡仍先于纯 delivery 走位（108>100）触发——保留巡航中在咽喉设卡的能力。
- 破卡 `PRIORITY_COMBAT_MAIN=130`、削卡 128、探路 127、清障 130 全**不动**（对敌方卡的应对不受影响，陪练测试不回归）。

## Phase B — 路线成本模型（全路线期望分枚举）

### 现状
`pathing.shortest_path` / `all_costs` 按 `(鲜度损耗, 帧数)` 字典序，鲜度绝对优先。`_step_cost`: `fresh = frames * ROUTE_FRESHNESS[route]`。每单位距离鲜度损耗 = coef × freshness：ROAD 75.9 / WATER 56.3 / MOUNTAIN 124.6 / BRANCH 100.75。

### 方向（细节 Phase A 完成后再定稿）
把"帧数"和"鲜度损耗"折算成**统一分值**再比较，而非字典序：
- 鲜度损耗 → 分：每点鲜度 ≈ ICE_BOX_VALUE/10 ≈ 1.8 分（已有常量口径）。
- 帧数 → 分：时间分很小（time≈8-15），但**早到 = 多做任务的机会**。用"沿途 + 提前期可收任务期望分"体现，或给帧一个小的机会成本系数。
- 候选路线：枚举到终点的 K 条近似路线（或对每条主线 bucket 各取一条最短），估 `delivery + freshness_score(末鲜度) + Σ 沿途可收任务期望 + time` 取最大。
- 重审慢边禁令：期望分模型能自洽后，`SLOW_ROUTE_COEF_LIMIT` 禁令应放宽/移除。

### 测试图缺口（关键）
demo 图（seed 20260618/12345）是**水路最优**，跑不出山路回归。需要"山路最优"图：
- 方案 a：从 looog 日志的 start/inquire 提取真实地图，写一个离线单测夹具（GameState + 期望路线断言），直接验证枚举选出山路。
- 方案 b：扫 seed 找山路最优的地图变体喂 run_match。
- 优先 a（确定、可回归），b 作对局级验证补充。

## Phase B2 — 竞争建模三件套（B1 暂缓后的主攻方向，2026-07-03 用户定夺）

背景：B1 复盘重判败因 = 同路任务被对手抢走（跑到才吃 OBJECT_BUSY 白跑）+ 对手更快 +
对手用冰鉴。三件套针对第一项，全部落在 economy 候选估值处（`_candidates`/`_pick_target`），
不动仲裁阶梯。任务和可认领资源（冰鉴等）同为先到先得，三件套对两者一视同仁。

### B2a 锁定检测（硬信号）
对手 `state == "PROCESSING"` 且 `current_process.task_id` / `resource_type`+`target_node_id`
命中候选 → 该候选当帧出局。不再等 CLAIM 被拒（OBJECT_BUSY）反馈才 backoff。

### B2b 竞争折扣（软信号）
每帧最多算一次 `opp_costs = all_costs(state, 对手位置)`（对手 MOVING 时按
next_node + 剩余边帧折算，参考 `safety._remaining_edge_frames`）。对每个候选停靠点 spot：
- **出局**：对手 ETA 明显更近（`opp_eta + MARGIN < my_to_frames`）**且**正朝它去
  （opp.next_node_id 在其到 spot 的最短路方向上）——强信号，抢不过；
- **打折**：对手仅 ETA 更近、无朝向信号 → 净值 × `CONTEST_DISCOUNT`（0.5 起步）。
不确定时宁可折扣、不硬出局——对手一次只能处理一个目标，全面出局会饿死经济层。

### B2c 折扣解除
对手满足任一：task raw ≥ 130（封顶不再抢任务，仅解除任务候选的折扣，资源候选折扣保留）/
delivered / retired / verified → B2b 失效；B2a 锁定检测始终保留。

### B2 风险
- demo 也抢任务，折扣会改变 vs demo 行为——demo 双种子回归是硬闸门。
- 折扣过猛 → 放弃太多候选 → raw 反降。单测必须覆盖"对手在远处时估值完全不变"。
- 同路争夺场景对局层暂不可复现（陪练无破卡/绕障，见 implement.md B1 复盘），
  本轮以单测 + 三方回归闸门（demo/racer/guard 不掉分）验收，对局级实证留给鲁棒陪练后续。

## 风险 / 回滚
- 每个改动独立 commit（里程碑粒度），run_match 对局验证后再推进下一个。
- A2 若使 demo 掉分，检查是否 demo 依赖设卡得分（预期不依赖）。
- Phase B 若 demo 翻车，回退到字典序（保留原函数或 flag）。
- B1 路线成本模型已被 755:737 实验推翻，暂缓（见 implement.md）；勿在 B2 中夹带路线改动。
