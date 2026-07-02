# 2026 西安软件大赛 —《一骑红尘：荔枝争运战》参赛项目

## 项目是什么

编写一个 AI 客户端（TCP + JSON 协议）参加双人对抗贡运赛：600 结算帧内把荔枝从 S01 运到 S15，总分高者胜。提交 ZIP（根目录 `start.sh <playerId> <host> <port>`），Linux 离线环境运行（Python 3.12.9 可用，禁止第三方依赖现场安装）。

## 必读文档（新 session 先读这个）

- **`docs/比赛分析与取胜策略.md`** — 已完成的完整赛题分析：得分结构、路线定量、机制备忘、P0-P5 开发路线图、调测方法。所有战略决策以它为基准。
- **`docs/客户端架构设计.md`** — 已批准的客户端架构（分层 + GameState/Intent 契约 + 铁律兜底 + 三人分工），P1 骨架搭建按它实施，文末有执行清单。
- 任务书 / 通信协议 / 地图配置原文在 `refs/debug-kit-v1/`。

## 目录结构

- `client/` — 我方参赛客户端（P1 起搭建，结构见 docs/客户端架构设计.md）
- `refs/official-base-clients/` — 官方 6 语言基础工程原件（根目录的 python-client 副本已删，framing 参考从这里取）
- `refs/debug-kit-v1/arena/` — 本地裁判服务器 + 官方 demo + 回放 UI（不入库，官方 ZIP 分发）
- `tools/` — run_match.py 本地对局启动器等
- `docs/` — 分析与设计文档

## 本地调测

- **首选**：`python tools/run_match.py`（本项目的对局启动器，默认 50ms/帧 + 自动拉起回放 UI；`--no-ui` 只出分；`--client-cmd "... {player_id} {host} {port}"` 换成自己客户端；`--seed` 指定种子）
- 注意：官方 `test.bat` 在 agent/git-bash 环境下不可用（中文路径过 cmd 边界编码损坏 + GNU timeout 遮蔽 Windows timeout.exe），双击运行则正常。`tools/run_match.py` 即为此而写，P5 批量自对弈也复用它
- 分数在 `refs/debug-kit-v1/arena/server/data.csv`，进程控制台日志在 `tools/logs/`
- 回放 UI：http://127.0.0.1:9091/litchi_delivery_replay/ （PowerShell HTTP 服务，PID 记录在 UI 构建目录 `.lychee_web_server.pid`）

## 硬性约束（违反即输）

- 每帧必发 action（空 `actions:[]` 也是心跳）；连续 60 帧缺动作 = 退赛判负
- `action.round` 必须等于当前 `inquire.round`
- 不得写死 playerId / host / port / 阵营 / 地图（会换地图变体，一切以 `start`/`inquire` 下发为准）
- 决策必须在 500ms/帧内完成

## 当前进度

- [x] 赛题完整分析（见 docs/比赛分析与取胜策略.md）
- [x] P0：跑通本地调测环境（2026-07-02，`tools/run_match.py` 起一局 demo 对局：2002 得 500 / 1001 得 461，均 100% 交付；回放 UI 正常。该分数即官方 demo 基准线）
- [x] 客户端架构定稿（2026-07-02 批准，见 docs/客户端架构设计.md；官方 python-client 副本已删）
- [x] **P1**：client/ 骨架完成（2026-07-02，Trellis 任务 07-02-p1-client-skeleton）。600 帧不掉线 + GameState/Intent 契约冻结 + 寻路/验核/交付：对打官方 demo 100% 交付、428 分（demo 496，差距=任务分杠杆）。单测 53 例，`cd client && python -m unittest discover -s tests`
- [ ] **P2（当前）**：经济层——顺路任务拿满 90 分、资源领取（冰鉴）、鲜度阈值管理（预期 ~650-700）
- [ ] P3-P5：优化层 → 对抗层 → 自对弈调参
- 流程约定：**跳过 trellis-check 等重质检子代理**，快速迭代；单测绿 + run_match 对局能跑即推进，里程碑粒度 commit

## 相关工具

- 已安装 skill `lychee-demo-movement-starter`：把基础工程升级到"能合法移动并跑 100 回合"，调用时需提供任务书、通信协议、调测指南的**绝对路径**。
