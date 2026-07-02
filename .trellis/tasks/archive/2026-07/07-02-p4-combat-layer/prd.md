# P4 对抗层补全

## Goal

按 `docs/P4-对抗层改动清单.md` 的 P0 项补齐第 6 章“拦截与突破”的最小可战实现，避免现网再因敌方在必经关隘设卡而长时间停机，并让窗口争夺不再全程弃权。

## Confirmed Facts

- 任务书 6.3.1：`BREAK_GUARD` 只能打当前节点相邻节点上的敌方有效设卡；无额外处理帧，成功清零，失败削防并休整 5 帧。
- 任务书 8.2：`MOVING` 只允许等待、继续当前移动、马类资源或疾行令，不能攻坚；因此必须在提交 `MOVE` 进入边之前识别目标节点守卫。
- 通信协议动作字段：`BREAK_GUARD` 需 `targetNodeId`，可带 `goodFruit` / `badFruit` / `rushTactic`；`WINDOW_CARD` 必须带 `contestId` + `card`。
- 当前代码只有 `DeliveryStrategy` 与 `EconomyStrategy`，`client/main.py` 未接入 combat 策略；`arbiter` 支持按主车队/窗口类别仲裁，窗口出牌可与主动作同帧并存。
- `GameState.ActionResult.error_code` 已解析，`Event` 尚未直接暴露 `errorCode`；`Guard` / `Contest` / `Bounty` 数据结构已存在。

## Requirements

1. **状态层暴露对抗信息**：为策略提供我方状态、敌方有效设卡、上一帧守卫阻挡、我方未结算窗口、护卫行动点/好果/坏果等便捷查询。
2. **攻坚破卡优先于 MOVE**：当我方停在相邻节点且下一跳有敌方有效设卡时，提交 `BREAK_GUARD`，坏果优先、好果补足；优先级必须压过 economy/delivery 的 `MOVE`。
3. **上边前阻止 MOVING 陷阱**：任何策略准备向敌方有效设卡节点 `MOVE` 时，本帧不得让该 `MOVE` 进入最终动作；应由 combat 改提攻坚或等待。
4. **窗口出牌最小可战**：每帧最多对一个本方参与且未结算的相关窗口提交带全字段的 `WINDOW_CARD`；关键窗口优先争，鲜度足够时优先 `XIAN_GONG`，否则使用有限护卫点 `BING_ZHENG`，相关但无资源才显式 `ABSTAIN`。
5. **寻路支持关隘分析和设卡代价**：新增非硬编码的必经点分析；路径代价在遇到敌方有效设卡时加入破卡/等待成本，使策略能自然权衡绕行与破卡。
6. **经济层振荡防护**：已在途或刚选定目标时，不因微小净值变化频繁改目标；避免需要立即原路折返的目标，除非收益显著覆盖边成本。
7. **MOVING 被后设卡兜底**：当主车队已经在路上且 `nextNodeId` 出现敌方有效设卡时，使用独立小分队额度提交最小版 `SQUAD_WEAKEN`，避免只能等自然风化。

## Acceptance Criteria

- [ ] 合成单测覆盖 `enemy_guard_at("S10")`、`blocked_by_guard() == "S10"`、`my_open_contests()`、资源便捷属性。
- [ ] 合成场景 IDLE@S09、S10 敌卡 defense=6、我方 2 坏果时，`CombatStrategy` 产出 `BREAK_GUARD{targetNodeId:S10,badFruit:2,goodFruit:0}`。
- [ ] 当 delivery/economy 同时产出 `MOVE S10` 时，仲裁结果保留 combat 的 `BREAK_GUARD`，不保留该 `MOVE`。
- [ ] 有相关本方窗口时每帧最多产出 1 个合法 `WINDOW_CARD`，且带 `contestId` 与 `card`；鲜度>=80 且好果充足时使用 `XIAN_GONG`。
- [ ] MOVING 且下一节点存在敌方有效设卡时，`CombatStrategy` 产出 `SQUAD_WEAKEN{targetNodeId: nextNodeId}`，并在足够小分队已在途时停止重复派遣。
- [ ] `pathing.choke_nodes()` 在样例图上识别通往终点的必经点，不硬编码 S10。
- [ ] `cd client && python -m unittest discover -s tests` 全绿。

## Out of Scope For This Iteration

- 主动设卡 B-3 的完整净值模型。
- 小分队探路、清障、主动增援与完整削卡调度；本轮只做 MOVING 被后设卡时的最小 `SQUAD_WEAKEN`。
- 天气感知 D-3 与资源语义泛化 D-2 的完整估值重构。
- 陪练客户端与整局对打验收可在 P0 单测绿后作为下一次集成任务继续。

## Open Questions

- 无阻塞产品问题。先按清单的 P0 最小可战范围实现，B-3/D-2/D-3/E 另开后续迭代。
