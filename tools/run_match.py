#!/usr/bin/env python3
"""本地对局启动器：替代调测包 test.bat 的 Python 实现。

为什么不直接用 test.bat：中文路径在 git-bash/agent 环境到 cmd 的边界上编码损坏，
且 bat 的等待循环依赖 Windows timeout.exe（PATH 里易被 GNU timeout 遮蔽）。
Python 全程走 Unicode API，无此问题，且便于后续批量自对弈（P5）复用。

用法（在仓库根目录）：
    python tools/run_match.py                      # 官方demo vs 官方demo，50ms/帧，跑完拉起回放UI
    python tools/run_match.py --no-ui              # 只跑对局出分
    python tools/run_match.py --seed 20260701      # 指定种子
    python tools/run_match.py --client-cmd "python ../../../python-client/basic_client.py {player_id} {host} {port}"
                                                   # 用自己的客户端当 1001（模板占位符会被替换）
"""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KIT_DIR = REPO_ROOT / "refs" / "debug-kit-v1" / "arena"
SERVER_DIR = KIT_DIR / "server"
CLIENT_DIR = KIT_DIR / "client"
DEMO_DIR = KIT_DIR / "demo"
UI_DIR = KIT_DIR / "ui"
LOG_DIR = REPO_ROOT / "tools" / "logs"

SERVER_EXE = SERVER_DIR / "lychee-arena-server.exe"
DEMO_EXE = DEMO_DIR / "l1-demo.exe"

# 对局结束后服务端在 server/ 目录产出的文件
OUTPUT_FILES = ["replay.txt", "debug_replay.txt", "client_debug.txt", "data.csv", "log.txt"]


def clean_env() -> dict:
    """去掉 cmd 私有的 '=X:' 盘符变量，避免子进程 cwd 解析混乱。"""
    return {k: v for k, v in os.environ.items() if not k.startswith("=")}


def port_is_free(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_process(cmd: list, cwd: Path, log_path: Path, env: dict) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "wb")
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log_file, stderr=subprocess.STDOUT)


def build_player_cmd(template: str | None, player_id: int, host: str, port: int, name: str) -> tuple[list, Path]:
    """返回 (命令行, 工作目录)。无模板时用官方 l1-demo.exe。"""
    if template:
        cmd = template.format(player_id=player_id, host=host, port=port, name=name).split()
        return cmd, REPO_ROOT
    exe = DEMO_EXE if name.startswith("demo") else CLIENT_DIR / "l1-demo.exe"
    cmd = [str(exe), f"--backend-host={host}", f"--backend-port={port}",
           f"--player-id={player_id}", f"--player-name={name}"]
    return cmd, exe.parent


def wait_for_scores(data_csv: Path, timeout_sec: int) -> bool:
    """等待 data.csv 生成且包含玩家分数行（表头 + ≥2 行）。"""
    waited = 0
    while waited < timeout_sec:
        if data_csv.exists():
            lines = data_csv.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            if len(lines) >= 2:
                return True
        time.sleep(2)
        waited += 2
        if waited % 20 == 0:
            print(f"  对局进行中... 已等待 {waited}s")
    return False


def sync_replay_to_ui() -> Path | None:
    replay = SERVER_DIR / "replay.txt"
    if not replay.exists():
        return None
    for build_dir in UI_DIR.glob("LycheeReplay_WebGL_*"):
        streaming = build_dir / "StreamingAssets"
        if streaming.is_dir():
            target = streaming / "replay.txt"
            target.write_bytes(replay.read_bytes())
            return target
    return None


def launch_ui(env: dict) -> None:
    """通过官方 start.ps1 起 9091 端口回放服务并打开浏览器。"""
    for build_dir in UI_DIR.glob("LycheeReplay_WebGL_*"):
        ps1 = build_dir / "start.ps1"
        if ps1.exists():
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                           cwd=str(build_dir), env=env, timeout=30)
            return
    print("[WARN] 未找到回放 UI 构建目录")


def main() -> int:
    parser = argparse.ArgumentParser(description="本地跑一局荔枝争运战对局")
    parser.add_argument("--port", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=20260618)
    parser.add_argument("--round-ms", type=int, default=50, help="每帧动作等待毫秒数（正式为500）")
    parser.add_argument("--wait-sec", type=int, default=300, help="等待对局结束的超时秒数")
    parser.add_argument("--no-ui", action="store_true", help="出分后不拉起回放UI")
    parser.add_argument("--ui-only", action="store_true", help="不跑对局，只同步上一局回放并拉起回放UI")
    parser.add_argument("--client-cmd", help="玩家1001命令模板，占位符 {player_id} {host} {port} {name}")
    parser.add_argument("--demo-cmd", help="玩家2002命令模板，同上")
    parser.add_argument("--match-id", default="local-debug-l1")
    args = parser.parse_args()

    if args.ui_only:
        synced = sync_replay_to_ui()
        print(f"回放已同步到 UI: {synced}" if synced else "[WARN] server/replay.txt 不存在，UI 里是上次已同步的回放")
        print("拉起回放 UI（http://127.0.0.1:9091/litchi_delivery_replay/）...")
        launch_ui(clean_env())
        return 0

    if not SERVER_EXE.exists():
        print(f"[ERROR] 找不到裁判服务端: {SERVER_EXE}")
        return 1
    if not port_is_free(args.port):
        print(f"[ERROR] 端口 {args.port} 被占用，可能有残留对局进程（tasklist 查 lychee/l1-demo）")
        return 1

    for name in OUTPUT_FILES:
        (SERVER_DIR / name).unlink(missing_ok=True)

    env = clean_env()
    procs: list[tuple[str, subprocess.Popen]] = []
    try:
        print(f"[1/3] 启动裁判服务端 127.0.0.1:{args.port}  seed={args.seed}  round={args.round_ms}ms")
        server_cmd = [str(SERVER_EXE), "--mode", "client-debug", "--debug-visibility", "full",
                      "--seed", str(args.seed), "--match-id", args.match_id,
                      "-p", str(args.port), "-r", ".",
                      "-a", str(args.round_ms), "-c", "30000", "-d", "30000"]
        procs.append(("server", start_process(server_cmd, SERVER_DIR, LOG_DIR / "server_console.log", env)))
        time.sleep(3)
        if procs[0][1].poll() is not None:
            print(f"[ERROR] 服务端启动即退出，见 {LOG_DIR / 'server_console.log'}")
            return 1

        print("[2/3] 启动玩家 1001 (client)")
        cmd, cwd = build_player_cmd(args.client_cmd, 1001, "127.0.0.1", args.port, "client-l1")
        procs.append(("client-1001", start_process(cmd, cwd, LOG_DIR / "client_1001.log", env)))
        time.sleep(1)

        print("[3/3] 启动玩家 2002 (demo 陪练)")
        cmd, cwd = build_player_cmd(args.demo_cmd, 2002, "127.0.0.1", args.port, "demo-l1")
        procs.append(("demo-2002", start_process(cmd, cwd, LOG_DIR / "demo_2002.log", env)))

        print(f"等待对局结束（data.csv 出分，超时 {args.wait_sec}s）...")
        if not wait_for_scores(SERVER_DIR / "data.csv", args.wait_sec):
            print(f"[ERROR] 超时未出分。检查 {SERVER_DIR / 'log.txt'} 和 {LOG_DIR}/ 下各进程日志")
            return 1
    finally:
        time.sleep(2)  # 给各进程收到 over 后自然退出的时间
        for pname, p in procs:
            if p.poll() is None:
                p.terminate()

    print("\n=== 对局结束，最终分数 (server/data.csv) ===")
    print((SERVER_DIR / "data.csv").read_text(encoding="utf-8", errors="replace"))
    for name in ("replay.txt", "client_debug.txt", "log.txt"):
        f = SERVER_DIR / name
        print(f"  {name}: {'OK ' + str(f.stat().st_size) + ' bytes' if f.exists() else '缺失'}")

    synced = sync_replay_to_ui()
    if synced:
        print(f"回放已同步到 UI: {synced}")

    if not args.no_ui:
        print("拉起回放 UI（http://127.0.0.1:9091/litchi_delivery_replay/）...")
        launch_ui(env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
