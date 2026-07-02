# Python 基础客户端

这是一个最小 Python 参赛客户端。它使用 `pyproject.toml` 作为常规 Python 工程元数据，运行时只依赖 Python 标准库。

它演示了：

- 5 位十进制 UTF-8 字节长度分帧。
- `registration` / `start` / `ready` / `inquire` / `action` 流程。
- 使用 `actions: []` 发送空动作心跳。

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
