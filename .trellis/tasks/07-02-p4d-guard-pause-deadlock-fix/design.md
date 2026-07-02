# P4d 守卫半路自锁死锁修复 设计

## Boundaries

只改策略层（`combat.py`、`economy.py` 接线）、新增 `strategy/safety.py`、新增调测工具
`tools/adversary_guard.py` 与对应单测。`GameState`/`Intent`/arbiter/`runtime.py` 契约不动。
所有动作仍走 propose→merge 流程，不绕过 arbiter。

## 服务器行为模型（本设计的事实基础，来自 looog/1 实证）

对手对我方 `next_node_id` 指向的节点 SET_GUARD 时，服务器把我方移动自动暂停：

| 字段 | 半路暂停时的值 | 真停靠节点时的值 |
|---|---|---|
| `me.state` | `WAITING` | `IDLE` 或 `WAITING` |
| `me.move_direction` | `PAUSED` | 非 `PAUSED` |
| `me.next_node_id` | 保留（非空） | `""`（state.py:206 注释「停靠时空串」） |
| `edge_progress_ms` | 冻结 | — |

暂停期间发 `BREAK_GUARD` → `MOVING_ACTION_FORBIDDEN`（服务器视同 MOVING，任务书 8.2）。
守卫清零（削卡/风化）后服务器自动恢复移动，客户端无需补发 MOVE。

## 改动 1：攻坚闸门（combat.py `_propose_break_guard`）

现状 `combat.py:71`：`state.my_state() not in _STATIONARY_STATES`，而
`_STATIONARY_STATES = {"IDLE", "WAITING"}`（combat.py:21）放行了半路 WAITING。

修法：保留 `_STATIONARY_STATES`（真停靠的 WAITING——经济层 WAIT 蹲守、等 RUSH 开门——
仍是合法攻坚时机），在其后追加「真站在节点上」判据：

```python
if me.next_node_id or me.move_direction == "PAUSED":
    return None   # 半路（含被守卫暂停）：攻坚非法，让位空心跳/削卡
```

两个条件互为兜底：`next_node_id` 非空即在边上；`move_direction == "PAUSED"` 防御
「暂停时服务器字段组合有变体」的情况。不改 `_guarded_next_hop` 及攻坚投料逻辑。

## 改动 2：削卡放宽（combat.py `_propose_squad_weaken`）

现状 `combat.py:161`：`if me.state != "MOVING" or not me.next_node_id: return None`。
被暂停成 WAITING 后削卡熄火，只剩风化。

修法：把状态判据从「MOVING」放宽为「在边上朝守卫推进（含被暂停）」：

```python
en_route = bool(me.next_node_id) and (
    me.state == "MOVING" or me.move_direction == "PAUSED")
if not en_route:
    return None
```

后续逻辑不变：`needed = ceil(guard.defense / 2)`，`squad_in_flight >= needed` 才停手，
`squad_available < 2` 资源闸保留。defense 随削卡落地逐帧下降，needed 同步收敛，
直至 defense 归零、服务器自动恢复移动（预期个位数帧清完）。

同帧行为组合（暂停期间）：主车队动作无产出 → 空心跳（合法）；小分队动作 = SQUAD_WEAKEN
持续补派。arbiter 类别互不冲突。

## 改动 3：「送达优先」硬约束（新增 `strategy/safety.py`）

### 判定

```python
RUSH_SAFETY_MARGIN = 60   # 帧。覆盖：削卡等待+验核读条+处理中断重来+暂停损耗+抖动。
                          # 经济层候选级 ENDGAME_MARGIN=40 更宽松（它按含回程的精确账算），
                          # 全局硬闸是最后防线，取更保守值；P5 自对弈可再调。

def frames_to_terminal(state) -> int:
    # 半路（含暂停）：剩余边帧数 + 从 next_node_id 起的最短路；
    # 停靠：从 current_node_id 起的最短路。
    # 路径帧用 pathing.path_frames（已含沿途处理读条），不建模守卫（余量覆盖）。

def must_rush(state) -> bool:
    return state.round + frames_to_terminal(state) + RUSH_SAFETY_MARGIN >= state.duration_round
```

无状态每帧重算（不做迟滞锁存：触发边界来回抖动最多让个别帧多/少一个候选提案，
经济层自身的候选账仍在，无实害；无状态实现最简单、可测性最好）。
`frames_to_terminal` 的半路剩余帧复用 `combat._eta_to_path_index` 同款算式
（`ceil((edge_total_ms - edge_progress_ms) / pathing.BASE_MOVE_PER_FRAME)`），
提取进 safety 以免两处漂移。

### 接线（谁让路、谁保留）

| 提案 | must_rush 时 | 理由 |
|---|---|---|
| economy `_propose_economy`（任务/冰鉴候选 + WAIT 蹲守） | 关 | 绕路/刷分/蹲守全停 |
| economy 冰鉴使用 `_propose_ice_use` | 留 | 交付要求鲜度>0，1 帧成本保住交付有效性 |
| economy 马匹/情报使用 | 留 | 加速移动/缩短验核，反而助攻直奔终点 |
| combat `_propose_set_guard` | 关 | 4 帧架设+果子成本，纯刷分 |
| combat `_propose_break_guard` / `_propose_squad_weaken` | 留 | 只打终点路径上的卡（`_guarded_next_hop` 已保证），是送达的一部分 |
| combat `_propose_squad_scout` | 留 | 探路预标记缩短沿途处理（P4c），助攻送达 |
| combat 窗口出牌 | 留 | 独立动作类别，不占主车队帧 |

接线点：`economy.propose` 在 `_propose_economy` 调用处加闸（其余 use 类提案不动）；
`combat.propose` 在 `_propose_set_guard` 调用处加闸。delivery 不动（本来就直奔终点）。

## 改动 5（实施中追加，对应 R5）：主车队清障（combat.py `_propose_clear_obstacle`）

事实基础（复现局实证）：S10 开局挂 LANDSLIDE，`nodeStates[].hasObstacle=true`，
MOVE 进入被拒 `TARGET_NOT_REACHABLE`；历史局是官方 demo 做 T04 顺手清掉的（r227）。
规则（任务书 2.4.4 / 5.2 动作表）：清除手段 = 主车队 `CLEAR`（1 好果 + 6 帧读条）/
小分队清障（2 支，延迟清）/ T04 / `FORCED_PASS`（付时间税不清障）。

实现：与攻坚同构的主车队动作提案——真停靠（复用改动 1 的三重闸：非处理中、
_STATIONARY_STATES、next_node_id 空且非 PAUSED）且 `_terminal_path` 下一跳
`has_obstacle` 时提交 `{"action": "CLEAR", "targetNodeId": path[1]}`，优先级
PRIORITY_COMBAT_MAIN（仲裁压制 delivery 的 MOVE，被拒 spam 根本不会发生）。
提案顺序：break_guard > clear_obstacle > set_guard（前两者是活命动作，不受 must_rush 闸）。

**不做小分队清障**：削一次卡耗 2 支降 2 防，8 支初始人手刚好够削一个 6 防 KEY_PASS
守卫；清障有 6 帧成本的主车队兜底，人手必须全留给削卡（半路暂停时唯一快清手段）。
P5 自对弈若证明 6 帧值得再加。

## 改动 4：设卡对手（新增 `tools/adversary_guard.py`，不入提交 ZIP）

复用 `client/lychee` 包（net/protocol/runtime/state/pathing），自定义一个 Strategy：

1. **选点**：start 后计算对手起点→终点最短路上第一个 KEY_PASS 咽喉
   （`pathing.choke_nodes`），CLI `--guard-node` 可覆盖（本图即 S10，实测自动选中）。
2. **赶路**：把 DeliveryStrategy 的 `_terminals` 偷换成设伏点（子类 CamperDelivery），
   MOVE/PROCESS/绕行反馈全继承；到点后因 verified=False 永不交付、自然蹲守。
   途中下一跳有障碍时 ObstacleClearer 发主车队 CLEAR（否则陪练自己先卡死在 S10 障碍前）。
3. **设伏**：蹲守待对手 `next_node_id == 目标节点`（debug-visibility=full 可见）的当帧发
   `SET_GUARD`（extraGoodFruit=2 → 6 防）→ 精确复现「半路暂停」；设卡只按 actionResults
   受理结果计数（被拒不烧次数）；守卫被清后若对手仍在逼近则补设，上限 `--max-guards`
   默认 1 = 现网死局忠实复现（8 支小分队物理上削不掉两个 6 防守卫，默认 2 会造无解局）。
4. 铁律沿用 Runtime：每帧必回、round 对齐。

挂法：`python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --demo-cmd "python tools/adversary_guard.py {player_id} {host} {port}" --no-ui`

## 单测设计（client/tests）

- `test_combat.py` 新增：
  - 半路暂停帧（WAITING + PAUSED + next_node_id 非空 + 目标有敌卡）→ 无 BREAK_GUARD 意图；
  - 同状态 → 产出 SQUAD_WEAKEN，且在途达 `ceil(defense/2)` 后停手；squad_available<2 不派；
  - 真停靠（next_node_id=""、非 PAUSED）+ 邻点敌卡 → BREAK_GUARD 照常（防回归）；
  - must_rush 时 `_propose_set_guard` 不产出。
- 新增 `test_safety.py`：frames_to_terminal 停靠/半路两分支；must_rush 边界（差 1 帧两侧）。
- `test_economy.py` 新增：must_rush 时任务/冰鉴候选与 WAIT 关闭、冰鉴使用仍在。

单测拟合状态的构造方式沿用现有 test_combat 的 GameState 装配惯例。

## 兼容与回滚

- 改动 1/2 是纯收紧/放宽单函数闸门，互相独立，可单独 revert。
- 改动 3 是新增模块 + 两处调用点，闸门常量置 `RUSH_SAFETY_MARGIN = 0` 即近似退化为原行为。
- 改动 4 纯工具，零线上风险。
- 风险点：暂停态字段组合若在正式服与调测包不一致（如 move_direction 取值差异），
  改动 1 的双条件闸与改动 2 的 en_route 判据都以 `next_node_id` 为主判据兜底。
