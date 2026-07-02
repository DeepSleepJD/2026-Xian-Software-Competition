# P1：client/ 骨架搭建——600 帧不掉线 + 寻路交付

## Goal

按已批准的架构（`docs/客户端架构设计.md`）搭建 `client/` 参赛客户端骨架，达成 P1 阶段目标：

1. **里程碑 1（必达）**：注册 → ready → 心跳循环，600 结算帧不掉线（永不退赛铁律生效）。
2. **里程碑 2**：解析 start/inquire 全字段为 GameState，冻结 GameState/Intent 接口契约。
3. **里程碑 3**：最短路寻路 + 主线交付状态机（移动/处理/验核/交付），单机 100% 交付，分数对齐官方 demo 基准（461/500）。

## Requirements

- 目录结构、模块职责、数据流严格按 `docs/客户端架构设计.md`（本任务 design.md 基准）。
- Python 3.12 stdlib，零第三方依赖。
- 入口 `client/main.py <playerId> <host> <port>`，附 `start.sh`（比赛提交要求）。
- framing 移植官方 `refs/official-base-clients/player-base-client/python-client/lychee_basic_client/framing.py`（5 位十进制长度前缀）。
- 协议字段以 `refs/debug-kit-v1/` 通信协议文档 + start/inquire 样例消息为准，逐字段核对。
- recorder 每帧收发落盘 jsonl（复盘 + 回归数据源）。

## 硬性约束（违反即输，铁律层保证）

- 每帧必发 action（空 `actions:[]` 也是心跳）；连续 60 帧缺动作 = 退赛判负。
- `action.round == inquire.round`。
- 决策 500ms/帧内完成（预算 ~400ms 留余量）。
- 不写死 playerId/host/port/阵营/地图，一切以 start/inquire 下发为准。

## Acceptance Criteria

- [ ] `python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}"` 起局，我方客户端全程 600 帧在线（data.csv 出分且 online=TRUE），无退赛判负。
- [ ] GameState/Intent 契约定稿并有 start/inquire 样例消息驱动的单元测试（不碰 socket）。
- [ ] 主线交付跑通：对打官方 demo，我方 100% 交付，得分 ≥ 461（demo 基准），力争 ≥ 500。
- [ ] 铁律层验证：策略层人为抛异常/超时的情况下客户端仍不掉线（发空心跳）。
- [ ] recorder 产出完整对局 jsonl。

## Notes

- 战略背景：`docs/比赛分析与取胜策略.md`；P2-P5（经济/优化/对抗/调参）不在本任务范围。
- 本地调测约束见 CLAUDE.md（不用官方 test.bat，统一走 tools/run_match.py）。
