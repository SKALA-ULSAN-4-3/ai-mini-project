#!/usr/bin/env bash
# Python 의존성 → LibreOffice/Java → 프로젝트 전용 H2Orestart 설정.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYTHON="${PYTHON:-}"
LO_VERSION="25.8.7.3"
STAGE="시작"

fail() { printf '설치 중단: %s\n' "$*" >&2; exit 1; }
step() { STAGE="$1"; printf '\n[설치] %s\n' "$STAGE"; }
trap 'printf "설치 실패 단계: %s (줄 %s)\n" "$STAGE" "$LINENO" >&2' ERR

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' \
        '사용법: bash data_pipeline/setup_environment.sh' \
        '지원: macOS(Homebrew 필요), Ubuntu 24.04(일반 사용자 + sudo)' \
        'Python 선택: PYTHON=python3.12 bash data_pipeline/setup_environment.sh' \
        'Python 패키지와 시스템 도구를 설치하고 H2Orestart를 프로젝트 프로필에 등록합니다.'
    exit 0
fi
[[ $# -eq 0 ]] || fail '지원하지 않는 옵션입니다. --help를 확인하세요.'
[[ $EUID -ne 0 ]] || fail 'sudo로 스크립트 전체를 실행하지 말고 일반 사용자로 실행하세요.'
if [[ -z "$PYTHON" ]]; then
    PYTHON=python3
    if [[ -x "$VENV/bin/python" ]]; then
        PYTHON="$("$VENV/bin/python" -c 'import sys; print(sys._base_executable)')"
    fi
fi

temporary=""
mounted=""
cleanup() {
    if [[ -n "$mounted" ]]; then hdiutil detach "$mounted" >/dev/null 2>&1 || true; fi
    if [[ -n "$temporary" ]]; then rm -rf -- "$temporary"; fi
}
trap cleanup EXIT

python_usable() {
    command -v "$PYTHON" >/dev/null 2>&1 &&
        "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'
}

java21_usable() {
    [[ -n "${JAVA_HOME:-}" && -x "$JAVA_HOME/bin/java" ]] &&
        "$JAVA_HOME/bin/java" -version 2>&1 | grep -Eq 'version "21([."]|$)'
}

install_macos() {
    command -v brew >/dev/null 2>&1 || fail 'Homebrew를 먼저 설치하세요: https://brew.sh/'
    if ! python_usable; then
        brew install python@3.12
        PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
    fi
    if ! java21_usable; then
        if ! JAVA_HOME="$(/usr/libexec/java_home -v 21 2>/dev/null)"; then
            brew install --cask temurin@21
            JAVA_HOME="$(/usr/libexec/java_home -v 21)"
        fi
    fi
    export JAVA_HOME
    SOFFICE="$PROJECT_ROOT/data/tools/LibreOffice.app/Contents/MacOS/soffice"
    if [[ -e "$PROJECT_ROOT/data/tools/LibreOffice.app" ]]; then
        [[ -x "$SOFFICE" ]] || fail '기존 프로젝트 LibreOffice.app에 soffice가 없습니다. 설치 상태를 확인하세요.'
        "$SOFFICE" --version | grep -Fq "$LO_VERSION" ||
            fail '기존 프로젝트 LibreOffice 버전이 다릅니다. 자동으로 덮어쓰지 않습니다.'
        return
    fi
    case "$(uname -m)" in
        arm64) archive_arch=aarch64; file_arch=aarch64
            expected_sha=e7556aa61e282f89578ebaf35afdb09c94dcf9d6ee7c137004377bee81a6e900 ;;
        x86_64) archive_arch=x86_64; file_arch=x86-64
            expected_sha=110439f207b5e420d7c8e441180c8374431761d549a1c14b584045ac56cd71c5 ;;
        *) fail '지원하지 않는 macOS CPU입니다.' ;;
    esac
    temporary="$(mktemp -d "${TMPDIR:-/tmp}/bid-setup.XXXXXX")"
    dmg="$temporary/LibreOffice.dmg"
    url="https://downloadarchive.documentfoundation.org/libreoffice/old/$LO_VERSION/mac/$archive_arch/LibreOffice_${LO_VERSION}_MacOS_${file_arch}.dmg"
    curl --fail --location --retry 2 --output "$dmg" "$url"
    actual_sha="$(shasum -a 256 "$dmg")"
    [[ "${actual_sha%% *}" == "$expected_sha" ]] || fail 'LibreOffice 설치 파일 SHA-256 불일치'
    mountpoint="$temporary/mount"
    mkdir -p "$mountpoint"
    hdiutil attach -readonly -nobrowse -mountpoint "$mountpoint" "$dmg" >/dev/null
    mounted="$mountpoint"
    mkdir -p "$PROJECT_ROOT/data/tools"
    ditto "$mountpoint/LibreOffice.app" "$PROJECT_ROOT/data/tools/LibreOffice.app"
    hdiutil detach "$mounted" >/dev/null
    mounted=""
}

install_ubuntu() {
    [[ -r /etc/os-release ]] || fail 'Ubuntu 24.04 환경에서 실행하세요.'
    # 시스템 배포판 정보만 읽는다. 프로젝트의 .env는 셸로 실행하지 않는다.
    . /etc/os-release
    [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] ||
        fail '자동 설치는 Ubuntu 24.04만 지원합니다. 다른 배포판은 README의 수동 설치를 참고하세요.'
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv \
        libreoffice-writer libreoffice-java-common openjdk-21-jdk-headless \
        fonts-noto-cjk fonts-noto-core
    JAVA_HOME="/usr/lib/jvm/java-21-openjdk-$(dpkg --print-architecture)"
    export JAVA_HOME
    SOFFICE="$(command -v soffice)"
}

step '운영체제별 LibreOffice · JDK 준비'
case "$(uname -s)" in
    Darwin) install_macos ;;
    Linux) install_ubuntu ;;
    *) fail 'macOS 또는 Ubuntu 24.04 환경이 필요합니다.' ;;
esac

python_usable || fail 'Python 3.10 이상이 필요합니다.'
java21_usable || fail 'JAVA_HOME의 JDK 21 설치와 CPU 아키텍처를 확인하세요.'
[[ -x "$SOFFICE" ]] || fail 'soffice 실행파일을 찾을 수 없습니다.'
"$SOFFICE" --version
step 'Python 가상환경 준비'
if [[ -x "$VENV/bin/python" ]]; then
    existing_version="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    requested_version="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    [[ "$existing_version" == "$requested_version" ]] ||
        fail "기존 가상환경은 Python $existing_version, 선택한 Python은 $requested_version 입니다. PYTHON=python$existing_version 으로 재실행하세요. 기존 환경은 덮어쓰지 않습니다."
fi
"$PYTHON" -m venv "$VENV"
step 'Python 패키지 설치'
"$VENV/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"
step 'H2Orestart 등록'
"$VENV/bin/python" -B "$SCRIPT_DIR/convert_documents.py" --setup --soffice "$SOFFICE"
step '패키지 및 API 로딩 확인'
"$VENV/bin/python" -m pip check
PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$VENV/bin/python" -B -c \
    'import faiss, numpy, pypdf; from data_pipeline.api import app; app.openapi(); print("FAISS · PDF · API 로딩 정상")'
printf '설치 완료. 실행 환경: %s\n' "$VENV/bin/python"
