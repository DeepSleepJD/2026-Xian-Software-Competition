# P1 技术设计

> **基准文档：`docs/客户端架构设计.md`**（2026-07-02 负责人批准）。目录结构、分层职责、GameState/Intent 契约、铁律层、三人分工均以该文档为准，本文件只记录 P1 落地时的补充决策，不重复正文。

## P1 实施范围与顺序

架构文档六大模块中，P1 按依赖序实施：

1. **net.py + runtime.py + main.py**（里程碑 1）：TCP framing（移植官方件）+ 主循环 + 铁律兜底。此时 protocol 只需最小解析（识别消息类型 + round 号），策略层可以是"恒发空 actions"的占位。
2. **protocol.py + state.py**（里程碑 2）：start/inquire 全字段 → GameState；Intent 数据类 + arbiter 首版。此步冻结契约。
3. **pathing.py + strategy/delivery.py**（里程碑 3）：图/最短路 + 交付状态机。
4. recorder.py 随里程碑 1 一起上（后续步骤都靠它产回归数据）。

## 补充决策

- **铁律实现方式**：主循环单线程同步收发；每帧处理入口 `try/except` 全包 + 时间预算检查（策略计算超 ~400ms 直接放弃本帧意图，发已算出的部分或空心跳）。不引入多线程看门狗——单线程在 50ms/帧的本地环境和 500ms 上限下足够，且避免竞态复杂度。若后续实测有超时风险再升级。
- **占位策略**：里程碑 1 的 strategy 层用 `NoopStrategy`（返回空 Intent 列表），保证骨架先跑通再填肉。
- **测试数据源**：`refs/debug-kit-v1/start消息.json`、`inquire消息.json` 作为 protocol/state 单测夹具；recorder 录制的真实对局帧作为回归夹具。
- **start.sh**：直接 `exec python3 main.py "$@"`（比赛环境 Python 3.12.9 可用）；本地 Windows 验证走 run_match.py 的 `--client-cmd`，不依赖 start.sh。

## 兼容与回滚

- `client/` 是全新目录，不触碰 refs/tools/docs，回滚 = 删目录，零风险。
- 接口契约（GameState/Intent）在里程碑 2 定稿后冻结，改动需三人同步（架构文档第三.2 节）。
