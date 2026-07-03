# Journal - xichen (Part 1)

> AI development session journal
> Started: 2026-07-02

---



## Session 1: P4 对抗层补全

**Date**: 2026-07-02
**Task**: P4 对抗层补全
**Branch**: `xichen`

### Summary

补齐攻坚破卡、窗口出牌单帧限制、MOVING 小分队削卡兜底；后续记录 B-3 我方设卡、D-2 资源泛化、D-3 天气感知。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `abdb7a7` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: P4 对抗层后续 backlog

**Date**: 2026-07-02
**Task**: P4 对抗层后续 backlog
**Branch**: `xichen`

### Summary

完成主动设卡、资源语义表、马类使用、天气感知路径成本与 HOT 冰鉴阈值，并补充对应单测和 backend strategy contract spec。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a40b2c2` | (see git log) |
| `4f99226` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: P4c resource and card fixes

**Date**: 2026-07-02
**Task**: P4c resource and card fixes
**Branch**: `xichen`

### Summary

Implemented P4c resource valuation, squad scout markers, window card ordering, INTEL gate use, and regression coverage; demo seeds 20260618 and 12345 both scored 774.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4be31b8` | (see git log) |
| `6c46529` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete

## Session: P4e 对抗策略修正

**Date**: 2026-07-03
**Task**: 07-02-07-02-p4e-counter-strategy-fix
**Branch**: `xichen`

### Summary

现网 vs 官方 all-purpose-demo 525:0 完败（looog/match_2751_20260702_214828.jsonl）逐帧复盘：
对手边走边在身后咽喉设满防卡（S10/S11 两张），我方削第一张耗光 8 支小分队，第二张半路
撞上冻结 180 帧（现网被卡形态=MOVING+进度冻结；任务书 8.2 半路禁折返+攻坚需停稳=无兵即
无解），终局未交付。落地四项：①safety.hold_before_choke 防陷阱闸门（无状态，delivery/
economy 进边 MOVE 双接线）；②经济慢边禁令（交付路径外 MOUNTAIN/BRANCH 级不走，用户点名
"别绕山路做任务"）；③落后不蹲守；④侦察保留量 4→6。

### Main Changes

- pathing.py: guard_max_defense 迁入共享
- safety.py: ahead_of_opponent / hold_before_choke
- delivery.py / economy.py: 进边 MOVE 过闸门；慢边禁令；蹲守收紧
- combat.py: 保留量 6、_ahead_of_opponent 包装 safety

### Testing

- [OK] 单测 166 例全绿（新增 18）
- [OK] vs demo seed 20260618/12345 均 773（基线 774±噪声，mountain_rounds=0）
- [OK] vs adversary_guard 陪练 766，100% 交付（=P4d 基线）
- [记录] 归因实验：初版"绕行≤15帧上限"774→740（大路任务簇+3冰鉴被误杀、路线翻转水路），
  禁用复跑 773 定位后改为慢边禁令方案

### Status

[OK] **Completed**


## Session 4: P4k/P4k-2：半路派队掉帧修复 + 窗口对抗本地全盲修复

**Date**: 2026-07-03
**Task**: P4k/P4k-2：半路派队掉帧修复 + 窗口对抗本地全盲修复
**Branch**: `xichen`

### Summary

日志实证未文档化服务器行为：边上单发 SQUAD_* 掉 1 tick(187/187)，arbiter 加护航 MOVE 捆绑免暂停(每局省 2-6 帧)；修复暴露同帧到 S02 的镜像 DOCK 死锁，追查出本地裁判 contests 只发空壳→state 事件流合成窗口、delivery/economy 补 CONTESTING 忙闸、protocol 牌字段自适应(现网 card 实证/本地 exe 旧 schema)；本地 exe 实测不收任何客户端 WINDOW_CARD，窗口对抗验证=单测+现网，陪练 --depart-delay 1 错峰。回归 demo 772/设卡陪练 766 全持平，单测 230。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4132e5c` | (see git log) |
| `f394527` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
