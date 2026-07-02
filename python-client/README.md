# Python 参赛客户端

这是一个 Python 参赛客户端。它使用 `pyproject.toml` 作为常规 Python 工程元数据，运行时只依赖 Python 标准库。

它实现了：

- 5 位十进制 UTF-8 字节长度分帧（`framing.py`）。
- `registration` / `start` / `ready` / `inquire` / `action` 流程（`session.py`）。
- 统一的动作构造器（`messages.py`）。
- 一个会「导航 → 交付」的策略（`strategy.py` + `graph.py`）。

## 策略概览（`strategy.py`）

每个结算帧根据公开状态决定主车队动作，目标是**稳定完成交付并最大化总分**：

1. **路线规划**：用 Dijkstra 在地图上求到宫门 S14 的最短路，权重按**鲜度损耗**（水路 < 官道 < 支路 < 山路，再加固定处理的等待损耗）。在没有任务加成时用时分恒为 0，因此鲜度与好果才是主要得分项。
2. **沿途固定处理**：到达 S02/S04/S05/S11/S13 等处理点时先 `PROCESS` 完成，再继续前进。
3. **顺路皇榜任务**：在当前站点领取可完成的皇榜任务（`CLAIM_TASK`），把任务基础分累计冲到约 110——送达分因此从 120 拉满到 240，并解锁用时分与里程碑奖励。缺马时跳过 T06。
4. **障碍与宫门**：目标站点有道路障碍时用 `FORCED_PASS` 强行通过（省下好果）；到 S14 若被对手验核占用（`OBJECT_BUSY`）则持续重试，进入 `RUSH` 阶段后 `VERIFY_GATE`。
5. **交付**：验核完成后进入 S15 `DELIVER`。

对阵官方 L1 demo（本地调测包，多个随机种子）稳定取得约 **730 分 vs demo 约 500 分**。

调测方法见调测包 `调测\test.bat`：把 `调测\client\start.bat` 换成启动本客户端即可（注册 playerId=1001，连接服务端 `127.0.0.1:<port>`）。

## 对局记录与失分分析（`recorder.py` + `analyze.py`）

加 `--record-dir <目录>` 启动客户端，会把每个结算帧的服务端 `inquire`（含双方完整状态、任务、窗口、事件、动作结果）以及结束时的 `over`（双方权威最终分）写成一个 JSONL 记录文件：

```powershell
py -3 .\basic_client.py --host 127.0.0.1 --port 30000 --player-id 1001 --record-dir .\rec
```

对局结束后分析该记录，定位「为什么分不如对手」：

```powershell
py -3 -m lychee_basic_client.analyze .\rec\<对局>_1001_<时间>.jsonl
```

报告分两层：

- **L1 丢在哪一项**：拿 `over` 双方 `scoreDetail` 逐项相减（送达/任务/好果/鲜度/用时/悬赏/惩罚），按落后幅度排序，一眼看出输在哪几项。
- **L2 哪段拉开**：逐帧鲜度曲线对比 + 最快掉队窗口（并给出那段在走哪种路线、有无天气命中、有无增益）；以及双方帧数拆解（各路线移动帧 / 处理 / 验核 / 等待 / 休整·窗口·强制通行的浪费帧）。

注意：对手侧的逐帧对比只在本地 `client-debug` 全可见性记录里完整；正式赛对手私有逐帧数据不公开，但对我方自身的归因始终成立。

## 运行环境

- Windows：Windows 10/11，安装 Python 后在 PowerShell 或 CMD 中运行。
- Linux/WSL2：安装 Python 后在 shell 中运行。
- Python 版本：Python 3.9 或更高版本。
- 必需命令：Windows 推荐 `py -3`，Linux/WSL2 推荐 `python3`。
- 第三方依赖：无，只使用 Python 标准库。

## 检查

Windows PowerShell/CMD：

```powershell
py -3 -m py_compile basic_client.py
py -3 -m unittest discover -s tests
```

Linux/WSL2：

```bash
python3 -m py_compile basic_client.py
python3 -m unittest discover -s tests
```

## 可选的可编辑安装

Windows PowerShell/CMD：

```powershell
py -3 -m pip install -e .
```

Linux/WSL2：

```bash
python3 -m pip install -e .
```

完成可编辑安装后，可以使用下面的控制台命令：

```bash
lychee-basic-python-client --host 127.0.0.1 --port 30000 --player-id 1006 --player-name BasicPy --version 0.1
```

## 不安装直接运行

Windows PowerShell/CMD：

```powershell
py -3 .\basic_client.py --host 127.0.0.1 --port 30000 --player-id 1006 --player-name BasicPy --version 0.1
```

Linux/WSL2：

```bash
python3 basic_client.py --host 127.0.0.1 --port 30000 --player-id 1006 --player-name BasicPy --version 0.1
```
