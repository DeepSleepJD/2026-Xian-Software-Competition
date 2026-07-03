import argparse
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    player_id: int
    player_name: str
    version: str
    record_dir: Optional[str] = None
    strategy: str = "default"


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Lychee arena Python client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=30000)
    parser.add_argument("--player-id", type=int, default=1006)
    parser.add_argument("--player-name", default="BasicPy")
    parser.add_argument("--version", default="0.1")
    parser.add_argument(
        "--record-dir",
        default=None,
        help="if set, write each round's inquire (both sides' state) to a JSONL "
        "file in this directory for later analysis",
    )
    parser.add_argument(
        "--strategy",
        default="default",
        choices=["default", "aggressive"],
        help="'aggressive' = the choke-guarding sparring opponent for local "
        "adversarial testing; 'default' = our real client",
    )
    args = parser.parse_args()
    return Config(
        host=args.host,
        port=args.port,
        player_id=args.player_id,
        player_name=args.player_name,
        version=args.version,
        record_dir=args.record_dir,
        strategy=args.strategy,
    )
