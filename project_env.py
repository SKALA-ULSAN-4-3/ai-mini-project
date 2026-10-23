"""프로젝트 공통 .env 로딩과 하위 프로그램 실행. 비밀값을 출력하지 않는다."""
from pathlib import Path
import argparse
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parent


def load_env(path=ROOT / ".env"):
    """단일 행 KEY=value 및 따옴표 지원. 이미 설정된 환경변수가 우선한다."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        os.environ.setdefault(name, value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="루트 .env를 적용해 하위 프로그램 실행")
    parser.add_argument("--cwd", default=".", help="프로젝트 루트 기준 작업 폴더")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("실행할 명령이 필요합니다.")
    load_env()
    raise SystemExit(subprocess.call(command, cwd=ROOT / args.cwd))
