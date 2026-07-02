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
- [x] **P2**：经济层完成（2026-07-02，Trellis 任务 07-02-p2-economy-layer）。`strategy/economy.py`：任务/冰鉴统一贪心（净值+一步前瞻，不是草案的比值制——比值制实测漏 90 里程碑）+ 无候选时 WAIT 蹲守 + 冰鉴阈值使用。对打 demo **702 分**（demo 458）、任务 raw 90（172 帧拿满）、100% 交付、鲜度 81 收官。单测 82 例。注意：`inquire.taskScore` 是原始任务分，里程碑奖励（60/90→+15/+35）结算时才补发进 csv
- [x] **P3**：优化层完成（2026-07-02，Trellis 任务 07-02-p3-optimization-layer）。对打 demo **771 分**（demo 458，seed 20260618/12345 一致）：①任务分冲刺——里程碑实为 60/90/110→+15/+35/+50 且封顶 180=raw130+50（任务书 7.2），`TASK_SCORE_GOAL` 90→130 + **边际分值估值**（跨档/封顶都算准），任务分 125→180 拿满；②第二冰鉴——根因是任务分闸门连坐冰鉴领取（raw 拿满经济层整体闭嘴，脚下 0 绕路的 S07 冰鉴都不领），闸门下沉到任务候选枚举后领 2 冰鉴、鲜度分 145→160；③数据定量后判死的：马类（快马省 4 帧短程马省 2.1 帧 ≈ +1 分不值）、T06 解锁（任务分已封顶边际 0）、S06 第 3 冰鉴（往返 118 帧实亏）。单测 83 例。剩余大分池：破关悬赏 100 分（窗口出牌，P4 对抗层范畴）；再往后 P5 自对弈调参
- [ ] **P4（当前最高优先）**：2026-07-02 现网两连败（60/80 vs 727/753，日志 `looog/`）——对手在 S10 咽喉设卡钉死我方 ~190 帧、窗口出牌全弃权、资源全没用。对抗层从加分项变成活命项。**改动清单见 `docs/P4-对抗层改动清单.md`**（败因证据 + 规则依据 + 分优先级改动项 + 验证方案，自包含可直接交给实施 agent）。前两轮（破卡/设卡/削卡/出牌/天气/马匹）已合入并过审；**第三轮见 `docs/P4c-资源利用与出牌修正实现文档.md`**（修 758→771 回归 + 探路预标记 + 出牌成本顺位/对手建模/终局解禁 + 文书防误用）
- [x] **P4d**：守卫半路自锁死锁修复（2026-07-02，Trellis 任务 07-02-p4d-guard-pause-deadlock-fix）。①攻坚闸门——半路被守卫暂停（WAITING+moveDir=PAUSED+nextNodeId 保留）不是停稳，`combat._propose_break_guard` 加 `nextNodeId 空 && 非 PAUSED` 闸，杜绝 134 帧 MOVING_ACTION_FORBIDDEN 刷屏；②削卡放宽——`_propose_squad_weaken` 从只认 MOVING 放宽到含 PAUSED 半路，被拦停后几帧清卡（现网死局 190 帧冻结 → 实测 ~10 帧）；③`strategy/safety.py` 送达优先硬闸（round+到终点帧数+60 余量 ≥ durationRound 时经济候选/WAIT/设卡全停，冰/马/情报/攻坚/削卡保留）；④**清障能力**（实施中发现的同级死锁：S10 开局挂 LANDSLIDE，历史 771 局全靠 demo 做 T04 顺手清障，对手不清则 MOVE 永拒卡死）——停靠时对交付路径下一跳障碍发主车队 CLEAR（6 帧+1 好果；小分队清障不用，8 支人手全留给削卡）；⑤`tools/adversary_guard.py` 设卡陪练（自动选咽喉、对手半路上边当帧设卡、会清障、--max-guards 默认 1）。验证：vs 设卡陪练 **766 分 100% 交付**（修复前对照 80 分未送达）；vs demo seed 20260618/12345 均 **774 分**（基线 771）。单测 148 例
- [x] **P4e**：对抗策略修正（2026-07-03，Trellis 任务 07-02-07-02-p4e-counter-strategy-fix）。背景：现网 vs 官方 all-purpose-demo **525:0 完败**（`looog/match_2751_20260702_214828.jsonl`）——它边走边在身后咽喉设满防卡（S10 r299 + S11 r364），我方削第一张卡耗光 8 支小分队（削卡 1 次=2 支删 2 防，削穿防 6 要 6 支），第二张卡半路撞上被冻 180 帧（**现网被卡形态是 state=MOVING+进度冻结**，非 P4d 的 WAITING+PAUSED——PAUSED 其实是自家派小分队引发的服务器暂停；任务书 8.2 半路禁折返，攻坚需停稳，无兵=无解干等风化），终局未交付全零。改动：①**防陷阱闸门** `safety.hold_before_choke`（无状态）——对手车队停在我方咽喉上且有 guardAP、该点无卡、我方兵力不足削穿满防时，delivery/economy 都不提交进边 MOVE，原地等它走人（亮卡则停稳攻坚链 2 坏果=6 攻坚值当帧清），must_rush 时失效强行进；②**经济慢边禁令**（用户点名"别绕山路做任务"）——候选去/回程需走交付路径之外的 MOUNTAIN/BRANCH 级慢边（系数>1500）直接出局。**注意：初版"绕行≤15帧"上限实测否决**（寻路鲜度主成本下最优主线是水路，帧数上限把大路任务簇+3冰鉴净赚链误判绕行，路线翻转 774→740，归因实验已档）；③蹲守收紧——落后于在场对手时不 WAIT 蹲任务刷新（`safety.ahead_of_opponent`）；④侦察保留量 4→6（留满削穿一张满防卡的兵力）。验证：vs demo seed 20260618/12345 均 **773**（基线 774±噪声，mountain_rounds=0）、vs 设卡陪练 **766** 100% 交付（=P4d 基线）。单测 166 例
- 流程约定：**跳过 trellis-check 等重质检子代理**，快速迭代；单测绿 + run_match 对局能跑即推进，里程碑粒度 commit

## 相关工具

- 已安装 skill `lychee-demo-movement-starter`：把基础工程升级到"能合法移动并跑 100 回合"，调用时需提供任务书、通信协议、调测指南的**绝对路径**。
