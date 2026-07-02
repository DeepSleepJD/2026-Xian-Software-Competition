import socket

from . import __version__
from .battle_logger import DEFAULT_LOG_PATH
from .config import parse_args
from .session import ClientSession


def _write_build_marker() -> None:
    """Drop a file whose name is the build version next to the battle log, so the
    running build is verifiable from artifacts alone (not just the console)."""
    try:
        safe = __version__.replace("/", "_").replace("\\", "_")
        marker = DEFAULT_LOG_PATH.parent / f"build-{safe}.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(__version__ + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    config = parse_args()
    # print prominently + drop a marker file so the running build can be verified
    print(f"=== lychee client build {__version__} ===")
    _write_build_marker()
    with socket.create_connection((config.host, config.port)) as sock:
        print(f"connected to {config.host}:{config.port} as player {config.player_id}")
        return ClientSession(sock, config).run()
