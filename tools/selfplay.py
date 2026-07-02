#!/usr/bin/env python3
"""自对弈验证：候选客户端(工作区) vs 冻结基线客户端(git ref)。

为什么用自对弈当强陪练：现网败因是"任务争夺"——强对手抢先锁任务/走快路先到，
官方 demo 和 tools/adversary_guard 都太弱、不抢任务，复现不了。我方自己 ~768 级
客户端会抢任务、会竞速，是验证"路线/竞速改动是否真的赢下争夺"的最强对标；候选版
对打冻结基线版，直接量出 delta（这也是 P5 自对弈的雏形）。

基线版通过 `git worktree` 在临时目录物化某个 commit，跑完自动清理。每个种子默认
跑两局并交换先后手(1001/2002)，抵消先手/side 偏置。

⚠️ 镜像死锁告诫：候选与基线若行为近乎一致（尤其同走 ROAD 主线），会在可争夺固定
处理站点（如 S02）同帧处理 → 每拍同牌必平 → DRAW 冷却重试 → 双方 0% 交付卡死
（任务书 5.4.4）。因此本工具只适合"路线/时序已明显分叉"的版本对比；要稳健验证竞速/
路线改动，请用 tools/adversary_racer.py（走山路快线、抢任务、起手错拍，天然不镜像）。

用法（仓库根目录）：
    python tools/selfplay.py                          # 候选 vs HEAD 基线，默认多种子×换边
    python tools/selfplay.py --baseline de75fb2       # 指定基线 commit/ref
    python tools/selfplay.py --seeds 20260618 12345   # 指定种子
    python tools/selfplay.py --no-swap                # 不换边，每种子只跑一局(候选=1001)
    python tools/selfplay.py --round-ms 30            # 更快出分(默认 50)
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_MATCH = REPO_ROOT / "tools" / "run_match.py"
DATA_CSV = REPO_ROOT / "refs" / "debug-kit-v1" / "arena" / "server" / "data.csv"
DEFAULT_SEEDS = [20260618, 12345]


def _client_cmd(main_py: Path) -> str:
    # 用正斜杠，避免 run_match.split() 与 Windows 反斜杠冲突
    return f"python {main_py.as_posix()} {{player_id}} {{host}} {{port}}"


def _parse_scores() -> dict[int, dict]:
    """读 server/data.csv → {team_id: {total, tasks, route, progress, freshness}}。"""
    text = DATA_CSV.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    if len(text) < 3:
        raise RuntimeError("data.csv 未出分（行数不足）")
    header = text[0].split(",")
    idx = {name: i for i, name in enumerate(header)}
    out: dict[int, dict] = {}
    for line in text[1:]:
        cols = line.split(",")
        if not cols or not cols[0].isdigit():
            continue
        tid = int(cols[0])
        out[tid] = {
            "total": int(cols[idx["total_score"]]),
            "tasks": int(cols[idx["score_tasks"]]),
            "route": cols[idx["main_route"]],
            "progress": cols[idx["progress"]],
            "freshness": float(cols[idx["freshness"]]),
        }
    return out


def _run_game(seed: int, port: int, round_ms: int,
              cmd_1001: str, cmd_2002: str) -> dict[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(RUN_MATCH), "--no-ui", "--seed", str(seed),
         "--port", str(port), "--round-ms", str(round_ms),
         "--client-cmd", cmd_1001, "--demo-cmd", cmd_2002],
        cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-2000:] + "\n")
        raise RuntimeError(f"run_match 失败 seed={seed} port={port}")
    return _parse_scores()


def main() -> int:
    ap = argparse.ArgumentParser(description="自对弈：候选 vs 冻结基线")
    ap.add_argument("--baseline", default="HEAD", help="基线 git ref（默认 HEAD）")
    ap.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    ap.add_argument("--no-swap", action="store_true", help="不换边，候选恒为 1001")
    ap.add_argument("--round-ms", type=int, default=50)
    ap.add_argument("--port", type=int, default=30000)
    args = ap.parse_args()

    cand_main = REPO_ROOT / "client" / "main.py"
    cand_cmd = _client_cmd(cand_main)

    worktree = Path(tempfile.mkdtemp(prefix="lychee-baseline-"))
    base_ref = subprocess.run(["git", "rev-parse", "--short", args.baseline],
                              cwd=str(REPO_ROOT), capture_output=True, text=True).stdout.strip()
    print(f"物化基线 {args.baseline} ({base_ref}) → {worktree}")
    subprocess.run(["git", "worktree", "add", "--detach", str(worktree), args.baseline],
                   cwd=str(REPO_ROOT), check=True, capture_output=True, text=True)
    base_cmd = _client_cmd(worktree / "client" / "main.py")

    rows: list[tuple] = []
    port = args.port
    try:
        for seed in args.seeds:
            # side A：候选=1001
            sa = _run_game(seed, port, args.round_ms, cand_cmd, base_cmd)
            rows.append((seed, "候选=1001", sa[1001], sa[2002]))
            port += 1
            if not args.no_swap:
                # side B：候选=2002（换边）
                sb = _run_game(seed, port, args.round_ms, base_cmd, cand_cmd)
                rows.append((seed, "候选=2002", sb[2002], sb[1001]))
                port += 1
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                       cwd=str(REPO_ROOT), capture_output=True, text=True)
        shutil.rmtree(worktree, ignore_errors=True)

    print(f"\n=== 自对弈结果  候选(工作区) vs 基线({base_ref}) ===")
    print(f"{'seed':>9} {'side':>10} | {'候选':>26} | {'基线':>26} | 胜")
    cand_tot = base_tot = wins = 0
    for seed, side, c, b in rows:
        def fmt(s):
            return f"{s['total']:4d}(任务{s['tasks']:3d} {s['route']:>8} {s['progress']:>6})"
        win = "候选" if c["total"] > b["total"] else ("基线" if b["total"] > c["total"] else "平")
        wins += 1 if c["total"] > b["total"] else 0
        cand_tot += c["total"]
        base_tot += b["total"]
        print(f"{seed:>9} {side:>10} | {fmt(c)} | {fmt(b)} | {win}")
    n = len(rows)
    print(f"\n候选均分 {cand_tot / n:.1f}  基线均分 {base_tot / n:.1f}  "
          f"delta {(cand_tot - base_tot) / n:+.1f}  候选胜 {wins}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
