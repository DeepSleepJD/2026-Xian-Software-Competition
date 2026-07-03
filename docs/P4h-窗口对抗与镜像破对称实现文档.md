# P4h：hold 自冻修复 + 文书领取 + 窗口对抗修正 + 镜像破对称（实现文档）

> 自包含实施文档：两局现网尸检 → 回归基线 → 6 个改动项（N1/N2 新增高优，1-4 为窗口对抗组）→ 验证清单 → 不做清单。
> 来源：2026-07-03 规则全文精读 + 双 agent 交叉评审 + **09:13 现网两连败逐帧尸检**（`looog/match_2751_20260703_0913{30,49}.jsonl`）。
> ⚠️ 重要：原窗口对抗 4 项（改动 1-4）**解决不了这两局**——两局败因在 N1/N2。实施顺序按本文档编号。

## 0. 现网两连败尸检（2026-07-03 09:13，都 100% 交付、小分输）

### 局 1（091330）：727 : 750 负 litchi-agent(2696)——hold_before_choke 误伤自冻

败因链（逐帧证据）：
- 对手走山路刷任务（终局 raw **180**，routeTaskScore MOUNTAIN:120|WATER:60），**全场从未设卡**（守卫扫描 0 条，guardAP=4 终局未动），r272-300 停在 S10 连续处理 T_008/T_011/T_014（三个 30 分任务）。
- 我方 r~245 到 S09（raw 90），**r250-286 被 `safety.hold_before_choke(S10)` 按住整整 36 帧**：S10 是 KEY_PASS（`guard_max_defense=7`），我方已花 2 支侦察、`squad_available=6 < 7` → "削得穿"保险不成立；对手在 S10 上/正朝 S10 走且 guardAP≥1 → 闸门恒真。期间 economy 空转、delivery 的 MOVE 被压，全发空心跳（state=WAITING 系统等待）。
- **复合 bug**：economy `_propose_economy` 在 hold 命中时直接 `return None`（economy.py:318 附近）——被 hold 的是 S10/S11 的 30 分目标，但**连脚下 0 绕路的 T_007（15 分，expire 320）都被饿死**。T_007 直到 r286 才被领——正是对手吃掉 S10 最后一个任务 T_014、被 hold 的高分目标从候选消失的那一帧。时间线完全咬合。
- 后果：raw 卡 105（差 5 分到 110 里程碑），S10-S13 走廊上 T_012/T_013/T_015/T_019/T_022 共 5 个任务全被领先 ~40 帧的对手扫光；交付 r515 vs 对手 r476。
- **翻盘账**：任一多拿 1 个 15 分任务 → raw 120 → tasks 140→170（110 档 +50）→ **757 > 750 胜**。36 帧冻结正好吃掉了追上 S11/S12/S13 任一任务的时间窗。

### 局 2（091349）：720 : 725 负 "5"(2632)——同点机会剥夺 → 资源饥饿 → 出牌破产

败因链：
- 对手与我方**几乎镜像同速同走大路**（r50-350 每个采样点同边）。它的策略是**资源优先**：S03 冰鉴 r82 被拿走时我们正被 T_001 任务窗口+读条拴住（r82-88）；S07 冰差 3 帧（r163 它领完，我们 r164 到）；S09 快马+官凭 r240-242 在我们读条时被拿；S13 过所 r441 同样。**终局我方 routeResourceCount 为空——全场 0 资源**。
- 直接分账：鲜度 70.72 vs 90.2 → 鲜度分 **127 vs 162（-35）**；任务我方反赢（raw 120 vs 105 → 170 vs 140，+30）。净 -5。
- **出牌破产**（r363-365 S11 DOCK 窗口，0:1 输掉处理权）：兵争点剩 1 触发 NORMAL 保留线、文书 0 张（见下）、鲜度 78.8<80 献贡不可出 → 第 2/3 拍被迫 ABSTAIN。
- **文书领取条件死锁（确定性 bug）**：`economy._resource_has_claim_consumer` 对 PASS_TOKEN/OFFICIAL_PERMIT 要求 `state.my_open_contests()` 非空（当下正开着窗口）才认为有消费者——窗口只存在 3 拍，与"路过资源点"几乎不可能重合 → **文书实践中永远不领**（S03/S13 的过所躺到 r441 被对手拿走），YAN_DIE 全场不可用。
- S03 任务窗口（r82-85）我方获胜但前两拍镜像互平（双方 BING_ZHENG），第 3 拍靠对手倾向统计（≥60% 兵争→切献贡）才破——有运气成分，印证改动 2 的必要性。
- **翻盘账**：+1 冰鉴 = +18 分 → 738 > 725；或 S11 DOCK 有 YAN_DIE 可出赢下处理权（+3~6 分）也够。
- 诚实注记：S03 冰的正面互换（我任务 30 vs 它冰 18+节奏）局部并不亏，输在读条节奏税逐点复利；这属 EV 建模课题（见"不做清单"N3），本轮只修确定性项。

## 1. 回归基线（改后必须保持）

| 基线 | 数值 | 命令 |
|---|---|---|
| 单测 | 183 例全绿（新增在此之上） | `cd client && python -m unittest discover -s tests` |
| vs 官方 demo | 768 分（seed 20260618 与 12345 均是） | `python tools/run_match.py --no-ui --seed 20260618` |
| vs 设卡陪练 | 757 分、100% 交付 | `tools/adversary_guard.py`（参数形式见 run_match.py --help） |
| vs 竞速陪练 | 755 : 737 | `tools/adversary_racer.py` 同上 |

已有测试锚点（改动 1/3 最易碰碎，先读再动）：
`test_plays_bing_zheng_first_for_relevant_window`、`test_irrelevant_window_gets_no_explicit_abstain`、
`test_plays_xian_gong_against_bing_zheng_tendency`、`test_gate_window_spends_last_guard_point`、
`test_plays_bing_zheng_when_not_fresh_enough_for_xian_gong`；safety/hold 相关见 `test_safety.py`、`test_delivery.py`。

## 2. 改动项（按此顺序实施）

### N1（最高优先）：hold_before_choke 误伤修复——两部分

**规则依据**：任务书 8.2 处理中只能等待处理完成（PROCESSING 的对手当帧不可能同时设卡）；6.2.1 设卡 4 帧处理。闸门原设计针对"路过型设卡手"（all-purpose-demo，见 P4e），对"蹲咽喉刷任务、从不设卡"的对手（litchi-agent）成了自杀开关。

**Part A（economy 候选饿死 bug，必修）**：`economy._propose_economy` 中 hold 命中当前 best 目标去路时**不得 `return None`**——应将该目标（以及所有第一跳同样被 hold 的目标）从本帧候选中剔除后**重选**，让脚下/别方向的候选（局 1 的 T_007）正常成交。实现建议：把 hold 判定下沉进 `_pick_target` 的可行性过滤（对每个候选算 `path[1]`，命中 hold 即 continue；spot==cur 的脚下候选天然不受影响），`_propose_economy` 里原判定删除。注意 `pathing.shortest_path` 每候选一次的开销已存在，无新增复杂度。

**Part B（闸门触发收紧）**：`safety.hold_before_choke` 增加释放条件（组合，全部满足才继续 hold）：
1. **从未设卡先验**：本局至今从未观测到对手任何设卡（含已风化）→ 不 hold。需要一个跨帧 flag（建议放 strategy 侧传入，或 safety 模块级 set 记录 `guard_ever_seen`；state 每帧可见全图 guard）。all-purpose-demo 型对手首卡通常在中局前出现，先验在真威胁面前会自动失效；首次被偷袭的一次性代价由攻坚链兜底（停稳相邻 2 坏果=6 攻坚值当帧清）。
2. **hold 时长上限**：同一咽喉连续 hold 超过 12 帧即放行（模块级 dict：choke→起始帧；换目标/对手走人即清零）。有界化最坏损失——12 帧远小于局 1 实付的 36 帧+走廊任务全失。
上限值与先验的组合留调参余地，验证以局 1 重放为准（见验证清单）。顺带评估（可选不改）：`SQUAD_RESERVE_FOR_WEAKEN=6` 对 KEY_PASS(上限 7) 的保险缺口——本局若保留 7 支闸门根本不触发，但会牺牲侦察；建议只记录不动。

**单测**：① 复现局 1 形态（对手停 KEY_PASS 处理中+从未设卡+我方 squad=6）→ economy 仍产出脚下 CLAIM_TASK；② 对手曾设卡+停咽喉 → 前 12 帧 hold、第 13 帧放行 MOVE；③ 对手在场且曾设卡、hold 中 → 原有防陷阱行为不变（P4e 用例回归）。

### N2（高优）：文书领取条件修复

**规则依据**：5.4.3 YAN_DIE 消耗 1 个文书（过所/官凭）；窗口出牌是任务/资源/固定站争夺的唯一近身战手段；文书领取 2 帧、路过型 0 绕路。

**现状**：`economy._resource_has_claim_consumer` 对 DOCUMENT_RESOURCES 返回 `bool(state.my_open_contests())`——要求领取决策帧恰好有开着的窗口，实践恒 False → 全场不领文书 → YAN_DIE 永久不可用（局 2 出牌破产的直接一环）。

**设计**：消费者判定改为**对手在场未交付即 True**（`opp and not opp.delivered and not opp.retired`）——对手在场就可能开窗，文书=窗口保险。价值维持 `RESOURCE_BASE_VALUES` 的 1.0（净值模型自动只在 ~0 绕路时领取，不会为它跑路）；可选把已持有文书总数 ≥2 时 cap 掉（`RESOURCE_CLAIM_CAPS` 已有单类 cap=1，够用）。

**单测**：① 对手在场未交付、脚下有 PASS_TOKEN、无开窗 → 候选存在；② 对手已交付 → 候选消失；③ 已持有 1 张同类 → cap 生效。

### 改动 1：TASK/RESOURCE 窗口估值接通 economy

**规则依据**：5.4.1 窗口触发精确口径——任务/固定站/宫门窗口**仅同帧争抢生成**，已开始处理的非资源对象后手再抢不开窗；资源额外一条：领取中被第 1 次打断也开窗（第 2 次不再开）。5.4.3：一方出有效牌、另一方弃权 → 有效牌方得本拍胜点，弃权=白送。

**现状**：`combat._KEY_CONTEST_SCORES = {"GATE": 50, "PASS": 45, "DOCK": 40}`（line 26），`_contest_score`（line 359）对 TASK/RESOURCE 基分 0，仅目标在交付主线上才补 30（+下一跳 10）。任务点多在主线外 → economy 判值 30+ 的任务，窗口一开 combat 三拍弃权。两层估值模型直接矛盾。

**设计**：
- TASK 窗口：用 `contest.task_id` 查 `state.tasks`，分值 = 里程碑边际
  `_task_points(me.task_score + t.score) - _task_points(me.task_score)`（`from .economy import _task_points`，无循环依赖；嫌私有可上提 `strategy/__init__.py`）。任务查不到 → 0 维持弃权。
- RESOURCE 窗口：分值 = `economy.RESOURCE_BASE_VALUES.get(contest.resource_type, 1.0)`（ICE_BOX=18）；我方持有量已达 `RESOURCE_CLAIM_CAPS` 上限 → 0。
- GATE/PASS/DOCK 与路径加成逻辑不变，最终 `score = max(现有路径逻辑, 新值)`；`score <= 0 → 弃权` 兜底保留。

**单测**：① 主线外 30 分任务 TASK 窗口 → 出有效牌；② raw=130 封顶后同窗口 → 边际 0 → 弃权；③ RESOURCE 窗口 ICE_BOX 持有 0/2 两态；④ 现有 GATE/DOCK 测试不回归。

### 改动 2：镜像破对称出牌（playerId 判别，禁用 Python hash()）

**规则依据**：5.4.4 双方同牌每拍必平；平 2 次 → 非 GATE 对象 18 帧冷却、GATE 6 帧冷却，冷却后再同帧争抢 → 无限循环；双弃权也是平点。S02 DOCK 与 **S14 GATE** 都会死锁（双方 0% 交付）。局 2 的 S03 任务窗口前两拍就是镜像互平，第 3 拍靠倾向统计才破，有运气成分。

**设计（平局反应式，基线零漂移）**：
- 默认出牌逻辑完全不变。仅当**本窗口上一拍双方出了同一张牌**（P4c 的 `window_card_reveals` 按 `contest_id+round_index` 可读）时触发：**角色按 playerId 定**——`switcher = (state.player_id == max(contest.red_player_id, contest.blue_player_id))`。switcher 本拍改出克制镜像牌的牌（克制表按 5.4.4，可负担里挑第一张），非 switcher 重复原牌。镜像局第 2 拍即分胜点。
- **禁用 `hash()`**：进程盐随机，两客户端结果不可控；playerId 大小比较确定且必然不对称。
- 注意窗口固定 3 拍，早分胜点不缩短窗口——本改动的价值是**确定性**（去掉倾向统计的样本依赖）与死锁保险，非节奏。

**单测**：① 上一拍同牌 + 我方高 id → 出克制牌；② 低 id → 重复原牌；③ 无同牌揭示 → 输出与现行为逐字节一致。

### 改动 3：顺位表补 QIANG_XING + 献贡-heavy 反制 + 献贡 floor

**规则依据**：5.4.3 强行——马类增益或疾行令生效中本拍免消耗，否则依次消耗 1 快马、1 短程马；5.4.4 强行是献贡的唯一克制牌。

**设计**：
- `_can_play_card` 加 QIANG_XING：buff 生效中免费可出；未生效仅当持有马且本窗口 `_contest_score ≥ 20`。
- 加 `_opponent_xian_gong_tendency()`（≥60%、样本 ≥2，同兵争口径）→ 顺位 `强行>献贡>兵争`。
- 默认顺位尾部追加**免费强行**：`兵争>验牒>献贡>强行(仅免费)`——有效牌胜弃权，别 ABSTAIN。
- **献贡 floor**：`my_good > 0` 改 `my_good > 1`（好果打 0 丧失交付资格，7.1）。

**单测**：① buff 中其他牌不可负担 → 出强行；② 对手献贡 ≥60% → 首选强行；③ 无 buff 无马 → 强行不可出；④ good=1 不出献贡。

### 改动 4：设卡加公开分差闸（压低悬赏喂分概率）

**规则依据**：6.3.3 悬赏结算条件"攻破方在本结算帧开始时公开总分**低于**设卡方"；卡存活 30 帧即生成悬赏；攻破防 6 卡只需 2 篓坏果（不计分=免费）。7.2/7.3：首张悬赏已交付口径 = 原始 10/18 + **全局一次性** +20 → 30/38；后续每张只加原始分；未交付封顶 25。

**设计**：`_propose_set_guard` 加闸——`state.me.total_score > state.opponent.total_score`（严格领先）时不设卡；落后或持平放行。**注释写"压低悬赏喂分概率"而非"杜绝"**（判定时点在攻破帧，分差可能翻转，这是启发式）。

**单测**：① 总分严格领先 → 不设卡；② 持平/落后 → 照常提议。

## 3. 验证清单（按序执行）

1. `cd client && python -m unittest discover -s tests` —— 183+新增 全绿；
2. **局 1 重放验证 N1**：用 recorder 重放法（memory/项目惯例：逐帧喂 `looog/match_2751_20260703_091330.jsonl` 的 inquire 进 GameState + 跑 economy/safety）断言：r250-260 区间 economy 产出 T_007 的 CLAIM_TASK（Part A），且 hold 在时长上限后放行（Part B）；
3. `python tools/run_match.py --no-ui --seed 20260618` 与 `--seed 12345` —— vs demo ≥768；
4. vs 设卡陪练 ≥757 且 100% 交付（**N1-Part B 重点回归**：确认收紧不削弱对真设卡手的防护）；vs 竞速陪练 ≥755；
5. 镜像死锁无对局回归手段（近镜像自对弈本身死锁），以改动 2 单测为准；
6. 流程约定：跳过 trellis-check 重质检，单测绿 + 对局能跑即推进，里程碑粒度 commit。

## 4. 明确不做的事（留 P5 批量自对弈一起验）

- **N3 同点机会剥夺 EV 建模**（局 2 的 S03 冰：同点对手在我读条时扫货；候选/前瞻 follow 项加"同点对手消耗假设"）——方向对但影响面大（估值全链路），需自对弈定量，本轮不动；
- B2 竞争折扣"拒止价值"调参（0.5 → 0.7± 或拒止加成）；
- INTEL 全链路（领取估值、任务点预标记 −3 帧）；
- VERIFY_GATE 绑 BREAK_ORDER 省 3 帧；悬赏猎取；蹲守选点；
- ICE_BOX cap=2 改按绕路成本判（S06 支线冰本图往返 ~118 帧仍是实亏，零冰局也不值得，已核 09:13 图 E18 S03-S06 BRANCH 38 → 单程 59 帧）。
