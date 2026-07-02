#!/bin/sh
# 比赛提交要求的启动脚本：start.sh <playerId> <host> <port>
# 比赛环境为 Linux + Python 3.12.9，零第三方依赖，直接转发参数给入口。
cd "$(dirname "$0")" || exit 1
exec python3 main.py "$@"
