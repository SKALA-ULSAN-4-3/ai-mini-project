"""검색어·기간으로 공고 목록 확인 → 공고문만 준비 → 사용자 선택 시 전체 첨부.

공고문 추출은 pypdf를 사용하며 점수 평가는 외부 담당자가 구현한다.
"""
import argparse
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "data_pipeline"

from project_env import load_env
from .common import ROOT, KST, read_json, write_json
from .bid_workflow import prepare_discovery, select_bid
# 기존 Python 호출자의 통신 함수 import도 유지한다.
from .g2b_client import (
    API_URL, MAX_FILE_BYTES, BID_FIELDS, CANDIDATE_FIELDS, FILE_FIELDS,
    CollectionError, OfficialRedirect, parse_response, fetch_page, attachments,
    safe_name, allowed_download, download_file, write_csv, search_candidates, notice_row,
)

def collect(args):
    if getattr(args, "select_bid", None) and not args.resume:
        raise CollectionError("--select-bid는 기존 --resume 폴더에서만 사용할 수 있습니다.")
    if args.resume:
        run_dir = args.resume.resolve()
        print(f"기존 후보로 공고문 준비·선택 처리: {run_dir}", flush=True)
    else:
        load_env()
        key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
        if not key:
            raise CollectionError("루트 .env에 DATA_GO_KR_SERVICE_KEY를 설정하세요.")
        if args.start > args.end or args.limit < 1:
            raise CollectionError("조회 기간과 후보 수집 개수를 확인하세요.")
        queries = list(dict.fromkeys(q.strip() for q in args.query))
        if not all(queries):
            raise CollectionError("요청 검색어는 비워 둘 수 없습니다.")
        items, truncated = search_candidates(key, args.start, args.end, queries, args.limit)
        request = dict(start=str(args.start), end=str(args.end), queries=queries, candidate_limit=args.limit,
                       collected_at=datetime.now(KST).isoformat(), page_limit_reached=truncated)
        run_dir = args.output.resolve() / datetime.now(KST).strftime("%Y%m%d_%H%M%S_%f")
        run_dir.mkdir(parents=True)
        write_json(run_dir / "candidates.json", dict(request=request, items=items))

    chosen = getattr(args, "select_bid", None)
    if chosen:
        if not args.resume:
            raise CollectionError("--select-bid는 --resume과 함께 사용하세요.")
        if args.search_only:
            raise CollectionError("--search-only와 --select-bid를 함께 사용할 수 없습니다.")
        result = select_bid(run_dir, chosen)
        failed = [r for r in result["attachments"] if r["status"] == "failed"]
        print(f"사용자 선택 공고 {chosen}: 전체 첨부 {len(result['attachments'])}개, 실패 {len(failed)}개")
        return 2 if failed else 0
    profile_path = getattr(args, "profile", None)
    if profile_path:
        profile = read_json(profile_path)
    elif (run_dir / "company_profile.json").exists():
        profile = read_json(run_dir / "company_profile.json")
    else:
        profile = {}
    result = prepare_discovery(run_dir, profile, args.search_only, getattr(args, "rhwp", None))
    print(f"공고 목록 {len(result['items'])}건 / 공고문 본문 일치 {len(result['recommended_bid_ids'])}건")
    print("전체 첨부는 사용자 선택 후에만 다운로드합니다. 점수 평가: 외부 연계 대기")
    print(f"수집 경로: {run_dir}")
    attention = sum(r["notice_status"] not in ("extracted", "review_empty_pages") for r in result["items"])
    return 2 if attention and not args.search_only else 0


def main():
    today = datetime.now(KST).date()
    parser = argparse.ArgumentParser(description="나라장터 용역 공고 후보 검색·첨부 저장")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=today - timedelta(days=6))
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=today)
    parser.add_argument("--query", action="append", help="사용자 요청 검색어. 여러 번 지정하면 OR 검색 (기본: 개발)")
    parser.add_argument("--limit", type=int, default=50, help="목록 후보 수집 개수")
    parser.add_argument("--resume", type=Path, help="기존 실행 폴더의 후보를 재사용해 같은 폴더에 다운로드")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "collected")
    parser.add_argument("--search-only", action="store_true", help="링크와 목록만 확인하고 다운로드 생략")
    parser.add_argument("--profile", type=Path, help="기업 프로필 JSON; 공고문 본문 사전 분류에 사용")
    parser.add_argument("--select-bid", help="사용자가 선택한 공고번호_차수 한 건의 전체 첨부 다운로드")
    parser.add_argument("--rhwp", type=Path, help="공고문 HWP/HWPX 변환 실행파일")
    args = parser.parse_args()
    args.query = args.query or ["개발"]
    try:
        return collect(args)
    except (CollectionError, ValueError, OSError) as exc:
        # 인증키나 요청 URL이 포함된 네트워크 예외를 그대로 출력하지 않는다.
        if isinstance(exc, CollectionError):
            print(f"오류: {exc}", file=sys.stderr)
        else:
            print("오류: 입력값, 저장 경로를 확인하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
