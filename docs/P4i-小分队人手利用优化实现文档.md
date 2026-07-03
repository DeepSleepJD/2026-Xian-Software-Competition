# P4i 小分队人手利用优化实现文档（自适应保留量 + 探路扩面与时机修正）

> 定稿：2026-07-03。自包含实现文档，可直接交给实施 agent。
> 范围：**只做改动 1（自适应保留量+RUSH 前清仓）和改动 2（探路扩面+派出时机修正）**。
> 改动 3（小分队清障）、改动 4（远程先手削卡）**未批准，明确不做**，见 §6。

---

## 0. 一句话

小分队 8 支人手是会过期的资源（RUSH 阶段禁止新提交，未用即作废），现网四局每局只兑现 ~2 帧价值；本改动把静态"留 6 支防设卡"改为按对手行为自适应，并把探路从"终点路径 2 个点、派太早会过期"扩到"任务节点 + 全部途经处理点 + 宫门验核，落地窗口精确化"。

## 1. 败因证据（现网日志，looog/）

四场现网局（07-03 00:13 与 09:13 各两局，全败）中我方（playerId 2751）小分队使用**完全相同**：

| 局 | 我方小分队动作 | 结果 |
|---|---|---|
| 全部四局 | r3-4 SQUAD_SCOUT→S02；r32-33 SQUAD_SCOUT→S04 | 仅 2/8 人手，剩 6 支闲置至终局 |
| match_2751_20260703_091349 | S02 标记 r44-47 APPLY+CONSUME（S02 TRANSFER 4→2，省 2 帧）；**S04 标记 r39 落地、r85 EXPIRE 作废**（45 帧有效期内主车队未到达登船） | 全系统净收益 ≈ 2 帧 ≈ 0.4 分 |
| match_2751_20260703_091330（局 1，727:750 负） | 同上；对手 2696 **全场从未设卡** | 我方留的 6 支削卡预备队全程零目标 |

对照组——赢我们 750:727 的对手 2696 的用法（同局日志 SQUAD_DISPATCH 事件）：

| 帧 | 动作 | 效果 |
|---|---|---|
| r2 | SQUAD_CLEAR→S08（complete r14） | 自己路线上的障碍，主车队到达前远程清除，零停顿 |
| r87 | SQUAD_CLEAR→S10（complete r101） | 同上 |
| r191 | SQUAD_CLEAR→S11（complete r198） | 同上 |
| r419 | SQUAD_SCOUT→S14（complete r421） | 宫门验核 6 帧→3 帧，直接换交付时间分 |

7/8 人手全部转化为帧数。（它的 SQUAD_CLEAR 打法属于改动 3 范围，本次不做；引用只为证明"人手花掉才有价值"。）

日志统计复用脚本（分析时实际用过，可直接改文件名跑）：

```python
import json
fn = 'looog/match_2751_20260703_091349.jsonl'
with open(fn, encoding='utf-8') as fh:
    for line in fh:
        if 'SQUAD' not in line and 'SCOUT_MARKER' not in line:
            continue
        obj = json.loads(line)
        md = obj.get('msg', {}).get('msg_data', {})
        for ev in md.get('events') or []:
            t = ev.get('type', '')
            if 'SQUAD' in t or 'SCOUT' in t:
                p = ev.get('payload', {})
                print(md.get('round'), t, p.get('playerId'), p.get('targetNodeId'),
                      p.get('action'), p.get('completeRound'), p.get('expireRound'))
```

## 2. 规则依据（任务书）

- **3.4 小分队**：每队初始 8 人手，**不补充**；每帧最多提交 1 个小分队动作；SQUAD_SCOUT 耗 1 人，SQUAD_CLEAR/REINFORCE/WEAKEN 各耗 2 人。人手不足动作被拒不扣人手。
- **6.4 小分队行动**：可派范围**无距离上限**；延迟 `min(15, max(3, ceil(D/3)))`，D = 到目标的 Chebyshev 距离（`max(|dx|,|dy|)`，停靠时从当前节点算，移动中从本段路线起点算）；提交后天气变化不重算；在途小分队不占本帧提交名额。
- **2.5 天气**：山雾命中探路时延迟 +2 帧，仍不超过 15。
- **6.4.1 探路标记**：处理帧数 −3、最低 2，适用于领资源、**处理皇榜任务**、**宫门验核**、主车队清障、通用处理；第 X 帧生成的标记 X~X+45 帧可用，X+46 清理；同点不叠加，一次处理消耗最早 1 个标记。
- **6.5 宫宴冲刺**：RUSH 触发（第 390-449 帧满足条件即触发，450 帧必触发）后**禁止新提交小分队动作**，在途的继续落地。→ 未花掉的人手在 RUSH 后是死资源。

处理帧数参考值（**来自现网局 start 帧，比赛会换地图，代码一律读下发的 `processNodes`/`taskTemplates`，不得写死**）：

| 固定处理点 | 帧数 | 探路省 | 任务 | 帧数 | 探路省 |
|---|---:|---:|---|---:|---:|
| S02 TRANSFER | 4 | 2 | T01/T06 | 3 | 1（不值） |
| S04 BOARD | 7 | 3 | T02/T08/T11 | 4 | 2 |
| S05 WATER_TRANSFER | 6 | 3 | T12/T13/T14 | 5 | 3 |
| S11 PASS_TRANSFER | 5 | 3 | T04 | 6 | 3 |
| S13 PALACE_TRANSFER | 5 | 3 | 资源领取 | 2 | 0（已是下限） |
| S14 VERIFY（宫门） | 6 | 3 | | | |

## 3. 现状代码与缺陷定位

涉及文件：`client/lychee/strategy/combat.py`（主改）、`client/lychee/strategy/economy.py`（暴露目标）、`client/main.py`（接线）。行号为定稿时快照，以当前代码为准。

| 位置 | 现状 | 缺陷 |
|---|---|---|
| combat.py L31 `SQUAD_RESERVE_FOR_WEAKEN = 6` | 恒留 6 支给削卡 | 对手不设卡时 6 支全废（09:13 局 1 实证）；RUSH 后规则性作废 |
| combat.py L29 `SCOUT_ETA_MAX = 40` | ETA≤40 就派 | 标记落地后仅活 45 帧，途中做任务一耽搁即过期（S04 实证） |
| combat.py L30 `SCOUT_PENDING_TIMEOUT = 8` | 在途去重仅 8 帧 | 最大延迟 15 帧，扩面后远目标（如 S14）在途中会被重复派、双倍扣人 |
| combat.py L215 `_propose_squad_scout` | 目标集=终点路径上 `process_round≥4` 的处理点 | 漏任务节点（当前主战场）、economy 目标；S14 常因 RUSH 时序错过 |
| combat.py L197 `_propose_squad_weaken` / L215 scout | 无 phase 闸 | RUSH 中提交必被拒（规则 6.5），白占动作与日志 |
| economy.py | 不对外暴露当前经济目标 | combat 无从得知"我们正要去哪个任务节点" |

`_propose_squad_scout` 现状全文（重写基准）：

```python
def _propose_squad_scout(self, state: GameState) -> Intent | None:
    me = state.me
    if me.squad_available - 1 < SQUAD_RESERVE_FOR_WEAKEN:
        return None
    cur = me.current_node_id
    if not cur:
        return None
    path = self._terminal_path(state, cur)
    if not path or len(path) < 2:
        return None
    for idx, node_id in enumerate(path[1:], start=1):
        proc = state.process_nodes.get(node_id)
        if proc is None or proc.process_round < SCOUT_MIN_PROC_FRAMES:
            continue
        prefix = path[:idx + 1]
        if self._eta_to_path_index(state, prefix) > SCOUT_ETA_MAX:
            continue
        if self._has_scout_marker(state, node_id) or self._has_pending_scout(state, node_id):
            continue
        self._scout_pending[node_id] = state.round
        action = {"action": "SQUAD_SCOUT", "targetNodeId": node_id}
        return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_SCOUT,
                      actions=[action], note=f"小分队探路@{node_id}")
    return None
```

## 4. 改动 1：自适应保留量 + RUSH 前清仓

### 4.1 常量（combat.py，替换 L31）

```python
SQUAD_RESERVE_EARLY = 4      # 开局：对手是否设卡型未知，留 4（2 波削卡）
SQUAD_RESERVE_RELAXED = 2    # 对手 150 帧仍未设卡：行为先验降档（同 P4h N1 思想）
SQUAD_RESERVE_GUARDER = 6    # 对手设过卡（粘滞）：留满削穿一张满防 6 的卡
SQUAD_RELAX_ROUND = 150
SQUAD_SPEND_ALL_ROUND = 350  # RUSH 至迟 450、常见 390 触发；350 起清仓避免作废
```

原名 `SQUAD_RESERVE_FOR_WEAKEN` 若有测试引用，保留为 `SQUAD_RESERVE_GUARDER` 的别名或同步改测试。

### 4.2 对手设卡粘滞检测

`__init__` 增加 `self._opponent_ever_set_guard = False`；`_read_events(state)` 里每帧调用：

```python
def _observe_opponent_guard(self, state: GameState) -> None:
    if self._opponent_ever_set_guard:
        return
    my_team = state.my_team_id or state.me.team_id
    for ns in state.node_states.values():
        guard = ns.guard
        if guard and guard.owner_team_id and guard.owner_team_id != my_team \
                and (guard.active or guard.defense > 0):
            self._opponent_ever_set_guard = True
            return
```

粘滞语义：见过一次即永远视为设卡型（卡会风化消失，但对手"会设卡"这个行为先验不消失）。

### 4.3 保留量函数

```python
def _squad_reserve(self, state: GameState) -> int:
    if self._opponent_ever_set_guard:
        return SQUAD_RESERVE_GUARDER      # 注意：设卡型对手 350 后也不清仓——
                                          # 现网 all-purpose-demo r364 晚设卡是 525:0
                                          # 败局主因，保留量就是为它买的保险
    if state.round >= SQUAD_SPEND_ALL_ROUND:
        return 0
    if state.round >= SQUAD_RELAX_ROUND:
        return SQUAD_RESERVE_RELAXED
    return SQUAD_RESERVE_EARLY
```

`_propose_squad_scout` 的保留闸从 `me.squad_available - 1 < SQUAD_RESERVE_FOR_WEAKEN` 改为 `me.squad_available - 1 < self._squad_reserve(state)`。语义不变：派出后剩余人手不得低于保留量。

### 4.4 RUSH 闸（规则 6.5 正确性修复）

`_propose_squad_weaken` 和 `_propose_squad_scout` 开头都加：

```python
if state.phase == "RUSH":
    return None
```

削卡逻辑除这一行外**一字不动**（削卡本身不受保留量约束，它就是保留量服务的消费者）。

## 5. 改动 2：探路扩面 + 派出时机修正

### 5.1 economy 暴露当前经济目标（economy.py）

- `__init__` 增加：`self.current_plan: tuple[str, int] | None = None`，语义 `(停靠/处理节点 id, 处理帧数)`。
- `_propose_economy`（L292-293 附近）在 `target, spot = self._pick_target(state, cur)` 之后：

```python
self.current_plan = (spot, target.proc_frames) if target is not None else None
```

- `propose()` 的 must_rush 分支（L231 `eco = None if safety.must_rush(state) else ...`）：must_rush 命中时 `self.current_plan = None`（送达优先时不再引导探路去经济点）。
- **刻意保留的语义**：移动/读条中 `propose()` 早退不更新 `current_plan`——它保持"上次停靠时选定、正在赶去"的目标，这正是 combat 需要在途派探路的时机。目标有效性由 combat 侧 ETA 窗口自证，不需要 economy 侧失效通知。

### 5.2 接线（main.py L44）

```python
economy = EconomyStrategy()
strategies=[CombatStrategy(economy=economy), DeliveryStrategy(), economy],
```

combat 侧用鸭子类型持有，**不 import EconomyStrategy**（避免循环导入）：

```python
def __init__(self, economy=None) -> None:
    ...
    self._economy = economy
```

读取处 `plan = getattr(self._economy, "current_plan", None)`。现有测试 `CombatStrategy()` 无参构造不受影响（economy=None → 候选集 B 整体关闭）。

### 5.3 延迟估算（combat.py 新增）

```python
@staticmethod
def _squad_delay(state: GameState, cur: str, target: str) -> int:
    a, b = state.nodes.get(cur), state.nodes.get(target)
    if a is None or b is None:
        return 15
    d = max(abs(a.x - b.x), abs(a.y - b.y))
    return min(15, max(3, ceil(d / 3)))
```

规则 6.4 原式。`cur` 停靠时=当前节点、移动中=本段起点，而客户端里移动中 `me.current_node_id` 就是本段起点（`_eta_to_path_index` 已依赖此语义），直接传 `me.current_node_id` 即可。山雾 +2 不建模（只影响下界余量，SCOUT_LAND_MARGIN 已覆盖）。

### 5.4 `_propose_squad_scout` 重写

常量变更：

```python
SCOUT_ETA_MAX = 25           # 40→25：落地后 45 帧有效期需覆盖途中做任务的时刻表滑移
SCOUT_GATE_ETA_SLACK = 45    # 宫门特判上界 = delay + 45（标记有效期的数学上界）
SCOUT_LAND_MARGIN = 2        # 落地须早于到达至少 2 帧
SCOUT_PENDING_TIMEOUT = 16   # 8→16：覆盖最大延迟 15，防远目标在途重复派
```

重写后逻辑：

```python
def _propose_squad_scout(self, state: GameState) -> Intent | None:
    me = state.me
    if state.phase == "RUSH":
        return None
    if me.squad_available - 1 < self._squad_reserve(state):
        return None
    cur = me.current_node_id
    if not cur:
        return None

    candidates: list[tuple[int, str]] = []      # (eta, node_id)
    seen: set[str] = set()

    # 候选集 A：终点路径上的固定处理点（原逻辑，窗口收紧）
    path = self._terminal_path(state, cur)
    if path and len(path) >= 2:
        for idx, node_id in enumerate(path[1:], start=1):
            proc = state.process_nodes.get(node_id)
            if proc is None or proc.process_round < SCOUT_MIN_PROC_FRAMES:
                continue
            candidates.append((self._eta_to_path_index(state, path[:idx + 1]), node_id))
            seen.add(node_id)

    # 候选集 B：economy 正在赶去的经济目标（任务处理 ≥4 帧才值得）
    plan = getattr(self._economy, "current_plan", None)
    if plan:
        spot, proc_frames = plan
        if spot not in seen and proc_frames >= SCOUT_MIN_PROC_FRAMES:
            spot_path = pathing.shortest_path(state, cur, spot)
            if spot_path and len(spot_path) >= 2:
                candidates.append((self._eta_to_path_index(state, spot_path), spot))

    # 统一过滤 + 择近派出
    best: tuple[int, str] | None = None
    for eta, node_id in candidates:
        if self._has_scout_marker(state, node_id) or self._has_pending_scout(state, node_id):
            continue
        delay = self._squad_delay(state, cur, node_id)
        eta_cap = delay + SCOUT_GATE_ETA_SLACK if self._is_gate_like(state, node_id) \
            else SCOUT_ETA_MAX
        if not (delay + SCOUT_LAND_MARGIN <= eta <= eta_cap):
            continue
        if best is None or eta < best[0]:
            best = (eta, node_id)
    if best is None:
        return None
    node_id = best[1]
    self._scout_pending[node_id] = state.round
    action = {"action": "SQUAD_SCOUT", "targetNodeId": node_id}
    return Intent(kind="combat.squad", priority=PRIORITY_SQUAD_SCOUT,
                  actions=[action], note=f"小分队探路@{node_id}")
```

宫门判定：

```python
@staticmethod
def _is_gate_like(state: GameState, node_id: str) -> bool:
    if node_id == state.roles.gate_node_id:
        return True
    proc = state.process_nodes.get(node_id)
    return bool(proc and proc.process_type == "VERIFY")
```

### 5.5 设计要点与已知歧义

- **窗口数学**：派出帧 E=eta 时落地在 `now+delay`、到达在 `now+eta`，标记覆盖落地后 45 帧 → 过期约束 `eta - delay ≤ 45`。普通点收紧到 `eta ≤ 25`（留 ≥23 帧时刻表滑移余量，S04 过期案例的滑移 ≥12 帧）；**宫门取满上界 `eta ≤ delay+45`**——RUSH 触发即永久禁提交（390-450 随时落锤），晚派没机会、早派会过期，只能贴上界抢跑（对照组对手 r419 派 S14 即此打法）。
- **候选集 B 的 eta 复用 `_eta_to_path_index`**：该 helper 对"目标是处理点"会扣除目标自身处理帧（到达即开始处理的口径），任务节点不在 `process_nodes` 时即纯路程帧数，两者语义都正确。
- **已知歧义（不做代码规避，回归时观察）**：规则 6.4.1"处理帧数 −3 最低 2 并消耗最早 1 个标记"未明说零收益处理（如 2 帧资源领取）是否也消耗标记。若实测会被无收益消耗，代价 1 人手，扩面后可承受；观察项见 §8。
- 同帧 ≤1 小分队动作的仲裁、削卡优先于探路（`propose()` L62-66）均不动。

## 6. 明确不做（范围外，防实施扩散）

- **SQUAD_CLEAR 开局远程清障**（改动 3）：涉及 T04 任务分权衡，未批准。主车队 CLEAR 兜底逻辑（P4d）不动。
- **远程先手削卡**（改动 4）：未批准。被动削卡（`_propose_squad_weaken`）除 RUSH 闸外一字不动。
- **INTEL 领取复活**：`_resource_has_claim_consumer` 对 INTEL 返回 False 的现状不动。
- **SQUAD_REINFORCE**：继续不用。

## 7. 单测清单（test_combat.py 追加；沿用现有 fixture 风格）

1. **保留量曲线**：r100 未见敌卡→4；r200 未见→2；r360 未见→0；任意帧见过敌卡→6，且敌卡风化消失后仍 6（粘滞）。
2. **保留闸生效**：available=5、reserve=4 → 可派（5-1≥4）；available=4、reserve=4 → 不派。
3. **RUSH 闸**：phase="RUSH" 时 weaken 与 scout 均不提议（weaken 场景用 P4d 半路 PAUSED fixture 改 phase 复测）。
4. **窗口下界**：eta < delay+2 不派（如同节点相邻、eta=3、delay=3）。
5. **窗口上界**：普通处理点 eta=26 不派、eta=25 派；宫门 eta=delay+45 派、eta=delay+46 不派、且 eta=40>25 也派（放宽生效的正例）。
6. **候选集 B**：注入 stub economy（`current_plan=("SX", 5)`）且 eta 合窗 → 派 SX；`current_plan=("SX", 2)` → 不派；未注入 economy → 行为同旧目标集（现有用例回归）。
7. **择近**：A、B 两候选同时合窗 → 派 eta 小者。
8. **pending 16 帧**：派出后 +10 帧同目标不重复派、+17 帧后可重派。
9. **economy.current_plan**（test_economy.py）：选中目标帧 =(spot, proc_frames)；无候选帧 =None；must_rush 帧 =None。

## 8. 回归验证方案

跑法一律 `python tools/run_match.py`（CLAUDE.md 本地调测约定）：

| 对局 | 命令要点 | 通过线 |
|---|---|---|
| vs 官方 demo | `--seed 20260618` 与 `--seed 12345` 各一局 | 我方 ≥768、100% 交付 |
| vs 设卡陪练 | `tools/adversary_guard.py`（P4d） | ≥757、100% 交付、被卡后仍能削穿+破卡 |
| vs 山路陪练 | `tools/adversary_racer.py`（P4g） | ≥755 且分数高于对手 |

**设卡陪练是本改动最大风险点**：陪练设卡发生在我方半路上边时，此前我方可能已按 EARLY=4 花掉 3-4 支探路，削卡预算从 6 变 4-5（差额靠攻坚果子补）。若回归掉分，按 §9 旋钮逐档回退。

日志观察项（server replay / recorder 输出，用 §1 脚本统计）：

- 我方 `SCOUT_MARKER_EXPIRE` 次数 = 0（时机修正的直接验证）；
- 非设卡对手局：我方 `SQUAD_SCOUT` 派出 ≥4 次、终局 `squadAvailable ≤ 2`；
- 全局无 SQUAD 类动作被拒（尤其 RUSH 段，验证 phase 闸）；
- `SCOUT_MARKER_CONSUME` 对应的处理是否为 ≥4 帧处理（验证 §5.5 歧义：若发现被 2 帧领取无收益消耗，记录频次，下轮再决定是否规避）。

## 9. 调参旋钮与回滚

- 行为全部由 5 个常量控制：`SQUAD_RESERVE_EARLY / RELAXED / GUARDER`、`SQUAD_RELAX_ROUND`、`SQUAD_SPEND_ALL_ROUND`，以及窗口 `SCOUT_ETA_MAX / SCOUT_GATE_ETA_SLACK / SCOUT_LAND_MARGIN / SCOUT_PENDING_TIMEOUT`。
- 设卡陪练回归掉分 → `SQUAD_RESERVE_EARLY` 4→5→6 逐档回退（6 即恢复旧保留行为）。
- 探路出现新的过期浪费 → `SCOUT_ETA_MAX` 25→20。
- 完全回滚 = EARLY/RELAXED/GUARDER 全 6 + `SCOUT_ETA_MAX` 回 40 + 去掉候选集 B，即近似旧行为；RUSH 闸与粘滞检测是纯正确性修复，无回滚理由。
