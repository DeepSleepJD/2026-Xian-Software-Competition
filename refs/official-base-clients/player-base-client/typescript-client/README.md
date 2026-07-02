# TypeScript 基础客户端

这是一个最小 TypeScript 参赛客户端。它使用 Node.js 内置的 `net` 模块完成 TCP 通信，用 TypeScript 提供类型检查，编译后以 Node.js 运行。

行为流程：

- 连接成功后发送 `registration`。
- 收到 `start` 后发送 `ready`。
- 每次收到 `inquire` 后发送 `actions: []`。
- 收到 `over` 后退出；收到 `error` 后打印错误并失败退出。

## 运行环境

- Windows：Windows 10/11，安装 Node.js 后在 PowerShell 或 CMD 中运行。
- Linux/WSL2：安装 Node.js 后在 shell 中运行。
- Node.js 版本：Node.js 18 或更高版本。
- 必需命令：`node`、`npm`。
- 第三方依赖：仅开发期依赖 `typescript` 和 `@types/node`，通过 `npm install` 安装。运行编译后的客户端只需要 Node.js。

## 安装依赖

Windows PowerShell/CMD：

```powershell
npm install
```

Linux/WSL2：

```bash
npm install
```

## 检查

Windows PowerShell/CMD：

```powershell
npm run build
npm test
```

Linux/WSL2：

```bash
npm run build
npm test
```

测试会校验分帧收发、基础动作消息构造，以及客户端最终写入 socket 的出站帧格式。

## 运行

先编译：

```bash
npm run build
```

Windows PowerShell/CMD：

```powershell
node .\dist\src\basic_client.js --host 127.0.0.1 --port 30000 --player-id 1005 --player-name BasicTs --version 0.1
```

Linux/WSL2：

```bash
node dist/src/basic_client.js --host 127.0.0.1 --port 30000 --player-id 1005 --player-name BasicTs --version 0.1
```
