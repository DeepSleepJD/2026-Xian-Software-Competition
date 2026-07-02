# C 基础客户端

这是一个最小 C 参赛客户端。它会连接竞技场服务端，发送 `registration`，收到 `start` 后回复 `ready`，并在每次收到 `inquire` 后发送空动作心跳：

```json
{"actions":[]}
```

它不会选择路线，也不会解析地图语义。它的唯一目的，是展示 TCP 分帧格式和必需的消息流程。

## 运行环境

- Windows 开发：推荐使用 VS Code + WSL2、Remote SSH 或 Dev Container，把最终构建目标保持为 Linux/WSL2。
- Linux/WSL2：可直接使用系统自带或包管理器安装的 C 工具链。
- 不支持：本客户端当前不是 MSVC 原生 WinSock 版本。
- 编译器：支持 C11 的 `cc`、`clang` 或 `gcc`。
- 构建工具：推荐 CMake 3.16+；也保留 `make` 作为最小备用入口。
- 第三方依赖：无，只使用 C 标准库和系统 socket API。

## 构建

Windows + WSL2：

```bash
cmake -S . -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

备用 Makefile 入口：

```bash
make test
```

## 运行

Windows + WSL2：

```bash
./build/basic_c_client --host 127.0.0.1 --port 30000 --player-id 1001 --player-name BasicC --version 0.1
```

Linux/WSL2：

```bash
./build/basic_c_client --host 127.0.0.1 --port 30000 --player-id 1001 --player-name BasicC --version 0.1
```

正常双客户端对战时，请使用两个不同的 `--player-id` 启动两个客户端；单客户端调试时，可以使用服务端的 `client-debug` 调试模式和本地对手。
