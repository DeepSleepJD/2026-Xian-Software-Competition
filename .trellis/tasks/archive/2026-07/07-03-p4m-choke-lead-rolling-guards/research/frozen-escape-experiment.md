# M2 被冻逃生实验结论（2026-07-03）

## 实验设置

- 场景：vs `tools/adversary_guard.py`（半路关门陪练），seed 20260618。
- 探针：`client/lychee/strategy/frozen_probe.py`（`LYCHEE_FROZEN_PROBE=1` 时 main.py 注册、
  且不注册 CombatStrategy 防削卡拆卡关闭冻结窗口）。
- 冻结复现：r272 陪练在 S10 设卡（def 6），我方 S09→S10 边上 449‰ 处进度冻死。

## 冻结形态勘误（第三变体）

本地陪练局冻结形态 = `state=MOVING + moveDirection=FORWARD + 进度不再推进`（P4e 现网同款）；
1-2 帧后沉降为 `WAITING + PAUSED`。加上现网 13:22 的 `WAITING + FORWARD + next 保留`，
冻结检测必须覆盖三变体，统一判据：**在边上（nextNodeId 非空）且下一跳有敌方有效卡**。

## 三动作裁决（tools/logs/client_1001.log [PROBE] 行）

| 帧 | 动作 | 裁决 |
|---|---|---|
| r273 | BREAK_GUARD→S10 (good=2,bad=1) | 无效（actionResults 记为 WAIT 被拒 MOVE_BLOCKED_BY_GUARD；防值无变化。与 P4d MOVING_ACTION_FORBIDDEN 结论一致） |
| r274 | FORCED_PASS→S10 | **明确拒绝 `MOVING_ACTION_FORBIDDEN`** —— 强通只能从停稳节点发起，半路冻结不可用 |
| r275 | 改道 MOVE→S07（本段起点 S09 的其他邻居） | **受理**，r276 当帧离开冻结态（state=MOVING cur=S09 next=S07），旧边进度作废、新边从 0 走 |

## 结论

1. **改道 MOVE 是半路被卡冻结的唯一且有效逃生舱**（任务书 4.2 条款实证）：13:22 现网被钉
   193 帧期间每帧都可脱困。实装进 delivery：冻结检测 → 比较"改道绕行/等风化"EV → 提交改道。
2. FORCED_PASS / BREAK_GUARD 在冻结态彻底不可用，只能从停稳节点发起——强化 M3 hold 闸门
   的价值（停在节点上才保有攻坚/强通两个主动选项）。
3. 附带观察：探针局里客户端（无 combat 层）停稳在卡前节点时会每帧重发 MOVE 被拒刷屏
   （r404-449），无害但难看；正式构建由攻坚/削卡接管，不处理。
