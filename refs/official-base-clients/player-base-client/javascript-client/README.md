# JavaScript 基础客户端

这是一个最小 Node.js 参赛客户端。它只使用 Node.js 内置的 `net` 模块，以及 `JSON.parse` / `JSON.stringify`。

行为流程：

- 连接成功后发送 `registration`。
- 收到 `start` 后发送 `ready`。
- 每次收到 `inquire` 后发送 `actions: []`。
- 收到 `over` 后退出；收到 `error` 后打印错误并失败退出。

## 运行环境

- Windows：Windows 10/11，安装 Node.js 后在 PowerShell 或 CMD 中运行。
- Linux/WSL2：安装 Node.js 后在 shell 中运行。
- Node.js 版本：Node.js 18 或更高版本。
- 必需命令：`node`；`npm` 只用于执行检查和测试脚本。
- 第三方依赖：无，不需要 `npm install`。

## 检查

Windows PowerShell/CMD：

```powershell
npm run check
npm test
```

Linux/WSL2：

```bash
npm run check
npm test
```

## 运行

Windows PowerShell/CMD：

```powershell
node .\src\basic_client.js --host 127.0.0.1 --port 30000 --player-id 1005 --player-name BasicJs --version 0.1
```

Linux/WSL2：

```bash
node src/basic_client.js --host 127.0.0.1 --port 30000 --player-id 1005 --player-name BasicJs --version 0.1
```
