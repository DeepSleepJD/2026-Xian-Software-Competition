# P4c 资源利用与出牌修正——实现文档(交接)

> 交接对象:实施 agent。活动 Trellis 任务:`07-02-p4-combat-backlog`。
> 前置阅读:`docs/P4-对抗层改动清单.md`(P4 第一轮背景)。本文档是第三轮改动,自包含。
> 规则原文:`refs/debug-kit-v1/一骑红尘:荔枝争运战 参赛选手任务书.md`(下称"任务书")、同目录《通信协议.md》。所有章节号已核对原文,动手前先读对应段落。

## 0. 背景与本轮范围

P4 前两轮(破卡/设卡/窗口出牌/削卡兜底/天气/马匹)已合入并通过审查。本轮解决审查遗留的四件事:

1. **回归修复(必须)**:对 demo 从 771 掉到 758(seed 20260618 实测)。根因:`economy.py` 给 INTEL/PASS_TOKEN/OFFICIAL_PERMIT 标了 2.5~3.0 的领取价值,但**全代码库没有任何消费这三种资源的逻辑**,经济层绕路白领,帧数和鲜度白亏。
2. **小分队探路预标记(核心新增)**:8 个人手当前只有"被钉死时削卡"一个保险用途,大概率整局 0 消耗作废。探路标记是确定性 tempo 收益,必须用起来。
3. **出牌重构**:成本顺位反了(先烧计分的好果、免费行动点闲置)+ 最后 1 点行动点永久死库存 + 无对手建模。顺带接入 YAN_DIE,让文书资源有真实价值。
4. **文书防误用铁律 + 若干小修**。

**本轮不做**(明确排除,防止范围蔓延):SQUAD_CLEAR / SQUAD_REINFORCE、FORCED_PASS、天气逻辑改动、寻路改动。

---

## 1. 规则依据(数值已逐条核对任务书)

### 1.1 探路标记(任务书 6.4.1)
- 生成方式:情报(INTEL,主车队 USE_RESOURCE)或小分队探路(SQUAD_SCOUT,1 人手,延迟生效——现网实测派出到落地 ~3 帧;山雾天气下 SQUAD_SCOUT 延迟 +2,任务书 2.5)。
- 效果:该节点有本队可用标记时,**处理帧数 -3,最低 2 帧**,消耗最早的 1 个标记。适用:领取资源、皇榜任务处理、**宫门验核**、主车队清障、通用处理(登船/换乘等)。
- 有效期:生成帧 X 起到 X+45 帧可用,X+46 清理。同队同节点**不叠加**。处理失败/中断/窗口平局**不消耗**标记。
- 标记是公开节点状态。⚠️ 实现注意:`NodeState.scouted` 字段已解析(`state.py:314`),但**两局现网日志里即使对手标记存在,我方收到的 `scouted` 始终为空**——不要依赖它,以 `SCOUT_MARKER_ADD / SCOUT_MARKER_EXPIRE / SCOUT_MARKER_CONSUME` 事件(payload 含 playerId/targetNodeId/expireRound/remainingTriggers)自行维护本队标记台账,`scouted` 仅作辅助。

### 1.2 情报(任务书 3.3.4)
- 只能停靠节点时用(MOVING/WAITING 不能用);指定目标节点;**沿路线边累计距离 ≤15**,超限被拒但不消耗。
- ⚠️ 本图边长 18~64,距离 15 意味着情报**基本只能标自己脚下的节点**(例外:S14→S15 距离 10)。这决定了它只配当低价值顺手货。
- 动作字段:USE_RESOURCE + resourceType=INTEL + 目标节点——**实施前在《通信协议.md》动作参数表核实 targetNodeId 字段名**。

### 1.3 文书(任务书 3.3.3)——规则陷阱
- 过所(PASS_TOKEN)/官凭(OFFICIAL_PERMIT)唯一用途:提交验牒牌(YAN_DIE)时**系统自动消耗** 1 个。
- **主动 USE_RESOURCE 文书 = 资源扣除且无任何效果,不返还。** 代码必须保证永远不对文书发 USE_RESOURCE。

### 1.4 出牌(任务书 5.4.3 / 5.4.4 / 3.3.5)
- 成本:YAN_DIE=1 文书;QIANG_XING=1 马(有马类 buff 或疾行令生效时本拍免消耗);XIAN_GONG=1 好果且鲜度≥80;BING_ZHENG=1 护卫行动点(每队 4 点,唯一用途,不恢复,终局作废)。
- 克制矩阵(行=我方,胜/负/平):

| 我 \ 敌 | YAN_DIE | QIANG_XING | XIAN_GONG | BING_ZHENG |
|---|---|---|---|---|
| YAN_DIE | 平 | 胜 | 负 | 负 |
| QIANG_XING | 负 | 平 | 胜 | 负 |
| XIAN_GONG | 胜 | 负 | 平 | 胜 |
| BING_ZHENG | 胜 | 胜 | 负 | 平 |

- 真实机会成本排序:**BING_ZHENG ≈ 0(死资源)≤ YAN_DIE(文书无他用)< QIANG_XING(马有移动价值)< XIAN_GONG(1 好果 ≈ 1.8 真实分)**。强度上 BING_ZHENG 压制 YAN_DIE(多克一张牌),故默认顺位 BING_ZHENG → YAN_DIE → XIAN_GONG。
- 对手明牌历史可从 `WINDOW_CARD_REVEAL` 事件读取(payload:contestId/roundIndex/redCard/blueCard/winner),我方红蓝方用 `state.my_team_id` 判断。

### 1.5 小分队(任务书 3.4)
- 初始 8 人手;每帧最多 1 个小分队动作(超发=全不执行+计 1 次非法;arbiter 已按 squad 类别限 1,不需要改);人手不足被拒不扣。SCOUT 1 人 / WEAKEN 2 人。

### 1.6 本图处理点数据(来自 start.gameplay.processNodes,现网实测)
S02 TRANSFER 4 帧 / S04 BOARD 7 / S05 WATER_TRANSFER 6 / S11 PASS_TRANSFER 5 / S13 PALACE_TRANSFER 5 / **S14 VERIFY 6**。标记减时后:4→2、7→4、6→3、5→2。**禁止硬编码这些节点 ID,一律读 `state.process_nodes`**(会换图)。

---

## 2. 改动清单

### A. 【必须,先做】经济层资源估值真实化(`client/lychee/strategy/economy.py`)

现状:`RESOURCE_BASE_VALUES`(约 L66-74)= `{ICE_BOX:18, FAST_HORSE:8, SHORT_HORSE:6, PASS_TOKEN:2.5, OFFICIAL_PERMIT:2.5, INTEL:3.0, BOAT_RIGHT:1.0}`。

改为(配合本轮 C 项 YAN_DIE 接入后的真实价值):

| 资源 | 新值 | 理由 |
|---|---:|---|
| ICE_BOX / FAST_HORSE / SHORT_HORSE | 不变 | 已有消费者 |
| PASS_TOKEN / OFFICIAL_PERMIT | **1.0** | 消费者=YAN_DIE(C 项);若 C 项未合入则为 0 |
| INTEL | **0.5** | 消费者=D 项脚下标记;若 D 项未做则为 0 |
| BOAT_RIGHT | 1.0 不变 | 本图 BOARD 的 `requiredResourceTypes` 为空、非硬需求;但**换图可能必需**——见 A-2 |

净值框架(`net_of`,估值 − 绕路帧×0.12)会用小价值自动否掉一切绕路领取,达到"只白捡 0 绕路"的效果,不需要额外硬门槛。

**A-2 防御性检查**:`_candidates` 里若某资源出现在任一 `state.process_nodes[*].required_resource_types` 中且该处理点在当前交付路径上,则该资源按硬需求处理(价值临时抬高到 ICE_BOX 级),避免换图后水路走不了。加单测:构造 BOARD 要求 BOAT_RIGHT 的假地图,断言路径含 S04 时 BOAT_RIGHT 被领取。

**验收**:`python tools/run_match.py --client-cmd "python client/main.py {player_id} {host} {port}" --no-ui --seed 20260618`(及 `--seed 12345`)总分**恢复 ≥771**。

### B. 【核心】小分队探路预标记(`client/lychee/strategy/combat.py` 新增 `_propose_squad_scout`)

**目标行为**:沿交付路径,对前方"重处理节点"在到达前预挂探路标记,零主车队帧成本换 2~3 帧/点。

触发条件(全部满足才提议,优先级常量 `PRIORITY_SQUAD_SCOUT = 127`,低于 weaken 的 128——同为 squad 类别,arbiter 自动让削卡优先):
1. 目标 = 交付路径(复用 `_terminal_path`)上最近的、`process_round >= SCOUT_MIN_PROC_FRAMES(=4)` 的处理节点(读 `state.process_nodes`);
2. 我方到该节点 ETA ≤ `SCOUT_ETA_MAX(=40)` 帧(用 `pathing.path_frames` 算路径前缀;标记寿命 45,派出延迟 ~3,留余量);
3. 该节点无本队有效标记且无在途 scout 订单——**自建台账**:内部 dict 记录 `{node_id: expire_round}`,由 `SCOUT_MARKER_ADD`(本队 playerId)登记、`SCOUT_MARKER_EXPIRE/CONSUME` 注销;在途订单记 `{node_id: dispatch_round}`,超过 ~8 帧未见 ADD 视为失败可重发;
4. 人手预算:`me.squad_available - 1 >= SQUAD_RESERVE_FOR_WEAKEN(=4)`——给削卡保险留 4 人(拆一张满防卡需 6 人,但 4 人可削 4 点防+好果补刀,权衡后取 4;参数化)。

动作:`{"action": "SQUAD_SCOUT", "targetNodeId": <node>}`。任何主车队状态都可发(现网实测对手 MOVING/PROCESSING 中都在派队),不要加 IDLE 门。

**注意**:每帧 `propose` 只返回一个 squad intent(weaken 或 scout),不要同帧两个——arbiter 会丢弃低优先的那个,但没必要制造噪音。

### C. 出牌重构(`combat.py` `_propose_window_cards`,现 L156-169)

三处改动:

**C-1 顺位改为成本序 + 对手反制**:
```
reserve = 0 if (state.phase == "RUSH" or contest.contest_type in ("GATE", "PASS")) else 1
if 对手兵正倾向:                          # 见 C-2
    card = XIAN_GONG(若鲜度≥80且好果>0) → BING_ZHENG(若点数>reserve) → YAN_DIE(若文书≥1) → ABSTAIN
else:
    card = BING_ZHENG(若点数>reserve) → YAN_DIE(若文书≥1) → XIAN_GONG(若鲜度≥80且好果>0) → ABSTAIN
```
- `reserve` 逻辑同时修复"最后 1 点永久死库存"缺口:RUSH 期或 GATE/PASS 窗口允许花到 0。
- YAN_DIE 出牌时**不发任何 USE_RESOURCE**,系统自动扣文书(规则 1.3);文书数 = `me.resources` 里 PASS_TOKEN+OFFICIAL_PERMIT 之和。

**C-2 对手建模(轻量)**:CombatStrategy 增加实例状态,逐帧扫 `WINDOW_CARD_REVEAL` 事件累积对手明牌计数(按 `my_team_id` 取对面颜色那列)。"兵正倾向" = 对手累计明牌 ≥2 张且 BING_ZHENG 占比 ≥60%。XIAN_GONG 克 BING_ZHENG,这是唯一值得烧好果的场景(DeepExpress 实测全场兵正)。

**C-3 同拍连续性**:同一窗口 3 拍之间保持策略一致(状态放实例变量,不依赖跨帧重算出牌一致性,但也不强求三拍同牌)。

### D. 【可选,低优先】情报脚下使用(`combat.py` 或 `economy.py`)

到达处理点后、发 PROCESS 前,若 `me.resources["INTEL"] ≥ 1` 且脚下节点 `process_round ≥ 5` 且无本队标记:先发 `USE_RESOURCE INTEL targetNodeId=当前节点`(1 帧),下帧再 PROCESS(-3 帧),净赚 ~2 帧。距离 ≤15 的限制在"标脚下"场景恒满足。实施前核实协议里 USE_RESOURCE 的目标节点字段名;若字段不存在或被拒,退避并放弃该功能(价值本来就小)。

### E. 文书防误用铁律(防御性,必做,5 分钟)

`economy.py` 所有 USE_RESOURCE 提议路径(现有冰鉴 `_propose_ice_use`、马匹 `_propose_horse_use`)加断言/白名单:**USE_RESOURCE 的 resourceType 只允许 {ICE_BOX, FAST_HORSE, SHORT_HORSE, INTEL}**。文书主动使用=白扣(规则 1.3),用白名单杜绝未来改动误踩。加一条单测。

### F. 【可选】上轮遗留 nits(顺手修,不强制)

1. `_break_action`(combat.py L88-):坏果过杀——`bad = min(2, my_bad, ceil(need/3))`,防守值 1 的残卡别扔 2 坏果(坏果是免费攻坚弹药,省着打第二张卡)。
2. `_pending_use_resource` 同帧覆盖:改成 dict 按 resourceType 记录,或在 `_read_feedback` 里用 actionResult 自带的 action 回读。
3. 马匹长边省帧估算(`_horse_saved_frames` MOVING 分支):当前把"剩余路程超出 buff 时长"的场景算成 0,正确公式是 `min(duration, base) - ceil(min(duration*speed, remaining)/speed)` 一类;修不修都行,只影响漏用。

---

## 3. 验收标准(全过才算完)

1. `cd client && python -m unittest discover -s tests` 全绿;新增单测覆盖:A(幻影价值不再绕路领取:构造 10 帧绕路的 INTEL 节点,断言无 CLAIM 候选)、A-2、B(ETA 内提议 scout / 标记台账去重 / 人手预算 / weaken 优先于 scout)、C(默认兵正优先 / 文书出验牒 / 兵正倾向触发鲜贡反制 / RUSH 或 GATE 窗口花掉第 4 点)、E(USE_RESOURCE 白名单)。
2. **demo 回归:seed 20260618 与 12345 两把,总分均 ≥771**(这是本轮的硬门槛,758 就是被 A 项根因打下来的)。
3. 现网日志回放冒烟(两局 `looog/*/logs/*.jsonl`,参考 P4 清单 §3 的回放驱动写法,注意用 `msg_name` 分发 start/inquire):全策略栈逐帧 propose+merge **零异常**;match4(水路局)断言:去 S04 途中(ETA≤40 时)提议过 `SQUAD_SCOUT S04`。
4. 陪练局(`tools/` 下若已有 bully 客户端):被拦→破卡→交付链路不回归。

## 4. 硬性约束(违者直接输)

- 每帧必发 action;`action.round == inquire.round`;500ms/帧内决策。
- **不硬编码**节点 ID/资源分布/处理帧数,一律读 `start`/`inquire`(`state.process_nodes`、`node_type`、`resourceStock`)。
- 每帧动作额度:主车队/小分队/窗口出牌/终局急策各 1(任务书 4.1);arbiter 已按类别限流,新增动作走 Intent,不要绕过 arbiter 直发。
- 文书永不 USE_RESOURCE(E 项白名单)。
- 现有 GameState/Intent 契约、delivery 铁律、771 基准不得回退。

## 5. 预期收益

| 项 | 预期 |
|---|---|
| A 回归修复 | +13(758→771 基准找回) |
| B 探路预标记 | 主路线 3~4 个重处理点 × 2~3 帧 ≈ 8~11 帧 ≈ +1~1.5 分;附带缩短被对手窗口抢占的暴露期(S02 被独占那种 13 帧亏损) |
| C 出牌重构 | 好果不再无谓消耗(每窗口省 1~3 好果 ≈ 2~5 分);4 点行动点用满;对兵正型对手窗口胜率显著提高 |
| D/E/F | 防错 + 尾部小分 |
