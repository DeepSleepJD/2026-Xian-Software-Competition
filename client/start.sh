#!/bin/sh
# 比赛提交要求的启动脚本（任务书 10.2）：start.sh <playerId> <host> <port>
# 比赛环境为 Linux + Python 3.12.9，零第三方依赖，直接转发参数给入口。
if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <playerId> <host> <port>" >&2
  exit 1
fi
cd "$(dirname "$0")" || exit 1
# 比赛环境用 python3；本地 Windows git-bash 验证时兜底 python
PY=$(command -v python3 || command -v python) || exit 1
exec "$PY" main.py "$@"
