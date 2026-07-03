# P4j 蹲守波次感知 + 稀缺冰竞争实现文档

> 定稿：2026-07-03。自包含实现文档，可直接交给实施 agent。
> 背景：10:37/10:38 现网两连败（732:750 / 722:767，日志 `looog/match_2751_20260703_1037{20},1038{29}.jsonl`）逐帧尸检。两局败因互不相同且都不在 P4i（小分队优化，另一 agent 实施中）范围内。
> 范围：**改动 A（蹲守重构：行军优先 + 波次感知 + 终局差额模式）+ 改动 B（稀缺冰鉴竞争三小刀）**。全部落在 `client/lychee/strategy/economy.py` + `safety.py` 一个公开访问器。
> 与 P4i 的关系：改动文件不同（P4i 主改 combat.py + economy 只加 `current_plan` 暴露），合并无冲突；若 P4i 已合入，economy `__init__` 里会多一行 `self.current_plan`，不影响本文档任何锚点。

---

## 0. 一句话

局 1 输在 economy 蹲守在错误的地点白等 25 帧（S13 刷新波争夺各差 18/13 帧，不蹲即赢 762:750）；局 2 输在全场 0 冰鉴（鲜度 124:163，-39 分）而冰竞争没有任何"稀缺时要争"的建模。蹲守要懂刷新波和终局差额，冰鉴要懂"0 库存时的真实边际"。

## 1. 败因证据（两局尸检）

### 1.1 局 1（103720）732:750 vs litchi-agent（山路流）——差一个 15 分任务

最终分解：我 240+162+178+140(raw 105)+12 = 732；对手 240+141+174+180(raw 180)+15 = 750。raw 105 距 110 档差 5 分，结算差 30 分（105→140 vs 120→170）。

决定性时间线：

| 帧 | 事件 |
|---|---|
| r241 | 我在 S09 完成第 4 任务（T_007，raw 105），此后无候选 |
| r246-271 | **economy 蹲守 WAIT 25 帧**（raw 105<110 + ahead_of_opponent 为真——对手还在 S08→S10 半路，其到终点帧数更长） |
| r269-271 | 对手落地 S10 → ahead_of_opponent 翻转 → 蹲守闸关闭 → r270 用快马 r271 动身 |
| r360 / r400 | **任务刷新波**在 S13 落 T_019（15 分）/ T_022（15 分）（波次周期 40，实例带 refreshRound 字段） |
| r423 / r428 | 身位领先 30-70 帧的对手顺路吃掉两个（其 raw 已 180 封顶、这些对它值 0 分——路过就吃，客观拒止） |
| r441 | 我到 S13，**各差 18/13 帧**，空手 |
| r494 | 交付，剩 106 帧未用（此时 S09/S10 的无主任务折返超 600 帧，确实不可达） |

反事实：不蹲那 25 帧 → r416 到 S13 → T_019 到手 → raw 120 → 结算 +30、交付提前 25 帧（用时 +3）→ **约 765:750 翻盘**。

蹲守的双重失败模式：①蹲的时候：下一波在 r280-360（34+ 帧外），且 S09 不是当波落点——**等不到货还付了等待成本**；②走了以后：整条 S10-S13 走廊全是任务候选节点，**行军穿过走廊本身就是最好的"蹲守"**，出发晚 25 帧输掉走廊里全部刷新争夺。

重要负结论（防实施跑偏）：**"蹲到下一波再走"不是正解**——若 r246 在 S09 蹲到 r280 波（34 帧），该波落点 S03/S04/S08 均不在 S09，白等更久、S13 更晚到、输得更多。正解是**行军优先**：只有"波次临近（≤15 帧）且脚下就是候选节点"才值得蹲。

### 1.2 局 2（103829）722:767 vs "5"（大路流）——0 冰鉴 = -39 鲜度分

最终分解：我 240+124(鲜度 68.96)+171+180+7 = 722；对手 240+163(90.64)+171+180+13 = 767。任务双满 180，胜负全在鲜度与用时。

| 帧 | 事件 |
|---|---|
| r82 | 对手领 **S03 冰鉴**（我 r85 才到 S03 做 T_001，差 ~5 帧被截胡） |
| r163 / r177 | 对手领 **S07 冰鉴** + S07 短马（我已回头走水路 S04/S05，S07 不可达） |
| r243 / r245 | 对手领 S09 快马+官凭（我 r308 才到 S09，晚 65 帧——S05→S09 长边 64 帧+水路处理 13 帧） |
| 全场 | 对手扫走 6 个资源、用 2 冰 2 马；**我全场 1 短马、0 冰** |

机制归因：①S03 失冰后**无 fallback**——S06 支线冰被慢边禁令（`SLOW_ROUTE_COEF_LIMIT`）硬杀 + P3"第 3 冰实亏"结论（那是持 2 冰状态的账，0 冰状态不成立）；S07 冰要放弃水路，被 B2 竞争折扣压制（对手更近即打折/出局→系统性让渡）。②冰鉴估值恒 18 分，不知道"0 库存时第一个冰"的真实边际 ≈ 22-25 分（+10 鲜度=+18 再加免 1-2 次十位阈值好果转坏，每次 ≈3.6 分双重损失）。

日志统计脚本见 `docs/P4i-小分队人手利用优化实现文档.md` §1（同一工具）。

## 2. 规则与机制依据

- 任务刷新：波次落地，同波实例共享 `refreshRound`（公开字段，state.py L356/375 已解析为 `Task.refresh_round`）；本局观测波次 r360/r400，周期 40。**未来波次不预发布**，只能由已见波次外推。
- 得分：鲜度分 `floor(鲜度/100×180)` 每点 ≈1.8 分；用时分每帧 ≈0.117；里程碑 60/90/110 → +15/+35/+50（`economy._task_points` L93 已实现）。
- 鲜度阈值：每首次跌破十位阈值 1 好果转坏（双重损失 ≈3.6 分）；冰鉴 +10 鲜度上限 100。
- 对手公开总分：`Player.total_score`（state.py L231/272 已解析）；对手交付后其分数冻结且公开可见。
- 交付后限制：已交付队伍不能再领资源/完成任务/获得悬赏（任务书 1.3）→ 对手交付后所有竞争解除（B2 已处理候选侧；蹲守闸门侧本文档补齐）。

## 3. 现状代码定位（行号为定稿快照）

| 位置 | 现状 | 缺陷 |
|---|---|---|
| economy.py L294-303 蹲守分支 | `raw<110 && safety.ahead_of_opponent && _can_linger` 则 WAIT | 对刷新波零感知（等不到货也蹲）；对走廊候选零感知（行军更优也蹲）；对手交付后差额可知但不用 |
| economy.py L504 `_can_linger` | 只查"现在动身能否赶上截止" | 保留，作为所有蹲守的硬底线 |
| safety.py L76 `ahead_of_opponent` | 按双方到终点帧数比位次 | 保留；蹲守新增"对手从未设卡"放宽（P4e"落后不蹲"是防设卡型对手的，对刷任务型对手过严） |
| safety.py L126-142 `_hold_memory`/`_observe_enemy_guard` | hold 专用的"本局见过对手设卡"记忆 | 复用：加公开访问器给 economy |
| economy.py L38 `ICE_BOX_VALUE=18.0`、L594 `_resource_value` | 冰鉴恒 18 分 | 不区分持冰状态，0 冰时低估 |
| economy.py L417 `_contest_factors` | 对手 ETA 更近即打折/出局（B2b） | 对稀缺不可替代资源（冰）系统性让渡，对手双吃 |
| economy.py L495 `_walks_slow_route` + L349 | 经济候选走交付路径外慢边即出局（P4e） | 把 0 冰状态下净值为正的支线冰也硬杀 |

## 4. 改动 A：蹲守重构（行军优先 + 波次感知 + 终局差额模式）

### 4.1 新常量（economy.py）

```python
LINGER_WAVE_WINDOW = 15       # 普通蹲守：下一波预计 ≤15 帧才值得等（≈3 分等待成本上限）
LINGER_WAVE_GRACE = 3         # 波次落地后再看 3 帧（同波任务进 feed 的抖动），没货立刻走
LINGER_DEFICIT_WINDOW = 45    # 终局差额模式：放宽到等满一个波次周期
DEFICIT_LINGER_MAX = 40       # 差额 ≤40（≈一个 30 任务的跨档结算）才值得等，更大追不回
WAVE_MIN_SAMPLES = 2          # 至少见过 2 个不同波次才做外推，否则不预测（=不蹲）
```

### 4.2 波次追踪与预测（economy 实例状态）

`__init__` 增加 `self._seen_waves: set[int] = set()`。每帧（`propose()` 开头，`_read_feedback` 之后）：

```python
for t in state.tasks:
    if t.refresh_round > 0:
        self._seen_waves.add(t.refresh_round)
```

预测器：

```python
def _next_wave_round(self, state: GameState) -> int | None:
    waves = sorted(self._seen_waves)
    if len(waves) < WAVE_MIN_SAMPLES:
        return None
    period = min(b - a for a, b in zip(waves, waves[1:]) if b > a)
    nxt = waves[-1]
    while nxt <= state.round:
        nxt += period
    return nxt
```

说明：波次间隔本图恒 40，取最小正差分即周期（若同波多实例 refreshRound 相同，set 已去重）。晚期波次可能不再产新任务（池耗尽），预测只用于"值不值得等"，落空由 GRACE 兜底立刻走（见 4.4 状态机）。

### 4.3 脚下是否候选节点

蹲守只在"当前节点可能接到新任务"时有意义。`state.task_candidates`（templateId → 候选节点列表，start 帧下发，state.py L569）已有：

```python
def _is_task_candidate_node(self, state: GameState, node_id: str) -> bool:
    return any(node_id in nodes for nodes in state.task_candidates.values())
```

（可选强化：排除"已知不会再刷"的模板——不做，波次落点本就随机，GRACE 兜底即可。）

### 4.4 蹲守分支重写（economy.py L294-303）

现状：

```python
if target is None:
    if me.task_score < 110 and safety.ahead_of_opponent(state) \
            and self._can_linger(state, cur):
        return Intent(..., actions=[{"action": "WAIT"}], note="蹲守任务刷新")
    return None
```

重写为：

```python
if target is None:
    if self._should_linger(state, cur):
        return Intent(kind="economy", priority=PRIORITY_ECONOMY,
                      actions=[{"action": "WAIT"}], note="蹲守任务刷新")
    return None
```

```python
def _should_linger(self, state: GameState, cur: str) -> bool:
    me = state.me
    if not self._can_linger(state, cur):          # 硬底线：截止前必须送得到
        return False
    if not self._is_task_candidate_node(state, cur):
        return False                              # 脚下接不到新任务：行军穿走廊就是最好的蹲守
    nxt = self._next_wave_round(state)
    if nxt is None:
        return False
    wait = nxt - state.round
    opp = state.opponent
    opp_delivered = bool(opp and opp.delivered)

    # 终局差额模式：对手已交付、分数冻结可见，差多少一目了然
    if opp_delivered and me.task_score < TASK_SCORE_GOAL:
        deficit = opp.total_score - self._projected_score(state)
        if 0 < deficit <= DEFICIT_LINGER_MAX and wait <= LINGER_DEFICIT_WINDOW + LINGER_WAVE_GRACE:
            return True
        return False    # 已领先：立即交付锁定胜局，蹲守只会流失鲜度/用时

    # 普通模式：只为 110 档蹲（110 后边际 ≤10 抵不过等待成本，P3 结论不变）
    if me.task_score >= 110:
        return False
    if wait > LINGER_WAVE_WINDOW + LINGER_WAVE_GRACE:
        return False                              # 波次太远：走，走廊前方还有候选节点
    if not (safety.ahead_of_opponent(state)
            or not safety.opponent_ever_set_guard(state)):
        return False    # 落后且对手是设卡型才禁蹲（P4e 原判罚对刷任务型对手过严）
    return True
```

语义要点：
- **wait ≤ window + GRACE 隐含了"波次落地后没货立刻走"**：波次落地帧 W 起，`_next_wave_round` 返回 W+period（远超 window）→ 蹲守自动关闭；落地后 GRACE 帧内新任务若进了 feed，`_pick_target` 会直接选中（根本不走蹲守分支）。无需显式状态机。
- 局 1 回放验证（本文档验收标准之一）：r246 @S09，waves={..., 240}，next=280，wait=34 > 15+3 → **不蹲，立刻行军** → S13 r~416 < r423 → T_019 到手。
- 局 1 终局：r473 @S14（S14 非任务候选节点）→ 不蹲 → 照常交付。若当时在 S13 且预测波 r440 差额 18 → 蹲到 r443，落空立刻走——两个方向都正确。

### 4.5 投影分估算

```python
def _projected_score(self, state: GameState) -> int:
    """按当前状态即刻动身交付的最终分保守估计（对手已交付场景用）。"""
    me = state.me
    eta = state.round + safety.frames_to_terminal(state)
    time_left = max(0, state.duration_round - eta)
    raw = me.task_score
    time_score = (time_left * 70 // state.duration_round) * min(raw, 90) // 90
    fresh = max(0.0, me.freshness - safety.frames_to_terminal(state) * 0.07)
    return (240 + _task_points(raw) + int(me.good_fruit / 100 * 180)
            + int(fresh / 100 * 180) + time_score)
```

精度要求 ±10 即可（决策阈值 DEFICIT_LINGER_MAX=40 有余量）；0.07/帧是全路型鲜度损耗的保守均值（HOT 时低估差额 → 更愿意蹲，方向安全）。验收：对局 1 终帧状态回算 ≈732±10。

### 4.6 safety.py 公开访问器

```python
def opponent_ever_set_guard(state: GameState) -> bool:
    mem = _hold_memory(state)
    _observe_enemy_guard(state, mem)
    return bool(mem.get("guard_ever_seen"))
```

复用 hold 的 WeakKeyDictionary 记忆（L126-142），零新状态。注意它按 GameState 实例弱引用——economy 与 safety 在同一帧收到同一 state 实例，语义一致。

## 5. 改动 B：稀缺冰鉴竞争三小刀（都在 economy.py）

### 5.1 B-1：0 库存冰鉴的边际加价

新常量 `ICE_ZERO_STOCK_BONUS = 6.0`（0 冰时第一个冰 ≈ 18 + 免 1-2 次阈值转坏 ≈3.6×1.5）。

`_resource_value`（L594）内：

```python
if resource_type == "ICE_BOX" and state.me.resources.get("ICE_BOX", 0) < 1:
    value += ICE_ZERO_STOCK_BONUS
```

（`_resource_value` 现无 state 参数则加传；调用点在 `_candidates` L579，state 在手。）

### 5.2 B-2：B2 竞争折扣的稀缺冰例外

新常量 `ICE_CONTEST_TOLERANCE = 5`（帧）。`_contest_factors`（L417）循环内、打折判定之前：

```python
if cand.key.endswith(":ICE_BOX") and me_ice == 0 and map_ice_left <= 2 \
        and to_frames <= opp_eta + ICE_CONTEST_TOLERANCE:
    continue        # 稀缺冰：ETA 劣势 ≤5 帧仍全价争夺，宁白跑一次领取也不让它双吃
```

其中循环外预计算：

```python
me_ice = state.me.resources.get("ICE_BOX", 0)
map_ice_left = sum(ns.resource_stock.get("ICE_BOX", 0)
                   for ns in state.node_states.values())
```

B2a 锁定检测（对手读条中）**不豁免**——已在领的抢不回来，白跑无意义。劣势 >5 帧仍按原折扣/出局（无望的争夺照旧放弃）。

### 5.3 B-3：慢边禁令的 0 冰豁免

`_pick_target` 可行性过滤（L349）现状：

```python
if self._walks_slow_route(state, cur, spot, anchor, allowed_slow):
    continue
```

改为：

```python
if self._walks_slow_route(state, cur, spot, anchor, allowed_slow) \
        and not self._slow_route_exempt(state, cand):
    continue
```

```python
@staticmethod
def _slow_route_exempt(state: GameState, cand: _Target) -> bool:
    """0 冰状态下冰鉴候选豁免慢边硬禁令，放行给净值账（DETOUR_COST_PER_FRAME）裁决。
    P3"S06 第 3 冰实亏"是持 2 冰的账；0 冰时 +24 值 − 118 帧×0.12≈14 成本 = 净 +10。"""
    return cand.key.endswith(":ICE_BOX") \
        and state.me.resources.get("ICE_BOX", 0) < 1
```

豁免只解除**硬禁令**，净值/截止/竞争折扣照算——酷暑等极端下净值转负会自然放弃。风险与旋钮见 §9。

## 6. 明确不做（范围外，防实施扩散）

- **行军节奏对齐波次**（刻意放慢/加速让到达簇节点卡在波次后）：收益不确定、易与送达优先打架，留 P5 自对弈评估。
- **N3 完整同点剥夺 EV 建模**（对手资源优先策略的全资源竞争预判）：本文档只做冰鉴专项。
- 马匹/文书的竞争例外、INTEL 复活、FORCED_PASS：不动。
- P4i 范围（combat.py 小分队）：不碰；若同期合入仅共享 economy `__init__` 一行，无逻辑交叉。

## 7. 单测清单（test_economy.py / test_safety.py 追加）

改动 A：
1. 波次预测：喂 refresh_round∈{240,280} 的任务 → `_next_wave_round`：r246 时 =320；r321 时 =360；只见 1 个波次 → None。
2. **局 1 回归（核心用例）**：raw 105、脚下 S09 为候选节点、waves={200,240}、r246（wait=34）→ 不蹲（提案为 None，不含 WAIT）。
3. 正例：同上但 r308（wait=12 ≤ 15+3）且 ahead → 蹲。
4. 落地即走：r321 波落空无新任务 → wait 变 39 → 不蹲。
5. 非候选节点不蹲：S14/S15 类节点即使 wait=5 → 不蹲。
6. 先验放宽：落后（ahead=False）+ 对手从未设卡 → 可蹲；对手设过卡（safety 记忆置位）→ 不蹲。
7. 终局差额：对手 delivered、total_score 使 deficit=18、raw<130、wait=38 ≤ 45+3 → 蹲；deficit=-5 → 不蹲；deficit=60 → 不蹲。
8. `_projected_score`：构造局 1 终帧近似状态（raw105/fresh90/good99/r473）→ 732±10。
9. `safety.opponent_ever_set_guard`：见卡前 False / 见卡后 True / 卡风化消失仍 True。
10. 硬底线：`_can_linger` False（截止吃紧）时任何模式都不蹲。

改动 B：
11. 0 冰时 ICE 候选 value=24.0，持 1 冰 =18.0。
12. B2 例外：ICE 候选、me 0 冰、图剩 2 冰、我 ETA 劣 4 帧（含对手朝向为真）→ factor 1.0；劣 6 帧 → 原折扣逻辑；持 1 冰 → 原折扣逻辑；对手读条中该冰（B2a）→ 仍出局。
13. 慢边豁免：0 冰时经支线（BRANCH 系数 1550）取冰的候选不被硬杀、进入净值比较；持 1 冰同路径 → 被杀；0 冰但候选是任务 → 被杀。

## 8. 回归验证方案

跑法一律 `python tools/run_match.py`：

| 对局 | 通过线 | 重点观察 |
|---|---|---|
| vs demo `--seed 20260618` / `12345` | ≥768、100% 交付 | 蹲守行为变化不应掉分（demo 局 raw 早满，蹲守本就少触发） |
| vs 设卡陪练 `tools/adversary_guard.py` | ≥757、100% 交付 | 对手设卡后 `opponent_ever_set_guard`=True → 落后禁蹲照旧 |
| vs 山路陪练 `tools/adversary_racer.py` | ≥755 且胜 | racer 抢任务场景下新蹲守不应多蹲 |

日志观察项（下次现网/陪练局，用 P4i 文档 §1 脚本改造统计）：
- 我方连续 WAIT ≥10 帧的段：每段必须能对应"预测波次 ≤18 帧内且脚下是候选节点"或"终局差额模式"，否则是回归；
- 我方冰鉴领取数 ≥1（对手非扫货流时应为 2）；
- 我方 raw ≥110 的局占比上升（这是改动 A 的最终目的）。

## 9. 调参旋钮与回滚

- 蹲守：`LINGER_WAVE_WINDOW`（15，调小更激进行军）、`DEFICIT_LINGER_MAX`（40）、`LINGER_DEFICIT_WINDOW`（45）。整体回滚 = `_should_linger` 换回旧三条件表达式。
- 冰：`ICE_ZERO_STOCK_BONUS`（6.0）、`ICE_CONTEST_TOLERANCE`（5；若现网出现连续白跑领冰，降 3）、B-3 若在酷暑局出现支线深绕，先把豁免加条件 `map_ice_left>0 且绕行帧 ≤130`，再不行整刀回滚（删豁免即恢复 P4e 行为）。
- 三小刀互相独立，可单独回滚。
