import socket

from . import __version__
from .config import parse_args
from .session import ClientSession


def main() -> int:
    config = parse_args()
    # print prominently so a running client's build can be verified at a glance
    print(f"=== lychee client build {__version__} ===")
    with socket.create_connection((config.host, config.port)) as sock:
        print(f"connected to {config.host}:{config.port} as player {config.player_id}")
        return ClientSession(sock, config).run()
