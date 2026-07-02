# Java 基础客户端

这是一个最小 Java 参赛客户端。它使用 Maven 作为工程构建工具，运行时只依赖 JDK 标准库。

核心代码位于 `org.lychee.basicclient` 包，入口类是 `org.lychee.basicclient.BasicJavaClient`。

行为流程：

1. 通过 TCP 连接竞技场服务端。
2. 发送 `registration`。
3. 读取 `start`，提取 `matchId` 和 `round`，然后发送 `ready`。
4. 每次读取 `inquire`，提取 `round`，然后发送 `actions: []`。
5. 收到 `over` 后退出；收到 `error` 后打印错误并失败退出。

## 运行环境

- Windows：Windows 10/11，安装 JDK 和 Maven 后在 PowerShell 或 CMD 中运行。
- Linux/WSL2：安装 JDK 和 Maven 后在 shell 中运行。
- JDK 版本：JDK 11 或更高版本。
- Maven 版本：Maven 3.8 或更高版本。
- 第三方运行时依赖：无，只使用 JDK 标准库。
- 构建插件：Maven 会按 `pom.xml` 自动解析编译、打包、运行插件。

## 检查

Windows PowerShell/CMD：

```powershell
mvn test
```

Linux/WSL2：

```bash
mvn test
```

## 构建

Windows PowerShell/CMD：

```powershell
mvn package
```

Linux/WSL2：

```bash
mvn package
```

## 运行

Windows PowerShell/CMD：

```powershell
java -jar .\target\lychee-basic-java-client-0.1.0.jar --host 127.0.0.1 --port 30000 --player-id 1004 --player-name BasicJava --version 0.1
```

Linux/WSL2：

```bash
java -jar target/lychee-basic-java-client-0.1.0.jar --host 127.0.0.1 --port 30000 --player-id 1004 --player-name BasicJava --version 0.1
```

也可以通过 Maven 运行：

```bash
mvn exec:java -Dexec.args="--host 127.0.0.1 --port 30000 --player-id 1004 --player-name BasicJava --version 0.1"
```
