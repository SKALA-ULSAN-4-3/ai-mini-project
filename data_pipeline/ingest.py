"""전처리 데이터와 공식 웹 주제 다섯 개를 FAISS에 적재한다."""
import argparse
import json
from pathlib import Path
from project_env import load_env
from .common import DEFAULT_DATASET, read_json, write_json
from .knowledge import KnowledgeStore, ingest_processed
from .web_topics import ingest_topics


def ingest_sources(run_dir, model, pdf=True, web=True):
    """자료 유형별 적재를 한 곳에서 제어한다. 로그 저장은 호출자가 맡는다."""
    result = {}
    if pdf:
        result["pdf"] = ingest_processed(run_dir, KnowledgeStore("pdf", model=model))
    if web:
        ingest_topics(KnowledgeStore("web", model=model))
        result["web"] = KnowledgeStore("web").status()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web-only", action="store_true")
    mode.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()
    load_env()
    log = args.run_dir / "ingestion.json"
    result = read_json(log) if log.exists() else {}
    result.update(ingest_sources(args.run_dir, args.embedding_model,
                                 pdf=not args.web_only, web=not args.pdf_only))
    if args.pdf_only and "web" not in result:
        result["web"] = KnowledgeStore("web").status()
    write_json(log, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
