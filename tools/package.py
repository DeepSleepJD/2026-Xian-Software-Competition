"""打包比赛提交 ZIP（任务书第 10 章规范）。

用法：python tools/package.py [--out dist/]

规范要点（10.1/10.2/10.7）：
- ZIP 根目录直接是 start.sh（不能套一层目录）
- start.sh 必须可执行 —— Windows 打 zip 默认丢 unix 权限位，
  这里用 ZipInfo.external_attr 显式写 0755
- shell 脚本必须 LF（.gitattributes 已保证检出为 LF，这里再兜底转换）
- 零第三方依赖（stdlib only），不打包 tests/logs/__pycache__
"""

import argparse
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "client"

EXCLUDE_DIRS = {"tests", "logs", "__pycache__", ".pytest_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".jsonl"}


def collect_files() -> list[Path]:
    out = []
    for p in sorted(CLIENT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(CLIENT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.suffix in EXCLUDE_SUFFIXES:
            continue
        out.append(p)
    return out


def add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    data = path.read_bytes()
    mode = 0o644
    if arcname.endswith(".sh"):
        data = data.replace(b"\r\n", b"\n")     # CRLF 兜底：Linux bash 见 \r 即死
        mode = 0o755                            # 平台要求 start.sh 可执行
    info = zipfile.ZipInfo(arcname, date_time=time.localtime()[:6])
    info.create_system = 3                      # Unix：让权限位生效
    info.external_attr = mode << 16
    zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)


def main() -> int:
    parser = argparse.ArgumentParser(description="打包比赛提交 ZIP")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"xigua_{stamp}.zip"

    files = collect_files()
    assert (CLIENT / "start.sh") in files, "client/start.sh 不存在"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in files:
            add_file(zf, p, p.relative_to(CLIENT).as_posix())

    # 自检（任务书 10.7）：根目录 start.sh + 可执行位 + 无嵌套目录
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "start.sh" in names, "ZIP 根目录缺 start.sh"
        info = zf.getinfo("start.sh")
        assert info.external_attr >> 16 & 0o111, "start.sh 无可执行位"
        assert b"\r" not in zf.read("start.sh"), "start.sh 含 CRLF"
        print(f"打包完成: {zip_path}  ({zip_path.stat().st_size} bytes)")
        for n in names:
            print(f"  {n}")
    print("自检通过：根目录 start.sh / 0755 / LF / 无 tests·logs·pycache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
