# C++ 基础客户端

这是一个最小 C++ 参赛客户端。它用于演示公开 TCP 协议，不实现游戏策略。

行为流程：

1. 连接服务端。
2. 发送 `registration`。
3. 读取 `start` 并发送 `ready`。
4. 每次读取 `inquire` 后发送 `actions: []`。
5. 收到 `over` 后退出；收到 `error` 后打印错误并失败退出。

## 运行环境

- Windows 开发：推荐使用 VS Code + WSL2、Remote SSH 或 Dev Container，把最终构建目标保持为 Linux/WSL2。
- Linux/WSL2：可直接使用系统自带或包管理器安装的 C++ 工具链。
- 不支持：本客户端当前不是 MSVC 原生 WinSock 版本。
- 编译器：支持 C++17 的 `c++`、`clang++` 或 `g++`。
- 构建工具：推荐 CMake 3.16+；也保留 `make` 作为最小备用入口。
- 第三方依赖：无，只使用 C++ 标准库和系统 socket API。

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
./build/basic_cpp_client --host 127.0.0.1 --port 30000 --player-id 1002 --player-name BasicCpp --version 0.1
```

Linux/WSL2：

```bash
./build/basic_cpp_client --host 127.0.0.1 --port 30000 --player-id 1002 --player-name BasicCpp --version 0.1
```
