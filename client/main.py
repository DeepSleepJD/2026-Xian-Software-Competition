"""参赛客户端入口：python main.py <playerId> <host> <port>

参数由赛方启动脚本传入（start.sh 同参数转发），不得写死。
队名/版本可用环境变量覆盖：LYCHEE_PLAYER_NAME / （版本见 lychee.VERSION）。
"""

import argparse
import os
import sys

from lychee import VERSION
from lychee.net import Connection
from lychee.recorder import Recorder
from lychee.runtime import Runtime
from lychee.strategy.combat import CombatStrategy
from lychee.strategy.delivery import DeliveryStrategy
from lychee.strategy.economy import EconomyStrategy

DEFAULT_PLAYER_NAME = "西瓜大队"   # 报名队名（2026-07-02 负责人定）；LYCHEE_PLAYER_NAME 可覆盖


def main(argv: list[str]) -> int:
    # Windows 本地调测时 stdout 可能是 GBK 管道，中文日志绝不能反杀客户端
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="荔枝争运战参赛客户端")
    parser.add_argument("player_id", type=int)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args(argv)

    player_name = os.environ.get("LYCHEE_PLAYER_NAME", DEFAULT_PLAYER_NAME)
    conn = Connection.open(args.host, args.port)
    try:
        economy = EconomyStrategy()
        if os.environ.get("LYCHEE_FROZEN_PROBE"):
            # P4m-M2 一次性冻结逃生实验：不注册 CombatStrategy（防削卡拆掉陪练的卡）
            from lychee.strategy.frozen_probe import FrozenProbeStrategy
            strategies = [FrozenProbeStrategy(), DeliveryStrategy(), economy]
        else:
            strategies = [CombatStrategy(economy=economy), DeliveryStrategy(), economy]
        runtime = Runtime(
            conn,
            player_id=args.player_id,
            player_name=player_name,
            version=VERSION,
            strategies=strategies,
            recorder=Recorder.from_env(args.player_id),
        )
        return runtime.run()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
