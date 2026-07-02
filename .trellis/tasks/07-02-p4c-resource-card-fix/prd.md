# P4c 资源利用与出牌修正

## Goal

按照 `docs/P4c-资源利用与出牌修正实现文档.md` 落地 P4c 修正：恢复 seed 20260618 demo 分数回归，真实化资源估值，利用小分队探路获取确定性 tempo 收益，并重构窗口出牌成本顺位与对手反制。

## Confirmed Facts

- P4 前两轮已处理破卡、设卡、窗口出牌、削卡兜底、天气、马匹；本轮聚焦审查遗留项。
- 当前经济层给 `INTEL`、`PASS_TOKEN`、`OFFICIAL_PERMIT` 较高领取价值，但旧代码缺少稳定消费路径，造成绕路领取亏帧。
- 规则要求文书只能在提交 `YAN_DIE` 时由系统自动消耗，主动 `USE_RESOURCE` 文书会白扣。
- 小分队人手当前主要用于削卡兜底，应新增探路预标记但保留削卡预算。
- 本轮不做 `SQUAD_CLEAR`、`SQUAD_REINFORCE`、`FORCED_PASS`、天气逻辑改动、寻路改动。

## Requirements

- A. 调整 `client/lychee/strategy/economy.py` 资源估值：
  - `PASS_TOKEN` / `OFFICIAL_PERMIT` 改为 `1.0`。
  - `INTEL` 改为 `0.5`。
  - 保留冰鉴、马匹、船权现有消费者价值。
  - 若资源是当前交付路径上处理点的 `required_resource_types`，候选领取时临时按硬需求抬高价值，避免换图缺关键资源。
- B. 在 `client/lychee/strategy/combat.py` 新增小分队探路预标记：
  - 沿 `_terminal_path` 寻找最近 `process_round >= 4` 的前方处理节点。
  - ETA 不超过 40 帧，目标无本队有效标记且无未超时在途订单。
  - 保留至少 4 点人手给削卡兜底。
  - `SQUAD_WEAKEN` 优先级高于 `SQUAD_SCOUT`。
  - 自建本队标记台账，使用 `SCOUT_MARKER_ADD`、`SCOUT_MARKER_EXPIRE`、`SCOUT_MARKER_CONSUME` 维护。
- C. 重构窗口出牌：
  - 默认成本顺位为 `BING_ZHENG` -> `YAN_DIE` -> `XIAN_GONG` -> `ABSTAIN`。
  - RUSH 阶段或 `GATE` / `PASS` 窗口允许护卫行动点花到 0，其余场景保留 1 点。
  - 文书数量按 `PASS_TOKEN + OFFICIAL_PERMIT` 计算，出 `YAN_DIE` 不主动发 `USE_RESOURCE`。
  - 从 `WINDOW_CARD_REVEAL` 事件维护对手明牌计数，对手 `BING_ZHENG` 倾向时优先用 `XIAN_GONG` 反制。
- E. 增加 `USE_RESOURCE` 白名单防误用：
  - 经济层主动资源使用只允许 `{ICE_BOX, FAST_HORSE, SHORT_HORSE, INTEL}`。
  - 任何文书主动 `USE_RESOURCE` 应在策略层被阻断或测试覆盖。
- 可选低风险项：
  - 修正 `_break_action` 坏果过杀。
  - 若协议字段清晰且实现风险低，加入脚下 `INTEL` 标记使用；否则保持估值低并不实现。

## Acceptance Criteria

- [x] `cd client && python -m unittest discover -s tests` 通过。
- [x] 新增/更新单测覆盖资源幻影价值、硬需求资源抬价、小分队 scout ETA/去重/预算/weaken 优先、窗口出牌顺位/YAN_DIE/兵正倾向/RUSH 花点、`USE_RESOURCE` 白名单。
- [x] `python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --no-ui --seed 20260618` 总分不低于 771。
- [x] 同命令 `--seed 12345` 总分不低于 771。
- [x] 不硬编码节点 ID、资源分布或处理帧数；读取 `state.process_nodes`、节点状态、资源库存。
- [x] 不改变本轮明确排除的天气、寻路、`SQUAD_CLEAR` / `SQUAD_REINFORCE` / `FORCED_PASS` 范围。

## Source

- Primary handoff: `docs/P4c-资源利用与出牌修正实现文档.md`
- Background: `docs/P4-对抗层改动清单.md`
