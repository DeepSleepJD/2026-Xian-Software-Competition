# Go 基础客户端

这是一个最小 Go 参赛客户端，只使用 Go 标准库。

它会连接竞技场服务端，发送 `registration`，收到 `start` 后发送 `ready`，并在每次收到 `inquire` 后发送 `actions: []`。

## 运行环境

- Windows：Windows 10/11，安装 Go 后在 PowerShell 或 CMD 中运行。
- Linux/WSL2：安装 Go 后在 shell 中运行。
- Go 版本：Go 1.22 或更高版本，`go.mod` 声明为 `go 1.22`。
- 第三方依赖：无，只使用 Go 标准库。

## 检查与构建

Windows PowerShell/CMD：

```powershell
go test ./...
go build ./...
```

Linux/WSL2：

```bash
go test ./...
go build ./...
```

## 运行

Windows PowerShell/CMD：

```powershell
go run . --host 127.0.0.1 --port 30000 --player-id 1003 --player-name BasicGo --version 0.1
```

Linux/WSL2：

```bash
go run . --host 127.0.0.1 --port 30000 --player-id 1003 --player-name BasicGo --version 0.1
```
