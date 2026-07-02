# P1 执行计划

> 验证命令统一：`python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --no-ui`
> 分数看 `refs/debug-kit-v1/arena/server/data.csv`，客户端日志在 `tools/logs/`。

## 里程碑 1：600 帧不掉线

- [x] 1.1 建 `client/` 目录骨架（架构文档第二节结构），空模块 + main.py 入口解析 `<playerId> <host> <port>`
- [x] 1.2 net.py：移植官方 framing（5 位十进制长度前缀收发），连接/重试/EOF 处理
- [x] 1.3 protocol.py 最小版：识别 start/inquire/over/error 消息类型，取 round 号；构造注册/ready/心跳 action 消息
- [x] 1.4 runtime.py：主循环（注册 → ready → 每帧 inquire→响应）+ 铁律兜底（异常全捕获、round 匹配、时间预算、空心跳）
- [x] 1.5 recorder.py：每帧收发 jsonl 落盘
- [x] 1.6 start.sh
- [x] **验证 1**：run_match.py 对打官方 demo，全程 600 帧 online=TRUE，data.csv 出分（我方 0 分正常，demo 正常得分）——2026-07-02：1001 online=TRUE round=600，recorder 602收/602发；demo 2002 得 420
- [x] **验证 2**：铁律测试——在策略处人为抛异常，客户端仍打满 600 帧——单测覆盖（CrashingStrategy/UnserializableStrategy/error消息/畸形消息，8 用例全绿）

里程碑 1 备注：over.msg_data 的 round/players 字段名与猜测不符（日志打出 None），M2 对照协议第 9 章修正 over 解析。

## 里程碑 2：GameState/Intent 契约定稿

- [x] 2.1 对照 `refs/debug-kit-v1/一骑红尘：荔枝争运战 通信协议.md` 逐字段解析 start/inquire → state.py GameState（2026-07-02；文档/样例差异见 state.py docstring：name/playerName、resources 回退、guard.active 推导等）
- [x] 2.2 Intent 数据类 + Strategy 基类 + arbiter.py 首版（优先级合并 + 动作类别同帧上限去冲突，防 INVALID_ACTION_CONFLICT）
- [x] 2.3 单测：用 start消息.json / inquire消息.json 夹具驱动 protocol/state（不碰 socket；35 例全绿，含 trellis-check 质检补充的 guard 推导/null 容错用例）
- [x] **验证**：单测全绿 + 集成对局 600 帧满勤、over 结算解析正确；契约草案完成，**待负责人确认后冻结**（冻结记录写 design.md）

## 里程碑 3：寻路 + 主线交付

- [x] 3.1 pathing.py：从 start 地图建图 + Dijkstra（支持换图变体；成本模型=鲜度损耗为主、帧数为次——宫门 390 帧才开，时间不值钱鲜度值钱）
- [x] 3.2 strategy/delivery.py：移动/固定处理/宫门验核/交付状态机 + 被堵绕行/硬闯 + 读条完成推断（含 1 帧处理、中断纠偏、宫门永不发 PROCESS 等时序防御）
- [x] **验证**（2026-07-02）：对打官方 demo 两局（seed 20260618/12345）均 **100% 交付**，得分 428（120交付+176好果+132鲜度）vs demo 496。**未达 461 基准属预期**：461 含任务分杠杆（demo 30 任务分→送达+40/用时+5），任务是 P2 范围；P1 送达链路本身无帧数浪费（被堵 19 帧系 S10 窄口障碍，对抗是 P4）

## 收尾

- [x] ~~全量质量检查（trellis-check）~~ 负责人决定跳过重质检流程，快速迭代（单测 53 例全绿 + 两局对局验证）
- [x] 更新 CLAUDE.md 进度勾选 P1
- [x] 提交 commit（里程碑粒度：c7a8d48 / e4fb2c8 / M3）

## 回滚点

- 每个里程碑验证通过后各提交一次 commit，回滚以里程碑为粒度。
