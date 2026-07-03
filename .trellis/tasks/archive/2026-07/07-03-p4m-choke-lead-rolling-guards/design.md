# P4m 技术设计

## 0. 总体结构：三层防守 + 一路进攻

```
R 领先权治理器(economy 候选过滤)  ── 让"落后进咽喉"尽量不发生
A 防陷阱闸门重做(safety)          ── 输掉竞速时不进死边
B 削卡战止损(combat)              ── 万一被冻不再白送小分队
C 被冻逃生(实验后定)              ── 被冻后的有限时间脱困
E intercept 合入 + 滚动设卡(combat) ── 赢下竞速时反手关对手的门
```

统一的底层新设施：**竞争咽喉 + 双方 ETA**。合并 xichen-intercept 后由 G1 ETA 引擎提供对手 ETA；咽喉集合复用 `pathing.choke_nodes`（hold_before_choke 已在用）。"竞争咽喉"定义：我方剩余交付路径上尚未通过、且对手也尚未通过的割点类节点（本图即 S10）。

## 1. 合并计划（M1）

- `git merge xichen-intercept`（分支基点 70b9f95，主线仅多铁律 88249e4 + 2 个 archive 提交）。
- 冲突面：仅 `client/lychee/strategy/combat.py` + `client/tests/test_combat.py`（铁律改了 `_squad_reserve`，分支 G3 花小分队做 REINFORCE）。
- 解法（决策记录#1）：`_squad_reserve` 保持铁律语义为基（验核前 6/验核后 0），新增"锁死态"分支：
  ```python
  def _squad_reserve(state):
      if state.me.verified: return 0
      if _opponent_locked(state): return SQUAD_RESERVE_LOCKED  # =2, 腾 4 支给 2 次 REINFORCE
      return SQUAD_RESERVE_BEFORE_GATE  # =6
  ```
  `_opponent_locked(state)`：我方有效卡在竞争咽喉上 && 对手在其远侧（对手到我方剩余路径任一节点的最优 ETA 均需经过该卡 或 绕行 ETA > 我方到终点 ETA）。保守实现：对手 currentNodeId/nextNodeId 在卡节点远侧连通分量内（拓扑判定，删掉卡节点后做可达性）。
- 分支测试若断言旧保留量，按铁律+锁死态语义改断言。

## 2. R 领先权治理器（M5，economy.py）

挂在候选过滤链上（与慢边禁令、`_is_backtrack_trip`、B2 折扣并列，候选级、不整层闭嘴）：

```
gate_race(candidate):
    choke = 第一个竞争咽喉(我未过 && 对手未过)   # 无 → 放行
    if 对手 delivered/retired → 放行
    my_direct  = ETA(cur → choke)
    opp_eta    = ETA(opp → choke)               # G1 引擎
    if my_direct > opp_eta - MARGIN → 放行      # 竞速已输,照常吃分,hold 闸门兜底
    my_via     = ETA(cur → 候选点) + 处理帧 + ETA(候选点 → choke)
    return my_via <= opp_eta - MARGIN           # 做完仍领先才准入
```

- `CHOKE_LEAD_MARGIN = 8`（帧，模块顶常量）。
- 关键性质：农夫型对手（opp_eta 很大）→ 约束永不触发，772 基线零损；竞速型 → 自动逐候选收缩为纯冲刺；**已经落后时不禁食**（多做任务不增加风险，被拦由 A 层兜底——13:22 局若已注定落后，带 150 任务分到 S09 好过空手）。
- 前瞻（一步 lookahead）同约束。

## 3. A 防陷阱闸门重做（M3，safety.py:109-204 区域）

`_can_opponent_set_guard_before_arrival`（:109-123）：

- **删 `opp.guard_action_point < 1` 判定**（GAP 是兵争牌货币，与设卡无关——13:22 局对手 GAP 恒 4 只是没出过牌）。设卡真实成本=好果且普通节点基础 0 篓 ⇒ 资源面永远可行，只保留 delivered/retired 排除。
- 位置/ETA 判定保持：对手停在我下一跳节点上 → 威胁；对手朝它走且 `opp_eta + 4(设卡读条) <= my_eta` → 威胁。

`hold_before_choke`（:164-204）：

- **删条件 3 `guard_ever_seen` 先验**（13:22 局的一票否决根因）。
- **删条件 5 "小分队 ≥ 节点防值上限则不等"**（增援战实证小分队削不穿有兵对手的卡，兵力永远"不足"，该放行条件是伪安全）。
- 条件 4 保留（下一跳已亮卡 → 不 hold，由停稳攻坚链处理；MOVE 反正会被服务器拒，不会进边）。
- **12 帧上限（`_hold_streak_allows`）→ 无状态时间预算制**：
  ```
  hold 允许 ⇔ round + ETA(cur→terminal) + FP_TAX_RESERVE(50) + RUSH_SAFETY_MARGIN(60) < duration_round
  ```
  预算内一直等（13:22 局需要 62 帧，12 帧上限杯水车薪）；预算耗尽或 must_rush → 放行进边（强通税已预留在账里）。删 mem 流水（无状态化）。
- **对手离开后留卡的处理**：停稳攻坚链已有（PRIORITY_COMBAT_MAIN=130），但 `_break_action`（:132-154）加"一击闸"：`attack < defense` 且对手可增援（未交付且 squad_available>=2）时不出手（半血卡会被远程增援回满，白丢果子还休整 5 帧），改等风化或强通；`attack >= defense` 一击清零（清零卡不可复活，任务书 936）。
- P4h 候选级剔除（hold 时 economy 换目标不饿死）为既有行为，回归用例保住。

## 4. B 削卡战止损（M4，combat.py:214-232）

- state.py 事件解析新增：对手 `SQUAD_REINFORCE` 落地事件（events 已有解析管线，P4k-2 合成窗口同源）→ `state.mem["opp_reinforces"] = True`（本局粘滞）。兜底：我方在削的敌卡防值不降反升同样置位。
- `_propose_squad_weaken` 新增闸：`opp_reinforces && 对手未交付/未退赛 && opp.squad_available >= 2` → 返回 None（消耗战必败：同帧序增援先落地，任务书 1083-1090）。
- 首支削卡照常放行（它就是探针，对手的反应置位标记）。
- 对手已交付/退赛/无兵 → 现逻辑不变（设卡陪练不增援，766 基线不受影响）。

## 5. E 滚动设卡（M6，combat.py，站在 G2/G6 肩上）

G2 已有 camp + set-on-commit（对手踏上进边、我在节点上 → 反手设卡，完成帧落在其半路 = 不可破）。第四刀把它从"单点埋伏"推广为"沿途滚动"：

- 触发：我方停靠在竞争咽喉节点（含处理完任务顺路），且 `对手未过该点`：
  - 对手已在进边上（committed）→ 立即 SET_GUARD（G2 现逻辑）；
  - 对手未 commit 但 `opp_eta(该点) - 我方离开耗时 >= ROLLING_GUARD_MIN_LEAD(默认 20)` 且该点是对手必经（割点判定同 `_opponent_locked` 的拓扑法）→ 也设（等不到 commit 也值得：他到点后要么攻坚耗果子喂我风化时间，要么吃时间税）。
- 约束：在场有效卡 < 2（规则上限）；好果预算 `>= 基础成本+2`（打满防）且不伤交付底仓（好果充裕，13:22 局我方 99 篓）；分差极大且对手仅差悬赏可翻盘时不设（决策记录#3）；RUSH 后仍可设（任务书 1152-1156 未禁）。
- 维持：对手开削 → G3 REINFORCE 顶回（同帧序我方先落地），预算受 `_squad_reserve` 锁死态（=2）约束。
- 优先级：沿用分支 G6 放宽后的设卡优先级；与 economy(110) 的相对序在 M6 实测定夺（滚动卡是过路顺手动作，倾向 112 左右超过经济候选、低于攻坚/削卡）。

## 6. C 被冻逃生实验（M2，timebox ~1h）

- runtime 加 env 探针 `LYCHEE_FROZEN_PROBE=1`：检测到"被卡冻结"（`blocked_by_guard()` && nextNodeId 非空 && 停进度）后，按帧轮发 ①改道 MOVE（segment 起点的其他邻居） ②`FORCED_PASS(next_node)` ③`BREAK_GUARD(next_node)`，记录 actionResults。
- 对局：`python tools/run_match.py --client-cmd "...探针开..." vs adversary_guard`（陪练本就半路关门）。
- 裁决→实装：
  - 改道被受理 → 冻结时若 `绕行代价 < 风化剩余` 提交改道（本图 S09→S08→S10 ≈ 110 帧 < 满防风化 ~165 帧）；
  - FORCED_PASS 被受理 → 若 `时间税+窗口开销 < 风化剩余` 发起强通（PASS 窗口出牌走既有窗口层）；
  - 全被拒 → 结论记档 docs/，不实装（预防层已把此态压为小概率）。

## 7. D 陪练升级（M7，tools/adversary_guard.py）

`--reinforce`：设卡后每帧监视 inquire 里该节点防值，防值较上帧下降且余兵 ≥2 → 发 `SQUAD_REINFORCE`（每帧限 1 个小分队动作），复现 BasicPy 的反应式增援。

## 8. 交互与风险清单

| 交互点 | 结论 |
|---|---|
| P4e 慢边禁令 / 铁律折返判定 | governor 为并列的候选级过滤，无重叠 |
| B2 竞争折扣 | 独立执行，候选须同时过两关 |
| P4h economy 候选级剔除（hold 时） | 保持，回归用例锁定 |
| P4k 护航 MOVE | 只在 state=MOVING 时护航，冻结态 WAITING 不触发，兼容 |
| P4j "不再主动等待"复盘 | hold 是保命等待，方案对齐时已获用户批准加强 |
| RUSH 限制 | SET_GUARD 主车队动作不受禁（1152-1156）；REINFORCE 是小分队动作，RUSH 后既有闸自然禁 |
| 镜像对手 | 只有领先方会设卡，无对称死锁新风险 |
| demo 基线回归 | demo 不竞速不设卡 → governor/hold 均不触发；滚动卡要求"对手必经+领先 20 帧"，demo 局可能触发少量设卡，M7 回归盯总分 |

回退旋钮（模块顶常量）：`CHOKE_LEAD_MARGIN=8`、`FP_TAX_RESERVE=50`、`ROLLING_GUARD_MIN_LEAD=20`、`SQUAD_RESERVE_LOCKED=2`；整层回退=按里程碑 commit revert。
