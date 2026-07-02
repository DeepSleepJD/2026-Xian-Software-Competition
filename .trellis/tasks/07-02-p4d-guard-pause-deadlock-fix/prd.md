# P4d 守卫半路自锁死锁修复 PRD

## 背景（败因已确证，无需重新分析）

2026-07-02 现网最新 4 局全输，其中 3 局荔枝未送达。日志：`looog/1`。

根因链条（诊断结论，判别因子：对手不设卡的 match3 我方畅通送达，设卡的三局全部冻死）：

1. 对手在 S10（KEY_PASS）`SET_GUARD` 时，我方正走在 S08→S10 支线半路（edgeProgress=465‰）；
2. 服务器把移动自动暂停：`state=WAITING` / `moveDir=PAUSED` / 进度冻结，`nextNodeId` 保留；
3. 客户端把「半路暂停」误判为「停稳可攻坚」，从 r300 起连发 134 帧 `BREAK_GUARD`，
   全部被判 `MOVING_ACTION_FORBIDDEN`（非法动作，还累计扣分）；
4. 同时 `SQUAD_WEAKEN` 只认 `state=="MOVING"`，被暂停成 WAITING 后唯一能快速清卡的手段熄火；
5. 守卫只能等自然风化（GUARD_WEATHERING 6→0），我方被钉死 ~190 帧（移动冻结占全局 22%），
   破关一次没命中 → 超时未送达 → 输。

## 需求

### R1（P0）攻坚合法性闸门 —— 修 `combat._propose_break_guard`

「半路 PAUSED 的 WAITING」不是可攻坚状态。攻坚只有真站在节点上才合法，需加闸：
`me.next_node_id == ""` 且 `me.move_direction != "PAUSED"`（字段见 `state.py:206/209`）。
修后半路暂停帧不得再产出 `BREAK_GUARD`（发空心跳合法推进）；真停靠节点时的攻坚能力不得回归。

### R2（P0）削卡放宽 —— 修 `combat._propose_squad_weaken`

现状只在 `state=="MOVING"` 才派队。需放宽到「被守卫拦停的半路 PAUSED」也持续派队：
只要 `next_node_id` 指向敌方有效守卫且小分队够用，就按 `ceil(defense/2)` 补足在途派遣，
直到 defense 归零（几帧内清完，替代 134 帧干等风化）。

### R3（P1）「送达优先」全局硬约束（兜底）

任何时刻若「已用帧数 + 到终点预计帧数 + 安全余量 > 总帧数（durationRound，默认 600）」，
立即放弃一切绕路/刷分/设卡，直奔终点。挡在终点路径上的守卫仍可攻坚/削卡（那是送达的
一部分）。这条硬约束要能独立兜住本次三局非送达（即使 R1/R2 之外再出现新的耗帧 bug）。

### R4（P1）设卡对手回归工具

本地现有陪练（官方 demo / 自身）不会在 S10 设卡，死锁场景无法复现，改完无从验证。
需要一个脚本化设卡对手（挂 `tools/run_match.py --demo-cmd`），能在我方半路上边时对咽喉
KEY_PASS 设卡，确定性复现「半路暂停」场景。

### R5（P0，实施中发现追加）道路障碍清除能力

复现局实证（2026-07-02）：S10 开局即挂 LANDSLIDE 障碍（任务书 2.4.4：障碍开局生成、
阻挡 MOVE 进入、不清不消）。历史 771 局全靠官方 demo 做 T04 顺手清障（r227 消失）；
对手不清障时我方 MOVE 永拒 `TARGET_NOT_REACHABLE`（339 帧 spam 到终局）→ 未送达。
与守卫死锁同级别的「咽喉被堵→永久卡死」缺陷，且现网任何不做 T04 的对手都会触发。
要求：交付路径下一跳有障碍且真停靠时提交主车队 `CLEAR`（6 帧 + 1 好果）。
不用小分队清障（2 支/次）——人手全留给削卡（8 支只够削一个 6 防守卫）。

## 验收标准（2026-07-02 全部达成）

- [x] 单测：`cd client && python -m unittest discover -s tests` 全绿（148 例 = 原 131 + 新增 17）。
- [x] 新增单测覆盖：①「WAITING + PAUSED + next_node_id 非空」时不得产出 BREAK_GUARD；
      ②同状态下对 next_node_id 的敌方守卫持续产出 SQUAD_WEAKEN 直至在途数达 `ceil(defense/2)`；
      ③真停靠节点（next_node_id 空、非 PAUSED）时攻坚照常（防回归）；④must_rush 触发/不触发
      的判定与各策略让路行为；⑤障碍清除（提案/仲裁压制 MOVE/半路不发/无障碍不发）。
- [x] 对局（设卡对手 `tools/adversary_guard.py`）：我方 **766 分、100% 交付（r495）**；
      `MOVING_ACTION_FORBIDDEN` = 0；PAUSED 冻结仅 ~10 帧（现网死局为 ~190 帧）；
      BREAK_GUARD 违规发送 0 次；r268 对手半路设卡 → r272/273/277 三发 SQUAD_WEAKEN 清掉。
      对照组（修复 stash 掉重跑）：卡死未送达、80 分——复现与修复因果闭环。
- [x] 对局（demo 回归）：seed 20260618 与 12345 均 **774 分、100% 交付**（P3 基线 771）。

## 硬性约束（违反即输，同 CLAUDE.md）

- 每帧必发 action（空 `actions:[]` 也是心跳）；连续 60 帧缺动作 = 退赛判负。
- `action.round` == 当前 `inquire.round`；决策 500ms/帧内完成。
- 不写死 playerId / host / port / 阵营 / 地图；S10 只是本图实例，判定一律走
  节点类型/字段（KEY_PASS、moveDirection、nextNodeId），不 hardcode 节点 ID。

## 非目标

- 不改 `runtime.py`（锁定文件）、不改 GameState/Intent/arbiter 契约。
- 不做「半路倒车/反向撤退」机制（服务器是否支持未知，不引入投机行为）。
- 不重新调设卡（SET_GUARD）自身的价值模型；只加送达优先闸。
- 设卡对手是调测工具，不入提交 ZIP、不追求对局强度。

## 复盘输入

- 日志：`looog/1`；项目记忆 `lychee-competition-status.md`；CLAUDE.md「当前进度」P4 节。
- 规则依据：任务书 8.2（MOVING 不能攻坚）、6.3.1（攻坚限相邻节点当帧结算）。
