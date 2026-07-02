# P4e 技术设计

## 改动地图

| 文件 | 改动 | 需求 |
|---|---|---|
| `client/lychee/strategy/safety.py` | 新增 `ahead_of_opponent()`、`hold_before_choke()` 无状态谓词 | R1/R3 |
| `client/lychee/pathing.py` | `guard_max_defense()` 从 combat 迁入（规则常量，共享） | R1 |
| `client/lychee/strategy/delivery.py` | `_pick_move_target` 出口处过 `hold_before_choke` | R1 |
| `client/lychee/strategy/economy.py` | 经济 MOVE 出口同过闸门；`_pick_target` 绕行硬上限；蹲守加 `ahead_of_opponent` 条件 | R1/R2/R3 |
| `client/lychee/strategy/combat.py` | `_guard_max_defense` 改引 pathing；`SQUAD_RESERVE_FOR_WEAKEN` 4→6；`_ahead_of_opponent` 改引 safety | R1/R4 |

## R1 防陷阱闸门

```python
# safety.py
def hold_before_choke(state, next_node) -> bool:
    """停靠时准备进入 next_node 前调用；True = 本帧别提交这个 MOVE。"""
    if not next_node or must_rush(state):        # 时间账吃紧时强行进（保底交付）
        return False
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired:
        return False
    if opp.current_node_id != next_node or opp.next_node_id:   # 对手须停在该节点
        return False
    if opp.guard_action_point < 1:
        return False
    if state.enemy_guard_at(next_node) is not None:  # 已亮卡 → 停稳攻坚链接管，别蹲
        return False
    if state.me.squad_available >= pathing.guard_max_defense(state, next_node):
        return False                              # 兵力足以半路削穿，进边风险可控
    # 咽喉过滤：非咽喉节点对手不值得设卡，避免每个处理站都跟停
    cur = state.me.current_node_id
    for terminal in _terminals(state):
        if next_node in pathing.choke_nodes(state, cur, terminal):
            return True
    return False
```

- **无状态**：对手停在节点上的时长天然有界（它也要赶路）；恶意长蹲由 `must_rush`
  兜底强行进。不引入跨帧 hold 计数器。
- **接线**：delivery `_pick_move_target` 返回 target 前检查，命中返回 ""（本帧无
  MOVE，停靠状态自然 WAIT 心跳）；economy `_propose_economy` 的赶路 MOVE 分支同检查，
  命中返回 None（本帧不提议赶路，但 CLAIM/USE 等原地动作不受影响——等待期照常干活）。
- 优先级不变，不新增 Intent 类型；闸门只是"这帧不提议进边的 MOVE"。

## R2 经济慢边禁令（定案；初版帧数上限已否决）

**否决记录（2026-07-03 归因实验）**：初版"纯绕行 ≤15 帧"上限导致 seed 20260618 从 774 掉到
740——寻路主成本是鲜度、最优主线是水路，S03/S07 大路任务簇对水路基线呈 +15 帧以上"绕行"
被整体误杀，车队改走水路、丢掉大路 3 个冰鉴（鲜度分 163→130）。禁用上限复跑立回 773。
教训：绕行帧数是相对"哪条主线"的度量，主线本身是内生选择，硬上限会锁死路线。

定案：禁的不是"远"，是"为经济目标走慢边"：

```python
SLOW_ROUTE_COEF_LIMIT = 1500   # MOUNTAIN(1780)/BRANCH(1550) 级
# 可行性过滤阶段：
allowed_slow = _path_slow_edges(shortest_path(cur, anchor))   # 交付路径自带的慢边豁免
if _walks_slow_route(cur→spot 或 spot→anchor 走了豁免外的慢边):
    continue
```

本局数据验证：S08 任务自 S07 去程走 E20(MOUNTAIN)、回程走 E17(BRANCH)，均不在交付路径
→ 出局；S03/S07 大路簇、水路候选无慢边 → 保留，路线不翻转（实测 773 恢复）。

## R3 蹲守收紧

```python
# safety.py（combat._ahead_of_opponent 迁入泛化）
def ahead_of_opponent(state, margin=0) -> bool:
    opp = state.opponent
    if opp is None or opp.delivered or opp.retired or not opp.current_node_id:
        return True        # 无在场对手 = 视同领先（蹲守只受时间账约束）
    return my_best_frames + margin < opp_best_frames   # 双方最短路帧数比较
```

economy 蹲守分支：`if me.task_score < 110 and safety.ahead_of_opponent(state) and self._can_linger(...)`。
combat `_ahead_of_opponent` 改为 `safety.ahead_of_opponent(state, GUARD_SETUP_FRAMES)`，
注意语义翻转：原实现"无对手/对手已交付"返回 False（不设卡），迁移后 combat 侧需保留
该行为（设卡对已交付对手无意义）——combat 包装时先判 `opp.delivered/retired → False`。

## R4 侦察保留量

`SQUAD_RESERVE_FOR_WEAKEN = 6`（削穿防御 6 需 6 支）。开局 8 支 → 最多 2 次侦察，
与现网局实际用量一致，不改变既有对局行为，只是把"第 3 次侦察掏空削卡兵力"堵死。

## 风化帧数口径修正（顺带，pathing 已有函数复用）

`combat._guard_weathering_frames` 与 `pathing._guard_weathering_frames` 重复且前者少
age 参数——combat 侧仅用于设卡收益估算（自家卡 age=0），保留不动，本次不合并。

## 回归风险

- 本地 demo 不设卡、始终落后于我方 → R1 闸门在本地对局中永不触发（choke 上对手
  不停靠时直接短路），771/774 基线应无变化。
- R2 使 S08 第二波任务（障碍已清、需真去 S08）出局 → raw 少一档 30 分，但
  TASK_SCORE_GOAL=130 由 S07×4+S10+S03 等顺路任务即可摸到（本局 S07 一站 raw 120），
  预期总分持平或更高（省 22+ 帧 → 鲜度/用时补回）。以 seed 20260618/12345 实测为准。
- R3 在本地对局中：我方全程领先 demo → 蹲守行为不变。
